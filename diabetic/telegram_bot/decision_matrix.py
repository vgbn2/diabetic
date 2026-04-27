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
    prediction_15m: Optional[float] = None
    prediction_60m: Optional[float] = None
    confidence_index: Optional[float] = None
    velocity_score: Optional[float] = None

class FeedbackEngine:
    """Consumes RLHF audit logs to adapt alert sensitivity dynamically."""
    
    @staticmethod
    async def get_dampener(audit_logger, alert_type: str) -> float:
        """
        Returns a target threshold multiplier. 
        > 1.0 = dampened (requires higher trigger).
        <= 1.0 = heightened/maintained.
        """
        if not audit_logger:
            return 1.0
            
        feedback = await audit_logger.get_recent_feedback(alert_type, hours=24)
        if not feedback:
            return 1.0
            
        false_alarms = sum(1 for f in feedback if f.get("is_false_alarm"))
        confirms = sum(1 for f in feedback if not f.get("is_false_alarm"))
        
        net_false = false_alarms - confirms
        if net_false >= 3:
            return 1.4  # Dampen by 40% (needs much higher velocity to trigger)
        elif net_false == 2:
            return 1.2
        elif net_false <= -2:
            return 0.9  # Heighten sensitivity
        return 1.0

class DecisionMatrix:
    """
    The 'Safety Shield'. Evaluates metabolic state against medical thresholds.
    """
    def __init__(self):
        from diabetic.config import config
        self.config = config

    async def evaluate(self, current: MetabolicSnapshot, prediction_30m: float, audit_logger=None) -> Optional[Alert]:
        """Runs the bimodal detection logic using centralized medical constants."""
        g = current.filtered_value
        v = current.velocity
        
        # 🔗 [CARDIAC CONSENSUS]
        # Real-time BPM + Neural Prediction = Total Contextual Awareness
        hr = current.bpm if current.bpm else current.predicted_hr
        if not hr:
            hr = self.config.PATIENT_BPM_BASELINE
            
        hrv = current.hrv or self.config.PATIENT_HRV_BASELINE
        is_active = hr > 115 # Exercise Context Buffer

        # 1. CRITICAL HYPO (Current) - Never suppressed
        if g < medical_constants.HYPO_CRITICAL:
            return Alert(
                timestamp=datetime.now(timezone.utc),
                type="CRITICAL_HYPO",
                severity=AlertSeverity.EMERGENCY,
                message=f"{self.config.UI_SETTINGS['EMERGENCY']}: Glucose is {g:.1f} mmol/L. Immediate action required!",
                glucose_value=g
            )

        # 2. WARNING HYPO (Predicted) - Suppressed if active (exercise drop)
        if prediction_30m < medical_constants.HYPO_WARNING and v < 0:
            if is_active and g > 4.5:
                return None # Exercise-induced drop; suppressed to avoid false alarm
                
            return Alert(
                timestamp=datetime.now(timezone.utc),
                type="WARNING_HYPO",
                severity=AlertSeverity.HIGH,
                message=f"{self.config.UI_SETTINGS['HIGH']}: Predicted to hit {prediction_30m:.1f} mmol/L. | Context: {'ACTIVE' if is_active else 'REST'} | Confidence: {current.confidence_index*100:.0f}%",
                glucose_value=g,
                prediction_30m=prediction_30m,
                prediction_15m=current.predict_15m,
                prediction_60m=current.predict_60m,
                confidence_index=current.confidence_index,
                velocity_score=current.velocity_score
            )

        # 2b. STRESS ANOMALY (Decoupling)
        if current.activity_label == "STRESS_ANOMALY":
             # [C3] Apply RLHF Feedback Dampening
             dampener = await FeedbackEngine.get_dampener(audit_logger, "STRESS_ANOMALY")
             
             # If dampener > 1.0, we require a stronger velocity to trigger this alert
             # Assuming baseline velocity required for Stress Anomaly was implicit in the label,
             # we add a hard explicit guard here that scales with RLHF.
             baseline_velocity_threshold = 0.5
             required_vel = baseline_velocity_threshold * dampener
             
             if abs(v) >= required_vel:
                 return Alert(
                        timestamp=datetime.now(timezone.utc),
                        type="STRESS_ANOMALY",  # Fix H4: distinct type prevents CircuitBreaker collision with FAINT_RISK
                        severity=AlertSeverity.HIGH,
                        message=f"{self.config.UI_SETTINGS['STRESS_ANOMALY']}: Biological Decoupling! Rapid velocity ({v:+1f}) while HR is baseline ({hr:.0f}). Potential faint risk.",
                        glucose_value=g,
                        prediction_30m=prediction_30m,
                        prediction_15m=current.predict_15m,
                        prediction_60m=current.predict_60m,
                        confidence_index=current.confidence_index,
                        velocity_score=current.velocity_score
                    )

        # 3. FAINT RISK (Hyper + Rapid climb + Cardiac stress)
        if g > medical_constants.FAINT_GLUCOSE:
            is_faint_risk = v > medical_constants.FAINT_VELOCITY_LIMIT_PER_MIN
            cardiac_stress = hr > 100 or hrv < 20
            now_hour = datetime.now(timezone.utc).hour
            is_dawn = 4 <= now_hour <= 8

            if is_faint_risk and (not is_dawn or cardiac_stress):
                return Alert(
                    timestamp=datetime.now(timezone.utc),
                    type="FAINT_RISK",
                    severity=AlertSeverity.HIGH,
                    message=f"{self.config.UI_SETTINGS['FAINT_RISK']}: Rapid climb ({v:+1f} mmol/L/min) | Glucose: {g:.1f} | HR: {hr:.0f}bpm.",
                    glucose_value=g,
                    prediction_30m=prediction_30m,
                    prediction_15m=current.predict_15m,
                    prediction_60m=current.predict_60m,
                    confidence_index=current.confidence_index,
                    velocity_score=current.velocity_score
                )

        # 4. CRITICAL HYPER (Current)
        if g > medical_constants.HYPER_CRITICAL:
            return Alert(
                timestamp=datetime.now(timezone.utc),
                type="CRITICAL_HYPER",
                severity=AlertSeverity.HIGH,
                message=f"{self.config.UI_SETTINGS['CRITICAL_HYPER']}: Glucose is {g:.1f} mmol/L. Check ketones.",
                glucose_value=g
            )

        return None

class CircuitBreaker:
    """Prevents alert fatigue by throttling notifications."""
    def __init__(self, cooldown_mins: int = 15):
        self.cooldown = timedelta(minutes=cooldown_mins)
        self.last_alerts = {}  # type -> timestamp

    def can_alert(self, alert_type: str, severity: AlertSeverity = AlertSeverity.MEDIUM) -> bool:
        """Determines if enough time has passed. EMERGENCY severity bypasses cooldown."""
        if severity == AlertSeverity.EMERGENCY:
            self.last_alerts[alert_type] = datetime.now(timezone.utc)
            return True

        now = datetime.now(timezone.utc)
        if alert_type not in self.last_alerts:
            self.last_alerts[alert_type] = now
            return True

        if now - self.last_alerts[alert_type] > self.cooldown:
            self.last_alerts[alert_type] = now
            return True

        return False