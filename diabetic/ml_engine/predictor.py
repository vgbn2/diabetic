import numpy as np
import xgboost as xgb
from typing import List, Optional
from src.shared.core.registry import MetabolicSnapshot
from src.shared.dsp.metabolic_math import MetabolicMath
from src.shared.core import medical_constants

class GlucoseForecaster:
    """
    XGBoost-based engine for predicting glucose levels 30 minutes into the future.
    Features: Filtered Glucose, Velocity, Acceleration, LBGI, HBGI.
    """
    def __init__(self, model_path: Optional[str] = None):
        self.model = xgb.XGBRegressor(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            objective='reg:squarederror'
        )
        self.is_trained = False

        if model_path:
            self.load_model(model_path)

    def _prepare_features(self, history: List[MetabolicSnapshot]) -> np.ndarray:
        """
        Extracts 10 metabolic features.
        Vector: [val_mmol, v, a, momentum, lbgi, hbgi, t_sin, t_cos, atr, oscillation]
        """
        if not history:
            return np.array([])

        latest = history[-1]
        lbgi, hbgi = MetabolicMath.calculate_risk_indices(latest.filtered_value)

        now = latest.glucose.timestamp
        t_sin = np.sin(2 * np.pi * now.hour / 24.0)
        t_cos = np.cos(2 * np.pi * now.hour / 24.0)

        momentum = latest.velocity * latest.filtered_value
        oscillation = 0.0
        if len(history) >= 5:
            mean_vals = np.mean([h.filtered_value for h in history[-5:]])
            oscillation = abs(latest.filtered_value - mean_vals)

        features = np.array([[
            latest.filtered_value,
            latest.velocity,
            latest.acceleration,
            momentum,
            lbgi,
            hbgi,
            t_sin,
            t_cos,
            latest.atr_14,
            oscillation
        ]])

        return features

    def _calculate_dynamic_damping(self, glucose: float, velocity: float, horizon_mins: float) -> float:
        """
        Calculates physiological braking for kinematic projection.
        """
        v_threshold = medical_constants.FAINT_VELOCITY_LIMIT_PER_MIN
        base_damping = 0.95 if abs(velocity) > v_threshold else 1.0

        # FIX: renal brake gated at >= 60 min (was 30 min).
        # Glucosuria operates on a 1-4 hour timescale — applying it at 30 min
        # has no physiological basis and causes systematic under-prediction.
        renal_damping = 1.0
        if horizon_mins >= 60.0 and glucose <= medical_constants.HYPER_CRITICAL:
            rt = medical_constants.RENAL_THRESHOLD
            if glucose > rt:
                delta = glucose - rt
                renal_damping = 1.0 - (medical_constants.RENAL_CLEARANCE_SLOPE * delta)

        # Counter-regulatory damping — also gated at >= 60 min for the same reason
        low_side_damping = 1.0
        if horizon_mins >= 60.0 and velocity < 0:
            lt = medical_constants.LOW_SIDE_THRESHOLD
            if glucose < lt:
                delta = lt - glucose
                low_side_damping = 1.0 - (medical_constants.LOW_SIDE_BRAKE_SLOPE * delta)

        combined = base_damping * renal_damping * low_side_damping
        return max(medical_constants.METABOLIC_BRAKE_FLOOR, combined)

    def predict(self, history: List[MetabolicSnapshot], horizon_mins: float = 30.0) -> tuple[float, float]:
        """
        Predicts glucose value N minutes from now.
        Returns: (prediction_value, confidence_score)
        """
        if not history:
            return 0.0, 0.0

        latest = history[-1]
        confidence = max(0.1, 1.0 - (horizon_mins / 120.0))

        if not self.is_trained:
            damping = self._calculate_dynamic_damping(latest.filtered_value, latest.velocity, horizon_mins)
            v_term = latest.velocity * horizon_mins * damping
            # 0.25 = 0.5 * 0.5: standard kinematic term × intentional acceleration damping.
            # Kalman acceleration is noisier than velocity; extra damping reduces long-horizon overshoot.
            a_term = 0.5 * latest.acceleration * (horizon_mins ** 2) * 0.5
            prediction = latest.filtered_value + v_term + a_term
            final_pred = max(medical_constants.PHYSIO_FLOOR, prediction)
            return float(final_pred), float(confidence)

        features = self._prepare_features(history)
        prediction = self.model.predict(features)[0]
        return float(prediction), float(confidence)

    def load_model(self, path: str):
        """Loads a pre-trained XGBoost model."""
        self.model.load_model(path)
        self.is_trained = True

if __name__ == "__main__":
    from datetime import datetime, timezone
    from src.shared.core.registry import GlucoseReading

    forecaster = GlucoseForecaster()
    snap = MetabolicSnapshot(
        glucose=GlucoseReading(timestamp=datetime.now(timezone.utc), value=8.3, trend="Flat"),
        filtered_value=8.3,
        velocity=-0.1,
        acceleration=0.0,
        atr_14=0.0
    )
    pred, _ = forecaster.predict([snap], 30.0)
    print(f"Current: 8.3 mmol/L | Predicted 30m: {pred:.2f} mmol/L")
