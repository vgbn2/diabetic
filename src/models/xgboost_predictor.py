import pandas as pd
import numpy as np
from typing import Dict, Any
from .registry import BasePredictor, ModelRegistry
from ..logger import logger

try:
    import xgboost as xgb
except ImportError:
    logger.warning("XGBoost is not installed. Run `pip install xgboost` to use XGBoostPredictor.")

@ModelRegistry.register("xgboost")
class XGBoostPredictor(BasePredictor):
    """
    Fast, efficient baseline predictor for 30-minute glucose forecasting.
    Ideal for real-time edge/mobile deployment.
    """
    def __init__(self, n_estimators=100, max_depth=3, learning_rate=0.1):
        self.model = xgb.XGBRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            objective='reg:squarederror'
        )
        self.features = ['sgv', 'velocity', 'remote_insulin', 'iob', 'cob', 'dsi']
        self.is_trained = False

    def train(self, df: pd.DataFrame, target_col: str = 'sgv_target_30m'):
        """
        Trains the XGBoost model.
        Expects a DataFrame where the target column is already shifted (-30 mins).
        """
        if target_col not in df.columns:
            raise ValueError(f"Target column '{target_col}' not found in DataFrame.")
            
        # Ensure all required features exist, fill missing with 0 for 'dsi', 'iob', etc. if needed
        for feat in self.features:
            if feat not in df.columns:
                logger.warning(f"Feature '{feat}' missing from training data. Filling with 0.")
                df[feat] = 0.0
                
        # Drop rows with NaN in features or target
        train_df = df.dropna(subset=self.features + [target_col])
        
        X = train_df[self.features]
        y = train_df[target_col]
        
        logger.info(f"Training XGBoost on {len(train_df)} samples...")
        self.model.fit(X, y)
        self.is_trained = True
        logger.info("XGBoost training complete.")

    def predict(self, current_state: Dict[str, Any]) -> float:
        if not self.is_trained:
            raise RuntimeError("Model must be trained before calling predict().")
            
        # Construct feature vector
        x_input = pd.DataFrame([{feat: current_state.get(feat, 0.0) for feat in self.features}])
        prediction = self.model.predict(x_input)[0]
        return float(prediction)

    def save(self, filepath: str):
        if self.is_trained:
            self.model.save_model(filepath)
            logger.info(f"Model saved to {filepath}")
        else:
            logger.error("Cannot save untrained model.")

    def load(self, filepath: str):
        self.model.load_model(filepath)
        self.is_trained = True
        logger.info(f"Model loaded from {filepath}")
