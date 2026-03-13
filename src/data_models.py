from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List

@dataclass(frozen=True)
class GlucoseRecord:
    """A standard model for glucose readings to decouple data source from logic."""
    timestamp: datetime
    sgv: float
    direction: str = "NONE"
    source: str = "Nightscout"
    trend_velocity: Optional[float] = None
    is_filtered: bool = False

    @property
    def sgv_mmol(self) -> float:
        """Convert mg/dL to mmol/L for research or international use."""
        return self.sgv / 18.018

@dataclass(frozen=True)
class TreatmentRecord:
    """Represents a metabolic event: insulin bolus or carbohydrate intake."""
    timestamp: datetime
    insulin: float = 0.0 # Units
    carbs: float = 0.0   # Grams
    event_type: str = "Unknown"

@dataclass(frozen=True)
class ProcessedState:
    """
    The final 'linkable' metabolic state for a single timestamp.
    Used by the ML engine and Alert system.
    """
    timestamp: datetime
    glucose: float
    iob: float
    cob: float
    velocity: float = 0.0
    acceleration: float = 0.0
    is_synthetic: bool = False # True if this was interpolated
