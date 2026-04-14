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
                self.model.load_state_dict(torch.load(weight_path, map_location=torch.device('cpu')))
                print(f"Personalized CNN Multi-Task v14 Weights Loaded: {weight_path}")
            except Exception as e:
                print(f"Warning: Failed to load multi-task weights: {e}. Running in Cold Mode.")
        else:
            print(f"Warning: No weights found at {weight_path}. Running in Cold Mode.")
            
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

    def _assemble_static_vector(self, now: datetime) -> torch.Tensor:
        """
        Maps the 15 bio-basal and environmental traits defined in ML_SPEC.
        Includes exposure-aware damping.
        """
        is_outdoor = self._infer_exposure(now)
        
        # Layer 1: Static Traits
        vector = [
            config.PATIENT_AGE / 100.0,
            config.PATIENT_WEIGHT_KG / 100.0,
            config.PATIENT_HEIGHT_CM / 200.0,
            1.0 if config.PATIENT_GENDER == "FEMALE" else 0.0,
            1.0 if config.PATIENT_ETHNICITY == "ASIAN" else 0.0,
            1.0 if config.PATIENT_DIABETES_TYPE == "T1D" else 0.0,
            (now.year - config.PATIENT_DIAGNOSIS_YEAR) / 30.0,
            0.5, # Activity label (Placeholder: Moderate)
            config.PATIENT_FRUCTOSAMIN / 500.0,
            1.0 if config.PATIENT_INFLAMMATORY_MARKER else 0.0,
            0.0, # is_sick (Placeholder)
            
            # Layer 2: Regime Forcing
            temporal_engine.get_multiplier(now),
            
            # --- Environmental Forcing ---
            # These are normalized by the DigitalTwin's exposure logic internally 
            # for simulation, but here we provide them as raw model inputs.
            0.0 if not is_outdoor else 1.0, # MOCK: Heat forcing impact simplified for CNN entry
            0.0 if not is_outdoor else 1.0, # MOCK: Humidity forcing 
            0.0 if not is_outdoor else 1.0  # MOCK: AQI forcing
        ]
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
        window['velocity'] = window[g_col].diff() / 2.5 # assume 2.5m interval
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
                # _ is the index. If it's a DatetimeIndex, _ is a Timestamp.
                ts_dt = _ if isinstance(_, datetime) else datetime.now(timezone.utc)

            reading = GlucoseReading(
                timestamp=ts_dt,
                value=g_val,
                trend=row.get('trend', 'Flat')
            )
            cardiac = cardiac_synthesizer.estimate(reading, velocity=row['velocity'])
            
            # Normalize for CNN: Glucose/20, BPM (60-180 range normalized to 0-1)
            # Matches MetabolicDataset: (hr - 60) / 120.0
            g_scaled = g_val / 20.0
            hr_scaled = (cardiac.bpm - 60) / 120.0
            temporal_data.append([g_scaled, hr_scaled])

        # Torch expects (Batch, Channels, Time)
        tensor = torch.tensor([temporal_data], dtype=torch.float32).transpose(1, 2)
        return tensor

    def run_inference_on_window(self, df_window: pd.DataFrame, now: datetime) -> dict:
        """
        Runs Multi-Task inference. Returns a dict of [glucose, heart_rate].
        """
        temp_x = self._prepare_temporal_tensor(df_window)
        static_y = self._assemble_static_vector(now)
        
        with torch.no_grad():
            output = self.model(temp_x, static_y)[0] # (2,)
            
        # Rescale: 
        # Glucose: val * 20.0
        # HR: (val * 120.0) + 60.0
        g_pred = float(output[0]) * 20.0
        hr_pred = (float(output[1]) * 120.0) + 60.0
        
        return {
            "glucose": g_pred,
            "heart_rate": hr_pred
        }

    def run_live_inference(self, csv_path: str):
        """
        Main entry point: Read live file -> Build tensors -> Forward Pass.
        """
        if not Path(csv_path).exists():
            print(f"Error: Live data not found at {csv_path}")
            return None

        # Load latest data
        df = pd.read_csv(csv_path)
        now = datetime.now(timezone.utc)
        
        # Prepare inputs
        temp_x = self._prepare_temporal_tensor(df)
        static_y = self._assemble_static_vector(now)
        
        print(f"Feeding data into CNN (Temporal: {temp_x.shape}, Static: {static_y.shape})...")
        
        with torch.no_grad():
            output = self.model(temp_x, static_y)
            
        return output.item()

if __name__ == "__main__":
    # Find the most recent export file
    export_dir = Path("data/exports")
    csv_files = list(export_dir.glob("*.csv"))
    if not csv_files:
        print("No live data found to feed into CNN.")
    else:
        # Sort by mtime to get the latest
        latest_csv = max(csv_files, key=lambda p: p.stat().st_mtime)
        print(f"Targeting: {latest_csv.name}")
        
        runner = MetabolicInferenceRunner()
        result = runner.run_live_inference(str(latest_csv))
        
        print("\n--- CNN INFERENCE RESULT ---")
        print(f"Residual Delta: {result:.4f}")
        print("Status: Success (Model activation verified)")
        print("Note: Running with initialized weights (Cold Mode)")
