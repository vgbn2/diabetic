from typing import List, Optional
from datetime import datetime, timedelta, timezone
from enum import Enum
from pydantic import BaseModel
from diabetic.registry import MetabolicSnapshot, GlucoseReading
from diabetic import medical_constants

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
        from diabetic.config import config
        self.config = config

    def evaluate(self, current: MetabolicSnapshot, prediction_30m: float) -> Optional[Alert]:
        """Runs the bimodal detection logic using centralized medical constants."""
        g = current.filtered_value
        v = current.velocity
        hr = current.bpm or self.config.PATIENT_BPM_BASELINE
        hrv = current.hrv or self.config.PATIENT_HRV_BASELINE
        
        # 1. CRITICAL HYPO (Current)
        if g < medical_constants.HYPO_CRITICAL:
            return Alert(
                timestamp=datetime.now(timezone.utc),
                type="CRITICAL_HYPO",
                severity=AlertSeverity.EMERGENCY,
                message=f"{self.config.UI_SETTINGS['EMERGENCY']}: Glucose is {g:.1f} mmol/L. Immediate action required!",
                glucose_value=g
            )
            
        # 2. WARNING HYPO (Predicted)
        if prediction_30m < medical_constants.HYPO_WARNING and v < 0:
            return Alert(
                timestamp=datetime.now(timezone.utc),
                type="WARNING_HYPO",
                severity=AlertSeverity.HIGH,
                message=f"{self.config.UI_SETTINGS['HIGH']}: Predicted to hit {prediction_30m:.1f} mmol/L in 30 mins. (Vel: {v:.1f})",
                glucose_value=g,
                prediction_30m=prediction_30m
            )
            
        # 3. CRITICAL HYPER (Current)
        if g > medical_constants.HYPER_CRITICAL:
            return Alert(
                timestamp=datetime.now(timezone.utc),
                type="CRITICAL_HYPER",
                severity=AlertSeverity.HIGH,
                message=f"{self.config.UI_SETTINGS['CRITICAL_HYPER']}: Glucose is {g:.1f} mmol/L. Check ketones.",
                glucose_value=g
            )
            
        # 4. FAINT RISK (Hyper + Rapid climb + Cardiac stress)
        # Integrate HRV and BPM for a more accurate faint risk
        if g > medical_constants.FAINT_GLUCOSE:
            # Base risk: fast rise (Wave 6: Normalized to per-minute)
            is_faint_risk = v > medical_constants.FAINT_VELOCITY_LIMIT_PER_MIN
            
            # Cardiac stress multipliers (BPM > 100 or HRV < 20ms)
            cardiac_stress = hr > 100 or hrv < 20
            
            # Dawn Phenomenon damping (4 AM - 8 AM)
            now_hour = datetime.now(timezone.utc).hour
            is_dawn = 4 <= now_hour <= 8
            
            if is_faint_risk and (not is_dawn or cardiac_stress):
                return Alert(
                    timestamp=datetime.now(timezone.utc),
                    type="FAINT_RISK",
                    severity=AlertSeverity.MEDIUM,
                    message=f"{self.config.UI_SETTINGS['FAINT_RISK']}: Rapid climb ({v:+1f} mmol/L/min) | Glucose: {g:.1f} | HR: {hr:.0f}bpm.",
                    glucose_value=g,
                    prediction_30m=prediction_30m
                )
            
        return None

class CircuitBreaker:
    """Prevents alert fatigue by throttling notifications."""
    def __init__(self, cooldown_mins: int = 15):
        self.cooldown = timedelta(minutes=cooldown_mins)
        self.last_alerts = {} # type -> timestamp

    def can_alert(self, alert_type: str, severity: AlertSeverity = AlertSeverity.MEDIUM) -> bool:
        """Determines if enough time has passed. EMERGENCY severity bypasses cooldown."""
        if severity == AlertSeverity.EMERGENCY:
            return True # Never throttle emergency alerts
            
        now = datetime.now(timezone.utc)
        if alert_type not in self.last_alerts:
            self.last_alerts[alert_type] = now
            return True
            
        if now - self.last_alerts[alert_type] > self.cooldown:
            self.last_alerts[alert_type] = now
            return True
            
        return False
