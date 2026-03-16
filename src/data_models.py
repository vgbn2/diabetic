from pydantic import BaseModel, Field, validator
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

class BaseMetabolicEvent(BaseModel):
    """Base schema for all synchronized metabolic data."""
    timestamp: datetime
    source: str = "Unknown"
    
    @property
    def iso_timestamp(self) -> str:
        return self.timestamp.isoformat()

class GlucoseReading(BaseMetabolicEvent):
    """Raw CGM sensor reading with interstitial lag metadata."""
    sgv: float = Field(..., gt=0, lt=1000)
    direction: str = "NONE"
    noise_level: int = 1 # 1=Clean, 2=Light, 3=Heavy
    lag_minutes: int = 15 # Default interstitial fluid delay

class BiometricReading(BaseMetabolicEvent):
    """Instantaneous biometric data (HRV, HR) from Radar or Wearable."""
    hr: Optional[float] = Field(None, gt=30, lt=220)
    rmssd: Optional[float] = Field(None, gt=0, lt=300)
    is_realtime: bool = True # Biometrics have 0ms lag compared to CGM

class TreatmentEvent(BaseMetabolicEvent):
    """Insulin bolus or carbohydrate intake."""
    insulin: float = 0.0
    carbs: float = 0.0
    event_type: str = "Meal"

class InferenceState(BaseModel):
    """
    The final, dynamic state tensor for ML and Filtering.
    This schema is 'elastic': it can expand if new sensors are added.
    """
    timestamp: datetime
    features: Dict[str, float] = Field(default_factory=dict)
    
    # Core state (Always present)
    glucose: float
    velocity: float = 0.0
    acceleration: float = 0.0
    
    # Optional dynamic features (Decoupled from UKF indices)
    iob: float = 0.0
    cob: float = 0.0
    dsi: float = 1.0
    hr: Optional[float] = None
    
    class Config:
        arbitrary_types_allowed = True

    def to_array(self, feature_list: List[str]) -> List[float]:
        """Dynamically generates a vector for the UKF based on requested features."""
        vector = [getattr(self, 'glucose', 100.0), getattr(self, 'velocity', 0.0), getattr(self, 'acceleration', 0.0)]
        for feat in feature_list:
            if feat not in ['glucose', 'velocity', 'acceleration']:
                vector.append(getattr(self, feat, 0.0))
        return vector
