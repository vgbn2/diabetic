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
            
        # Feature vector (1x10)
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

    def predict(self, history: List[MetabolicSnapshot], horizon_mins: float = 30.0) -> tuple[float, float]:
        """
        Predicts glucose value N minutes from now.
        Returns: (prediction_value, confidence_score)
        """
        if not history:
            return 0.0, 0.0
            
        latest = history[-1]
        
        # Confidence decays as horizon increases
        # Baseline confidence is 0.95 for 5 mins, decaying to ~0.4 for 2 hours
        confidence = max(0.1, 1.0 - (horizon_mins / 120.0))
        
        if not self.is_trained:
            # Weighted Kinematic Algorithm: P = G + (V * t) + (0.5 * A * t^2)
            # Damping applied to velocity to reflect metabolic inertia
            damping = 0.85 if abs(latest.velocity) > 0.1 else 1.0
            
            # Use kinematic equation
            v_term = latest.velocity * horizon_mins * damping
            a_term = 0.5 * latest.acceleration * (horizon_mins ** 2) * 0.5 # Extra damping on acceleration
            
            prediction = latest.filtered_value + v_term + a_term
            
            # Apply physiological floor
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

   
