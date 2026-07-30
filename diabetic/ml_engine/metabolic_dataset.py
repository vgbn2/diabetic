import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset
from datetime import datetime, timezone
from typing import Tuple, List, Optional

from diabetic.ml_engine.synthetic_cardiac import cardiac_synthesizer
from diabetic.registry import GlucoseReading
from diabetic.config import config

class MetabolicDataset(Dataset):
    """
    Slices historical CSV data into CNN-ready windows.
    Performs feature scaling and cardiac synthesis for training.
    """
    
    def __init__(
        self, 
        csv_path: Optional[str] = None, 
        df_input: Optional[pd.DataFrame] = None,
        seq_len: int = 30, 
        prediction_offset: int = 6,
        *,
        allow_synthetic_cardiac: bool = True,
    ):
        self.csv_path = csv_path
        self.df_input = df_input
        self.seq_len = seq_len
        self.prediction_offset = prediction_offset # e.g. 6 ticks = 30 mins
        self.allow_synthetic_cardiac = allow_synthetic_cardiac
        
        self.data, self.static_vector = self._preprocess()
        self.X, self.y = self._create_windows()

    def _preprocess(self) -> Tuple[pd.DataFrame, np.ndarray]:
        if self.df_input is not None:
            df = self.df_input.copy()
        elif self.csv_path:
            df = pd.read_csv(self.csv_path)
        else:
            raise ValueError("MetabolicDataset requires either csv_path or df_input.")
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')

        # Fix H9: Detect DB-exported vs. legacy glucose column name (and handle duplicates)
        if 'glucose_mmol_l' in df.columns and 'glucose' in df.columns:
            # Consolidation scenario: prioritize high-fidelity naming
            df['glucose'] = df['glucose'].fillna(df['glucose_mmol_l'])
            df.drop(columns=['glucose_mmol_l'], inplace=True)
        elif 'glucose_mmol_l' in df.columns:
            df.rename(columns={'glucose_mmol_l': 'glucose'}, inplace=True)

        # Fix C3: Resample to dynamic sampling interval (not hardcoded 5min)
        # Fix C1: set_index FIRST, then resample. Using numeric_only=True on .mean()
        # prevents chaining select_dtypes before the index is set, which was silently
        # dropping non-numeric columns (velocity, timestamp) before resampling.
        interval_mins = int(config.SAMPLING_INTERVAL_MINS)
        resample_rule = f'{interval_mins}min'
        df = df.set_index('timestamp').resample(resample_rule).mean(numeric_only=True)

        # Post-resample audit: log a warning if expected base channels are missing.
        _expected = {'glucose'}
        _missing = _expected - set(df.columns)
        if _missing:
            import logging as _logging
            _logging.getLogger("Bio-Quant.MetabolicDataset").warning(
                "[C1-GUARD] Post-resample column audit FAILED. Missing channels: %s. "
                "Check CSV schema alignment.", _missing
            )

        # 2. Interpolate missing glucose
        df['glucose'] = df['glucose'].interpolate(method='linear')
        df = df.dropna(subset=['glucose'])  # Remove trailing/leading NaNs

        if "heart_rate" not in df:
            if not self.allow_synthetic_cardiac:
                raise ValueError(
                    "Deployable training requires a real heart_rate channel."
                )
            hrs = []
            for i in range(len(df)):
                g_val = df.iloc[i]["glucose"]
                vel = 0.0
                if i > 0:
                    vel = (
                        g_val - df.iloc[i - 1]["glucose"]
                    ) / config.SAMPLING_INTERVAL_MINS
                g_reading = GlucoseReading(
                    timestamp=df.index[i], value=g_val, trend="NONE"
                )
                cardiac = cardiac_synthesizer.estimate(g_reading, velocity=vel)
                hrs.append(cardiac.bpm)
            df["heart_rate"] = hrs
        else:
            df["heart_rate"] = df["heart_rate"].interpolate(method="linear")
            df = df.dropna(subset=["heart_rate"])

        # 4. Feature Scaling (CNN best practices)
        df['glucose_scaled'] = df['glucose'] / 20.0
        df['hr_scaled'] = (df['heart_rate'] - 60) / 120.0 # 60-180 range

        # 5. Extract Static Vector (15 features)
        static = self._assemble_static_vector(df.index[0])
        
        return df, static

    def _assemble_static_vector(self, now: datetime) -> np.ndarray:
        """Assembles the 15-feature static trait vector from ScalingEngine (Fix C2)."""
        from diabetic.utils.scaling_engine import scaling_engine
        return scaling_engine.assemble_static_vector(now)

    def _create_windows(self) -> Tuple[np.ndarray, np.ndarray]:
        X_list = []
        y_list = []
        
        data_vals = self.data[['glucose_scaled', 'hr_scaled']].values
        glucose_vals = self.data['glucose_scaled'].values
        hr_vals = self.data['hr_scaled'].values

        for i in range(len(data_vals) - self.seq_len - self.prediction_offset):
            # Input sequence (Temporal Channels x SeqLen)
            window = data_vals[i : i + self.seq_len].T 
            X_list.append(window)
            
            # Multi-Target: [Glucose_Scaled, HR_Scaled] at target_t
            target_t = i + self.seq_len + self.prediction_offset - 1
            y_sample = [
                glucose_vals[target_t],
                hr_vals[target_t]
            ]
            y_list.append(y_sample)

        return np.array(X_list, dtype=np.float32), np.array(y_list, dtype=np.float32)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return (
            torch.from_numpy(self.X[idx]), 
            torch.from_numpy(self.static_vector), 
            torch.from_numpy(self.y[idx]) # Already 2-element array
        )
