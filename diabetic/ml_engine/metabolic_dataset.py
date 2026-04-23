import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset
from datetime import datetime, timezone
from typing import Tuple, List

from diabetic.ml_engine.synthetic_cardiac import cardiac_synthesizer
from diabetic.registry import GlucoseReading
from diabetic.config import config
from diabetic.utils.temporal import temporal_engine

class MetabolicDataset(Dataset):
    """
    Slices historical CSV data into CNN-ready windows.
    Performs feature scaling and cardiac synthesis for training.
    """
    
    def __init__(self, csv_path: str, seq_len: int = 30, prediction_offset: int = 6):
        self.csv_path = csv_path
        self.seq_len = seq_len
        self.prediction_offset = prediction_offset # e.g. 6 ticks = 30 mins
        
        self.data, self.static_vector = self._preprocess()
        self.X, self.y = self._create_windows()

    def _preprocess(self) -> Tuple[pd.DataFrame, np.ndarray]:
        df = pd.read_csv(self.csv_path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')

        # Fix H9: Detect DB-exported vs. legacy glucose column name
        g_col = 'glucose_mmol_l' if 'glucose_mmol_l' in df.columns else 'glucose'
        if g_col == 'glucose_mmol_l':
            df.rename(columns={'glucose_mmol_l': 'glucose'}, inplace=True)

        # Fix C3: Resample to dynamic sampling interval (not hardcoded 5min)
        interval_mins = int(config.SAMPLING_INTERVAL_MINS)
        resample_rule = f'{interval_mins}min'
        df = df.set_index('timestamp').select_dtypes(include=[np.number]).resample(resample_rule).mean()

        # 2. Interpolate missing glucose
        df['glucose'] = df['glucose'].interpolate(method='linear')
        df = df.dropna(subset=['glucose'])  # Remove trailing/leading NaNs

        # 3. Generate Synthetic Cardiac Channel
        hrs = []
        for i in range(len(df)):
            g_val = df.iloc[i]['glucose']
            # Calculate velocity if possible
            vel = 0.0
            if i > 0:
                # Fix C3: Divide by actual sampling interval, not hardcoded 5.0
                vel = (g_val - df.iloc[i-1]['glucose']) / config.SAMPLING_INTERVAL_MINS
            
            g_reading = GlucoseReading(timestamp=df.index[i], value=g_val, trend="NONE")
            cardiac = cardiac_synthesizer.estimate(g_reading, velocity=vel)
            hrs.append(cardiac.bpm)
        
        df['heart_rate'] = hrs

        # 4. Feature Scaling (CNN best practices)
        df['glucose_scaled'] = df['glucose'] / 20.0
        df['hr_scaled'] = (df['heart_rate'] - 60) / 120.0 # 60-180 range

        # 5. Extract Static Vector (15 features)
        static = self._assemble_static_vector(df.index[0])
        
        return df, static

    def _assemble_static_vector(self, now: datetime) -> np.ndarray:
        """Assembles the 15-feature static trait vector from config."""
        # Simple mapping (0.0 - 1.0)
        gender_map = {"FEMALE": 0.0, "MALE": 1.0, "OTHER": 0.5}
        eth_map = {"ASIAN": 0.1, "CAUCASIAN": 0.2, "AFRICAN": 0.3, "HISPANIC": 0.4}
        type_map = {"T1D": 1.0, "T2D": 0.5, "PRE": 0.2}

        vector = [
            config.PATIENT_AGE / 100.0,
            config.PATIENT_WEIGHT_KG / 150.0,
            config.PATIENT_HEIGHT_CM / 250.0,
            gender_map.get(config.PATIENT_GENDER, 0.0),
            eth_map.get(config.PATIENT_ETHNICITY, 0.0),
            type_map.get(config.PATIENT_DIABETES_TYPE, 0.0),
            (datetime.now().year - config.PATIENT_DIAGNOSIS_YEAR) / 50.0,
            0.5, # Default activity level
            config.PATIENT_FRUCTOSAMIN / 500.0,
            1.0 if config.PATIENT_INFLAMMATORY_MARKER else 0.0,
            0.0, # is_sick
            temporal_engine.get_multiplier(now),
            1.0, 1.0, 1.0 # Environment defaults for training
        ]
        return np.array(vector, dtype=np.float32)

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
