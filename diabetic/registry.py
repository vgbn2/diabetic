from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List

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
    is_snack: bool = False
    gi_type: str = "STARCH"  # "LIQUID", "STARCH", or "SNACK"

class HydrationEvent(BaseModel):
    """Represents a fluid intake event (Layer 3 - The Behavioral Engine)."""
    timestamp: datetime
    milliliters: float
    type: str = "WATER"  # "WATER", "ELECTROLYTE", "CAFFEINE"

class EnvironmentReading(BaseModel):
    """External environment data (Layer 2 - The Adaptive Regimes)."""
    timestamp: datetime
    temperature: float
    humidity: float
    aqi: Optional[float] = None

class CardiacReading(BaseModel):
    """Represents heart rate and variability data."""
    timestamp: datetime
    bpm: int
    hrv: float  # Heart Rate Variability index
    mean_bpm: Optional[int] = None
    max_bpm: Optional[int] = None
    signal_quality: float = 1.0

class UserFeedback(BaseModel):
    """Subjective truth collected via UI (Layer 5 - The Interaction Layer)."""
    timestamp: datetime
    symptoms: List[str] = []  # e.g., ["fog", "dizziness", "shaky"]
    is_false_alarm: bool = False
    confidence_override: Optional[float] = None  # User's felt confidence in current alert

class ProbabilisticForecast(BaseModel):
    """Represents a range of possible futures (Layer 4 - Meta-Correction)."""
    timestamp: datetime
    mean: float
    p5: float
    p95: float
    std_dev: float

class MetabolicSnapshot(BaseModel):
    """A unified state representing a person's metabolic condition at a point in time (5-Layer Synthesis)."""
    glucose: GlucoseReading
    cardiac: Optional[CardiacReading] = None
    last_insulin: Optional[InsulinDose] = None
    last_meal: Optional[MealEvent] = None
    last_hydration: Optional[HydrationEvent] = None
    environment: Optional[EnvironmentReading] = None
    feedback: Optional[UserFeedback] = None
    
    # Layer 2 (Regimes)
    cycle_day: Optional[int] = None
    is_sick: bool = False
    
    # Layer 4 (The Meta-Correction Layer)
    filtered_value: float = 0.0
    velocity: float = 0.0
    acceleration: float = 0.0
    atr_14: float = 0.0
    predict_30m: float = 0.0
    forecast: Optional[ProbabilisticForecast] = None # P5/P95 Range
    residual_error: float = 0.0  # Error from previous forecast
    sensor_health: float = 1.0   # Diagnostic integrity (0.0 - 1.0)
    
    # Layer 3 (The Behavioral Engine)
    active_carbs: float = 0.0     # Carbs on Board (COB)
    active_insulin: float = 0.0   # Insulin on Board (IOB)
    activity_label: str = "UNKNOWN"  # Populated by dsp.context_classifier
    
    @property
    def bpm(self) -> Optional[int]:
        return self.cardiac.bpm if self.cardiac else None
        
    @property
    def mean_bpm(self) -> Optional[int]:
        return self.cardiac.mean_bpm if self.cardiac else None
        
    @property
    def max_bpm(self) -> Optional[int]:
        return self.cardiac.max_bpm if self.cardiac else None
        
    @property
    def hrv(self) -> Optional[float]:
        return self.cardiac.hrv if self.cardiac else None
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

