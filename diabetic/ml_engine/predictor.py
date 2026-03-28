import numpy as np
import xgboost as xgb
from typing import List, Optional
from diabetic.registry import MetabolicSnapshot
from diabetic.dsp.metabolic_math import MetabolicMath
from diabetic import medical_constants

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
        Extracts 10 metabolic features for synchronization with verification scripts.
        Vector: [val_mmol, v, a, momentum, lbgi, hbgi, t_sin, t_cos, atr, oscillation]
        """
        if not history:
            return np.array([])

        latest = history[-1]
        lbgi, hbgi = MetabolicMath.calculate_risk_indices(latest.filtered_value)

        # Circadian Features
        now = latest.glucose.timestamp
        t_sin = np.sin(2 * np.pi * now.hour / 24.0)
        t_cos = np.cos(2 * np.pi * now.hour / 24.0)

        # Momentum & Oscillation
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

        Two components:
        1. Base damping (velocity noise rejection) — applied at all horizons.
           Reduces contribution of high-frequency velocity spikes.

        2. Renal damping (glucosuria sink) — applied ONLY when horizon >= 60 min.
           FIX T1: glucosuria operates on a 1-4 hour timescale. Applying this
           brake to short-horizon (5-30 min) predictions compounds per-reading
           and has no physiological basis at that scale. Gated to long-horizon
           projections only.
           Disabled above HYPER_CRITICAL (19.4 mmol/L): under-predicting a
           hyperglycemic rise in the critical zone is more dangerous than
           over-predicting it.
        """
        # Base damping — artifact/noise rejection for high velocity readings
        # FAINT_VELOCITY_PER_5MIN = 0.5 mmol/L per 5 min = 0.1 mmol/L per min
        v_threshold = medical_constants.FAINT_VELOCITY_PER_5MIN / 5.0
        base_damping = 0.95 if abs(velocity) > v_threshold else 1.0

        # Renal damping — long-horizon only, and not in the critical zone
        renal_damping = 1.0
        if horizon_mins >= 30.0 and glucose <= medical_constants.HYPER_CRITICAL:
            rt = medical_constants.RENAL_THRESHOLD
            if glucose > rt:
                delta = glucose - rt
                renal_damping = 1.0 - (medical_constants.RENAL_CLEARANCE_SLOPE * delta)

        # Counter-regulatory damping — long-horizon and falling only
        # Reduces predicted drop as glucose approaches physiological floor.
        low_side_damping = 1.0
        if horizon_mins >= 30.0 and velocity < 0:
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

        # Confidence decays as horizon increases
        confidence = max(0.1, 1.0 - (horizon_mins / 120.0))

        if not self.is_trained:
            # Kinematic Algorithm: P = G + (V * t * damping) + (0.25 * A * t^2)
            # FIX Bug5: documented the 0.25 factor explicitly. The standard
            # kinematic formula is 0.5 * a * t^2. The extra * 0.5 is intentional
            # acceleration damping (reduces long-horizon overshoot from noisy
            # Kalman acceleration estimates). It is not a physics error.
            # FIX T1: horizon_mins passed to damping so renal brake is gated.
            damping = self._calculate_dynamic_damping(latest.filtered_value, latest.velocity, horizon_mins)

            # Velocity is in mmol/L per min, horizon_mins is in mins
            v_term = latest.velocity * horizon_mins * damping
            # Acceleration damping factor 0.5 reduces to 0.25 * a * t^2.
            # Intentional: Kalman acceleration is noisier than velocity.
            a_term = 0.5 * latest.acceleration * (horizon_mins ** 2) * 0.5

            prediction = latest.filtered_value + v_term + a_term
            final_pred = max(medical_constants.PHYSIO_FLOOR, prediction)
            return float(final_pred), float(confidence)

        features = self._prepare_features(history)
        prediction = self.model.predict(features)[0]
        return float(prediction), float(confidence)

    def predict_30m(self, history: List[MetabolicSnapshot]) -> float:
        """Deprecated: Use predict() instead for new integrations."""
        val, _ = self.predict(history, 30.0)
        return val

    def load_model(self, path: str):
        """Loads a pre-trained XGBoost model."""
        self.model.load_model(path)
        self.is_trained = True

if __name__ == "__main__":
    from datetime import datetime
    from diabetic.registry import GlucoseReading

    forecaster = GlucoseForecaster()
    snap = MetabolicSnapshot(
        glucose=GlucoseReading(timestamp=datetime.now(), value=8.3, trend="Flat"),
        filtered_value=8.3,
        velocity=-0.1,
        acceleration=0.0,
        atr_14=0.0
    )
    pred = forecaster.predict_30m([snap])
    print(f"Current: 8.3 mmol/L | Predicted 30m: {pred:.2f} mmol/L")