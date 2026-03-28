from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional

class GlucoseReading(BaseModel):
    """Represents a single glucose data point from CGM."""
    timestamp: datetime
    value: float  # Blood glucose level (standard unit: mmol/L)
    trend: str    # Trend arrow/indicator (e.g., Flat, FortyFiveUp, DoubleDown)
    source: str = "nightscout"
    unit: str = "mmol/L"

class InsulinDose(BaseModel):
    """Represents an insulin delivery event."""
    timestamp: datetime
    units: float
    type: str  # e.g., 'rapid-acting', 'long-acting'

class MealEvent(BaseModel):
    """Represents a carbohydrate ingestion event."""
    timestamp: datetime
    carbs: Optional[float] = None
    is_breakfast: bool = False
    is_lunch: bool = False
    is_dinner: bool = False
    gi_type: str = "STARCH"  # "LIQUID" or "STARCH"

class CardiacReading(BaseModel):
    """Represents heart rate and variability data."""
    timestamp: datetime
    bpm: int
    hrv: float  # Heart Rate Variability index

class MetabolicSnapshot(BaseModel):
    """A unified state representing a person's metabolic condition at a point in time."""
    glucose: GlucoseReading
    cardiac: Optional[CardiacReading] = None
    last_insulin: Optional[InsulinDose] = None
    last_meal: Optional[MealEvent] = None
    
    # Derived DSP values
    filtered_value: float = 0.0
    velocity: float = 0.0
    acceleration: float = 0.0
    atr_14: float = 0.0
    predict_30m: float = 0.0
    
    @property
    def bpm(self) -> Optional[int]:
        return self.cardiac.bpm if self.cardiac else None
        
    @property
    def hrv(self) -> Optional[float]:
        return self.cardiac.hrv if self.cardiac else None
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
