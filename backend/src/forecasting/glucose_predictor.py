import numpy as np
import xgboost as xgb
from typing import List, Optional
from backend.src.registry import MetabolicSnapshot
from backend.src.features.metabolic_math import MetabolicMath

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
        Extracts features from the latest snapshot.
        Format: [glucose, velocity, acceleration, lbgi, hbgi]
        """
        if not history:
            return np.array([])
            
        latest = history[-1]
        lbgi, hbgi = MetabolicMath.calculate_risk_indices(latest.filtered_value)
        
        # Feature vector
        features = np.array([[
            latest.filtered_value,
            latest.velocity,
            latest.acceleration,
            lbgi,
            hbgi
        ]])
        
        return features

    def predict_30m(self, history: List[MetabolicSnapshot]) -> float:
        """
        Predicts glucose value 30 minutes from now.
        Fallback: Linear extrapolation if model not trained.
        """
        if not history:
            return 0.0
            
        if not self.is_trained:
            # Fallback to kinematic extrapolation: G_30 = G_0 + (V * 30) + (0.5 * A * 30^2)
            latest = history[-1]
            prediction = latest.filtered_value + (latest.velocity * 30.0) + (0.5 * latest.acceleration * (30.0**2))
            return max(2.2, prediction) # Physiological floor
            
        features = self._prepare_features(history)
        prediction = self.model.predict(features)[0]
        return float(prediction)

    def load_model(self, path: str):
        """Loads a pre-trained XGBoost model."""
        self.model.load_model(path)
        self.is_trained = True

if __name__ == "__main__":
    # Test kinematic fallback
    from datetime import datetime
    from backend.src.registry import GlucoseReading
    
    forecaster = GlucoseForecaster()
    snap = MetabolicSnapshot(
        glucose=GlucoseReading(timestamp=datetime.now(), value=150.0),
        filtered_value=150.0,
        velocity=1.0,
        acceleration=0.1
    )
    
    pred = forecaster.predict_30m([snap])
    print(f"Current: 150.0 | Predicted 30m (Kinematic): {pred:.2f}")
