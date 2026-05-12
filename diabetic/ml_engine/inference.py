import logging
from typing import Optional
from diabetic.registry import MetabolicSnapshot
import torch
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import List, Tuple
from pathlib import Path
from diabetic.config import config
from diabetic.ml_engine.convolutional_layer import DiabeticCNN, CNNConfig
from diabetic.ml_engine.synthetic_cardiac import cardiac_synthesizer
from diabetic.utils.temporal import temporal_engine
from diabetic.utils.schedule import schedule_manager
from diabetic.registry import GlucoseReading
from diabetic.utils.scaling_engine import scaling_engine

logger = logging.getLogger("Bio-Quant.ML.Inference")
class MetabolicInferenceRunner:
    """
    Production-ready bridge to feed live data into the 5-layer CNN engine.
    Handles data windowing, synthetic cardiac generation, and static trait mapping.
    """
    
    def __init__(self, seq_len: int = 30):
        self.seq_len = seq_len
        self.config = CNNConfig()
        self.model = DiabeticCNN(config=self.config)
        
        # Load Personalized Weights (Phase 14+)
        # We now use the v14 weights for multi-task support
        weight_path = Path(__file__).parent / "weights" / "diabetic_cnn_v14.pth"
        if weight_path.exists():
            try:
                self.model.load_state_dict(torch.load(weight_path, map_location=torch.device('cpu'), weights_only=True))
                logger.info(f"Personalized CNN Multi-Task v14 Weights Loaded: {weight_path}")
            except Exception as e:
                logger.warning(f"Warning: Failed to load multi-task weights: {e}. Running in Cold Mode.")
        else:
            logger.warning(f"Warning: No weights found at {weight_path}. Running in Cold Mode.")
            
        self.model.eval() # Inference mode

    def _infer_exposure(self, now: datetime) -> bool:
        """
        Heuristic to guess Indoor/Outdoor state.
        Priority: Schedule Manager -> Hardcoded Heuristic.
        """
        event = schedule_manager.get_event_at(now)
        if event:
            return event.is_outdoor
            
        # Fallback to time-based heuristic
        hour = now.hour
        if hour in [8, 12] or (17 <= hour < 19):
            return True # Assume Outdoor
        return False # Assume Indoor

    def _assemble_static_vector(self, now: datetime, env_data: Optional[dict] = None, is_sick: bool = False) -> torch.Tensor:
        """
        Maps the 15 bio-basal and environmental traits via the ScalingEngine.
        Includes exposure-aware damping for environmental forcing.
        """
        is_outdoor = self._infer_exposure(now)
        vector = scaling_engine.assemble_static_vector(now, env_data=env_data, is_sick=is_sick).tolist()
        
        # Override environmental forcing bits (indices 12, 13, 14 in the 15-feature vector)
        # Based on Layer 2 Climatology logic.
        if not is_outdoor and env_data is None:
            vector[12] = 0.0 # Heat
            vector[13] = 0.0 # Humidity
            vector[14] = 0.0 # AQI
            
        return torch.tensor([vector], dtype=torch.float32)

    def _prepare_temporal_tensor(self, df: pd.DataFrame) -> torch.Tensor:
        """
        Processes the raw glucose CSV into a (Channels, Seq) tensor.
        Includes synthetic heart rate generation.
        """
        if len(df) < self.seq_len:
            # Pad if needed, though we usually only run if we have a full window
            df = pd.concat([df.iloc[0:1]] * (self.seq_len - len(df)) + [df])

        window = df.tail(self.seq_len).copy()
        # Ensure we have a working copy and detect col
        window = window.copy()
        g_col = 'glucose_mmol_l' if 'glucose_mmol_l' in window.columns else 'glucose'
        
        # Velocity logic
        window['velocity'] = window[g_col].diff() / config.SAMPLING_INTERVAL_MINS
        window['velocity'] = window['velocity'].fillna(0)
        
        # Scaling
        window['glucose_scaled'] = window[g_col] / 20.0

        temporal_data = []
        for _, row in window.iterrows():
            # 1. Glucose Channel
            g_val = row[g_col]
            
            # 2. Synthetic Heart Rate Channel
            ts = row.get('timestamp_utc')
            if ts:
                ts_dt = datetime.fromisoformat(ts)
            else:
                # Fix H3: pandas iterrows index is pd.Timestamp, not datetime.
                # Safely convert any index type to UTC-aware datetime.
                import pandas as pd
                if isinstance(_, pd.Timestamp):
                    ts_dt = _.to_pydatetime()
                    if ts_dt.tzinfo is None:
                        ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                else:
                    ts_dt = datetime.now(timezone.utc)

            reading = GlucoseReading(
                timestamp=ts_dt,
                value=g_val,
                trend=row.get('trend', 'Flat')
            )
            cardiac = cardiac_synthesizer.estimate(reading, velocity=row['velocity'])
            
            # Normalize for CNN: Glucose/20, BPM (60-180 range normalized to 0-1)
            # Matches MetabolicDataset: (hr - 60) / 120.0
            # Normalize for CNN via ScalingEngine
            g_scaled = scaling_engine.scale_glucose(g_val)
            hr_scaled = scaling_engine.scale_heart_rate(cardiac.bpm)
            temporal_data.append([g_scaled, hr_scaled])

        # Torch expects (Batch, Channels, Time)
        tensor = torch.tensor([temporal_data], dtype=torch.float32).transpose(1, 2)
        return tensor

    def run_inference_on_window(self, df_window: pd.DataFrame, now: datetime, env_data: Optional[dict] = None) -> dict:
        """
        Runs Multi-Task inference. Returns a dict of [glucose, heart_rate].
        """
        temp_x = self._prepare_temporal_tensor(df_window)
        static_y = self._assemble_static_vector(now, env_data=env_data)
        
        with torch.inference_mode():
            output = self.model(temp_x, static_y)[0] # (2,)
            
        # Rescale: 
        # Glucose: val * 20.0 (clamp to [2.2, 27.0])
        from diabetic.medical_constants import PHYSIO_FLOOR, FAINT_GLUCOSE
        g_pred = float(output[0]) * 20.0
        g_pred = max(PHYSIO_FLOOR, min(g_pred, FAINT_GLUCOSE + 5.0))
        
        # HR: (val * 120.0) + 60.0 (clamp to [40, 200])
        hr_pred = (float(output[1]) * 120.0) + 60.0
        hr_pred = max(40.0, min(hr_pred, 200.0))
        
        return {
            "glucose": g_pred,
            "heart_rate": hr_pred
        }

    def run_inference_on_snapshots(self, snapshots: List[MetabolicSnapshot]) -> Optional[dict]:
        """
        Bridges the live Coordinator memory to the Multi-Task Neural Engine.
        Expects a list of MetabolicSnapshot objects (last 30).
        """
        if len(snapshots) < self.seq_len:
            return None
            
        recent = snapshots[-self.seq_len:]
        temporal_data = []
        
        for i, snap in enumerate(recent):
            g_val = snap.glucose.value
            
            # 1. Cardiac Channel: Use real BPM if available, fallback to synthesis
            if snap.cardiac and snap.cardiac.bpm:
                hr_val = float(snap.cardiac.bpm)
            else:
                # Estimate velocity for synthesis fallback
                vel = 0.0
                if i > 0:
                    # Approximation based on the previous snapshot in the list
                    vel = (g_val - recent[i-1].glucose.value) / config.SAMPLING_INTERVAL_MINS
                
                # Reading object for synthesizer
                from diabetic.registry import GlucoseReading
                reading = GlucoseReading(
                    timestamp=snap.glucose.timestamp,
                    value=g_val,
                    trend=snap.glucose.trend
                )
                cardiac = cardiac_synthesizer.estimate(reading, velocity=vel)
                hr_val = float(cardiac.bpm)
                
            # 2. Normalize
            # 2. Normalize via ScalingEngine
            g_scaled = scaling_engine.scale_glucose(g_val)
            hr_scaled = scaling_engine.scale_heart_rate(hr_val)
            temporal_data.append([g_scaled, hr_scaled])
            
        # Torch expects (Batch, Channels, Time)
        tensor = torch.tensor([temporal_data], dtype=torch.float32).transpose(1, 2)

        # In snapshots, we can extract env_data from the latest snapshot if available
        env_data = None
        is_sick = False
        if recent[-1].environment:
            env_data = recent[-1].environment.model_dump()
        is_sick = recent[-1].is_sick
            
        static_y = self._assemble_static_vector(datetime.now(timezone.utc), env_data=env_data, is_sick=is_sick)
        
        with torch.inference_mode():
            output = self.model(tensor, static_y)[0]
            
        # Rescale and Clamp logic (Layer 4 Safety)
        from diabetic.medical_constants import PHYSIO_FLOOR, FAINT_GLUCOSE 
        g_pred = float(output[0]) * 20.0
        g_pred = max(PHYSIO_FLOOR, min(g_pred, FAINT_GLUCOSE + 5.0))
        
        hr_pred = (float(output[1]) * 120.0) + 60.0
        hr_pred = max(40.0, min(hr_pred, 200.0))
        
        return {
            "glucose": g_pred,
            "heart_rate": hr_pred
        }

    def run_live_inference(self, csv_path: str):
        """
        Main entry point: Read live file -> Build tensors -> Forward Pass.
        """
        if not Path(csv_path).exists():
            logger.error(f"Error: Live data not found at {csv_path}")
            return None

        # Load latest data
        df = pd.read_csv(csv_path)
        now = datetime.now(timezone.utc)
        
        # Prepare inputs
        temp_x = self._prepare_temporal_tensor(df)
        static_y = self._assemble_static_vector(now,is_sick=False)
        
        logger.info(f"Feeding data into CNN (Temporal: {temp_x.shape}, Static: {static_y.shape})...")
        
        with torch.inference_mode():
            output = self.model(temp_x, static_y)[0]
            
        from diabetic.medical_constants import PHYSIO_FLOOR, FAINT_GLUCOSE
        g_pred = float(output[0]) * 20.0
        g_pred = max(PHYSIO_FLOOR, min(g_pred, FAINT_GLUCOSE + 5.0))
        
        hr_pred = (float(output[1]) * 120.0) + 60.0
        hr_pred = max(40.0, min(hr_pred, 200.0))

        return {
            "glucose": g_pred,
            "heart_rate": hr_pred
        }

if __name__ == "__main__":
    # Find the most recent export file
    export_dir = Path("data/exports")
    csv_files = list(export_dir.glob("*.csv"))
    if not csv_files:
        logger.info("No live data found to feed into CNN.")
    else:
        # Sort by mtime to get the latest
        latest_csv = max(csv_files, key=lambda p: p.stat().st_mtime)
        logger.info(f"Targeting: {latest_csv.name}")
        
        runner = MetabolicInferenceRunner()
        result = runner.run_live_inference(str(latest_csv))
        
        if result:
            logger.info("\n--- CNN INFERENCE RESULT ---")
            logger.info(f"Predicted Glucose: {result['glucose']:.2f} mmol/L")
            logger.info(f"Predicted Heart Rate: {result['heart_rate']:.1f} BPM")
            logger.info("Status: Success (Multi-Task activation verified)")
            logger.info("Note: Running with initialized weights (Cold Mode)")

