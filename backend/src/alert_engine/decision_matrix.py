from typing import List, Optional
from datetime import datetime, timedelta
from enum import Enum
from pydantic import BaseModel
from backend.src.registry import MetabolicSnapshot, GlucoseReading

class AlertSeverity(Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EMERGENCY = "EMERGENCY"

class Alert(BaseModel):
    timestamp: datetime
    type: str
    severity: AlertSeverity
    message: str
    glucose_value: float
    prediction_30m: Optional[float] = None

class DecisionMatrix:
    """
    The 'Safety Shield'. Evaluates metabolic state against medical thresholds.
    """
    def __init__(self):
        from backend.src.config import config
        self.config = config

    def evaluate(self, current: MetabolicSnapshot, prediction_30m: float) -> Optional[Alert]:
        """Runs the bimodal detection logic. Internal thresholds converted to mmol/L."""
        g = current.filtered_value
        v = current.velocity
        
        # 1. CRITICAL HYPO (Current) - 55 mg/dL -> ~3.1 mmol/L
        if g < 3.1:
            return Alert(
                timestamp=datetime.now(),
                type="CRITICAL_HYPO",
                severity=AlertSeverity.EMERGENCY,
                message=f"🚨 EMERGENCY: Glucose is {g:.1f} mmol/L. Immediate action required!",
                glucose_value=g
            )
            
        # 2. WARNING HYPO (Predicted) - 70 mg/dL -> ~3.9 mmol/L
        if prediction_30m < 3.9 and v < 0:
            return Alert(
                timestamp=datetime.now(),
                type="WARNING_HYPO",
                severity=AlertSeverity.HIGH,
                message=f"⚠️ WARNING: Predicted to hit {prediction_30m:.1f} mmol/L in 30 mins. (Vel: {v:.1f})",
                glucose_value=g,
                prediction_30m=prediction_30m
            )
            
        # 3. CRITICAL HYPER (Current) - 350 mg/dL -> ~19.4 mmol/L
        if g > 19.4:
            return Alert(
                timestamp=datetime.now(),
                type="CRITICAL_HYPER",
                severity=AlertSeverity.HIGH,
                message=f"🔺 CRITICAL HYPER: Glucose is {g:.1f} mmol/L. Check ketones.",
                glucose_value=g
            )
            
        # 4. FAINT RISK (Hyper + Rapid climb) - Climb > 0.5 mmol/L/min
        if g > 16.7 and v > 0.5: # 16.7 mmol/L = ~300 mg/dL
            return Alert(
                timestamp=datetime.now(),
                type="FAINT_RISK",
                severity=AlertSeverity.MEDIUM,
                message=f"💫 FAINT RISK: Rapid climb ({v:+.1f}) while in Hyper range ({g:.1f}).",
                glucose_value=g,
                prediction_30m=prediction_30m
            )
            
        return None

class CircuitBreaker:
    """Prevents alert fatigue by throttling notifications."""
    def __init__(self, cooldown_mins: int = 15):
        self.cooldown = timedelta(minutes=cooldown_mins)
        self.last_alerts = {} # type -> timestamp

    def can_alert(self, alert_type: str) -> bool:
        """Determines if enough time has passed since last alert of this type."""
        now = datetime.now()
        if alert_type not in self.last_alerts:
            # First time seeing this alert, record and allow
            self.last_alerts[alert_type] = now
            return True
            
        if now - self.last_alerts[alert_type] > self.cooldown:
            # Cooldown passed, record new time and allow
            self.last_alerts[alert_type] = now
            return True
            
        # Still in cooldown, DO NOT update timestamp (stay blocked)
        return False
