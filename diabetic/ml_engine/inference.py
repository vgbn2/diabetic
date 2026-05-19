import logging
import torch
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Union
from pathlib import Path

from diabetic.config import config
from diabetic.registry import MetabolicSnapshot, GlucoseReading
from diabetic.ml_engine.convolutional_layer import DiabeticCNN, CNNConfig
from diabetic.ml_engine.synthetic_cardiac import cardiac_synthesizer
from diabetic.utils.schedule import schedule_manager
from diabetic.utils.scaling_engine import scaling_engine
import diabetic.medical_constants as mc

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
        self.device = torch.device('cpu') # Default to CPU
        self._resample_to_5min = False
        
        # Load Personalized Weights (Phase 14+)
        weight_path = Path(config.ML_WEIGHTS_PATH)
        if weight_path.exists():
            try:
                self.model.load_state_dict(torch.load(weight_path, map_location=self.device, weights_only=True))
                logger.info(f"Personalized CNN Multi-Task {config.ML_WEIGHTS_VERSION} Weights Loaded: {weight_path}")
            except Exception as e:
                logger.warning(f"Warning: Failed to load multi-task weights: {e}. Running in Cold Mode.")
        else:
            logger.warning(f"Warning: No weights found at {weight_path}. Running in Cold Mode.")

        self._refresh_sampling_mode()
        self.model.eval() # Inference mode

    def _refresh_sampling_mode(self):
        """Align inference resampling with the configured training cadence."""
        if config.SAMPLING_INTERVAL_MINS != 5:
            logger.warning(
                f"CNN trained on 5-min grids. Config uses {config.SAMPLING_INTERVAL_MINS}min. "
                "Resampling to 5-min before inference."
            )
            self._resample_to_5min = True
        else:
            self._resample_to_5min = False

    def reload_weights(self, path: Path):
        """Phase 3: Hot-reloading weights after autonomous retraining."""
        try:
            self.model.load_state_dict(
                torch.load(path, map_location=self.device, weights_only=True)
            )
            self.model.eval()
            logger.info(f"[HotReload] Weights reloaded from {path}")
        except Exception as e:
            logger.error(f"[HotReload] Failed to reload weights: {e}. Keeping current weights.")

        self._refresh_sampling_mode()

    def _infer_exposure(self, now: datetime) -> bool:
        """Heuristic to guess Indoor/Outdoor state."""
        event = schedule_manager.get_event_at(now)
        if event:
            return event.is_outdoor
            
        hour = now.hour
        if hour in [8, 12] or (17 <= hour < 19):
            return True # Assume Outdoor
        return False # Assume Indoor

    def _assemble_static_vector(self, now: datetime, env_data: Optional[dict] = None, is_sick: bool = False) -> torch.Tensor:
        """Maps the 15 bio-basal and environmental traits."""
        is_outdoor = self._infer_exposure(now)
        vector = scaling_engine.assemble_static_vector(now, env_data=env_data, is_sick=is_sick).tolist()
        
        if not is_outdoor and env_data is None:
            vector[12] = 0.0 # Heat
            vector[13] = 0.0 # Humidity
            vector[14] = 0.0 # AQI
            
        return torch.tensor([vector], dtype=torch.float32)

    def _prepare_temporal_tensor(self, snapshots: List[MetabolicSnapshot]) -> Optional[torch.Tensor]:
        """
        Extracts and normalizes features from snapshots into a (1, Channels, seq_len) tensor.
        """
        if not snapshots:
            return None

        if len(snapshots) < self.seq_len and not self._resample_to_5min:
            logger.debug(f"Unsaturated: {len(snapshots)}/{self.seq_len}. Skipping CNN.")
            return None

        # 1. Feature Extraction & Normalization
        if self._resample_to_5min:
            # P1-2: Graceful resampling to 5-min grid
            timestamps = [s.glucose.timestamp.timestamp() for s in snapshots]
            
            # Extract raw values for interpolation
            raw_vals = []
            for s in snapshots:
                hr = s.bpm if s.bpm else (s.predicted_hr if s.predicted_hr else 75.0)
                raw_vals.append([
                    s.glucose.value,
                    hr
                ])
            
            latest_ts = timestamps[-1]
            # Create a 5-min grid backwards from latest timestamp
            target_ts = [latest_ts - (i * 300) for i in range(self.seq_len)]
            target_ts.reverse()
            
            # Interpolate and Scale
            data = []
            for t in target_ts:
                # Linear interpolation for each feature
                interp_row = []
                for feat_idx in range(2):
                    feat_series = [v[feat_idx] for v in raw_vals]
                    val = np.interp(t, timestamps, feat_series)
                    
                    # Scale based on feature index
                    if feat_idx == 0: # Glucose
                        interp_row.append(scaling_engine.scale_glucose(val))
                    elif feat_idx == 1: # HR
                        interp_row.append(scaling_engine.scale_heart_rate(val))
                data.append(interp_row)
        else:
            window = snapshots[-self.seq_len:]
            data = []
            for s in window:
                hr = s.bpm if s.bpm else (s.predicted_hr if s.predicted_hr else 75.0)
                data.append([
                    scaling_engine.scale_glucose(s.glucose.value),
                    scaling_engine.scale_heart_rate(hr)
                ])

        # Torch expects (Batch, Channels, Time) -> (1, 2, 30)
        tensor = torch.tensor([data], dtype=torch.float32).transpose(1, 2)
        return tensor

    def run_inference_on_snapshots(self, snapshots: List[MetabolicSnapshot]) -> Optional[dict]:
        """
        Bridges the live Coordinator memory to the Multi-Task Neural Engine.
        """
        tensor = self._prepare_temporal_tensor(snapshots)
        if tensor is None:
            return None

        latest = snapshots[-1]
        env_data = latest.environment.model_dump() if latest.environment else None
        is_sick = latest.is_sick
            
        static_y = self._assemble_static_vector(datetime.now(timezone.utc), env_data=env_data, is_sick=is_sick)
        
        with torch.inference_mode():
            output = self.model(tensor, static_y)[0]
            
        # Rescale: Glucose (0-1 -> 0-20), HR (0-1 -> 60-180)
        raw_g_pred = float(output[0]) * 20.0
        
        # --- PHASE 4.1: Dynamic Inference Bounding ---
        latest_val = latest.glucose.value
        min_plausible = max(mc.PHYSIO_FLOOR, latest_val - mc.MAX_PHYSIO_DROP_30M)
        max_plausible = min(mc.FAINT_GLUCOSE + 5.0, latest_val + mc.MAX_PHYSIO_RISE_30M)
        
        g_pred = max(min_plausible, min(raw_g_pred, max_plausible))
        
        if g_pred != raw_g_pred:
             logger.debug(f"CNN Prediction clamped from {raw_g_pred:.1f} to {g_pred:.1f} (Bounds: {min_plausible:.1f} - {max_plausible:.1f})")
        # ---------------------------------------------
        
        hr_pred = (float(output[1]) * 120.0) + 60.0
        hr_pred = max(40.0, min(hr_pred, 200.0))
        
        return {
            "glucose": g_pred,
            "heart_rate": hr_pred
        }

    def run_inference(self, snapshots: List[MetabolicSnapshot]) -> Optional[dict]:
        """Exposed method for running inference (sync wrapper)."""
        return self.run_inference_on_snapshots(snapshots)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    runner = MetabolicInferenceRunner()
    logger.info("Inference Runner stand-alone test complete.")
