import numpy as np
from datetime import datetime, timezone
from typing import Optional
from diabetic.config import config
from diabetic.utils.temporal import temporal_engine

class ScalingEngine:
    """
    Centralized scaling and normalization engine for the Metabolic Intelligence Suite.
    Ensures 1:1 parity between training data (MetabolicDataset) and live inference.
    """
    
    # ── Static Mapping Rules (Tier 1 Metadata) ────────────────────────────────
    GENDER_MAP = { 
        "FEMALE": 0.0, 
        "MALE": 1.0, 
        "OTHER": 0.5}#bruh

    ETHNICITY_MAP = {
        "ASIAN": 0.1, 
        "CAUCASIAN": 0.2, 
        "AFRICAN": 0.3, 
        "HISPANIC": 0.4,
        "UNKNOWN": 0.0  # Safe fallback to prevent collision
    }
    DIABETES_TYPE_MAP = {"T1D": 1.0, "T2D": 0.5, "PRE": 0.2}
    ACTIVITY_LEVEL_MAP = {
        "SEDENTARY": 0.3, 
        "MODERATE": 0.5, 
        "ACTIVE": 0.7, 
        "VERY ACTIVE": 1.0, 
        "ATHLETE": 1.2, 
        "UNKNOWN": 0.5
    }
# all of the above should be a range no?
    @classmethod
    def assemble_static_vector(cls, now: Optional[datetime] = None, env_data: Optional[dict] = None, is_sick: bool = False) -> np.ndarray:
        """
        Assembles the 15-feature static trait vector exactly as used in training.
        Supports dynamic environmental injection and clinical overrides (sick mode).
        """
        if now is None:
            now = datetime.now(timezone.utc)
            
        temp_scaled = 1.0
        humid_scaled = 1.0
        aqi_scaled = 1.0
        
        if env_data:
            # Safely scale environment metrics anchored to 1.0 as baseline
            # Temperature normal = 25C. Formula: (Temp / 25) so 25C -> 1.0
            temp_scaled = min(2.0, max(0.0, env_data.get('temperature', 25.0) / 25.0))
            # Humidity normal = 60%. Formula (Humid / 60) so 60% -> 1.0
            humid_scaled = min(2.0, max(0.0, env_data.get('humidity', 60.0) / 60.0))
            # AQI normal = 50. Formula (AQI / 50) so 50 AQI -> 1.0
            aqi_scaled = min(10.0, max(0.0, env_data.get('aqi', 50.0) / 50.0))

        vector = [
            config.PATIENT_AGE / 100.0,
            config.PATIENT_WEIGHT_KG / 150.0,
            config.PATIENT_HEIGHT_CM / 250.0,
            cls.GENDER_MAP.get(config.PATIENT_GENDER, 0.0),
            cls.ETHNICITY_MAP.get(config.PATIENT_ETHNICITY, 0.0),
            cls.DIABETES_TYPE_MAP.get(config.PATIENT_DIABETES_TYPE, 0.0),
            (now.year - config.PATIENT_DIAGNOSIS_YEAR) / 50.0,
            cls.ACTIVITY_LEVEL_MAP.get(config.PATIENT_ACTIVITY_LEVEL.upper(), 0.5),
            config.PATIENT_FRUCTOSAMIN / 500.0,
            1.0 if config.PATIENT_INFLAMMATORY_MARKER else 0.0,
            1.0 if is_sick else 0.0, # is_sick (Dynamic state flag)
            temporal_engine.get_multiplier(now),
            temp_scaled, humid_scaled, aqi_scaled
        ]
        return np.array(vector, dtype=np.float32)


    @staticmethod
    def scale_glucose(value: float) -> float:
        """Normalized to [0.0 - 1.0] range (baseline 20.0 mmol/L)."""
        return value / 20.0

    @staticmethod
    def scale_heart_rate(bpm: float) -> float:
        """Normalized to [0.0 - 1.0] range (baseline 60-180 BPM)."""
        return (bpm - 60.0) / 120.0

scaling_engine = ScalingEngine()
