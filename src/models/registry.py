from abc import ABC, abstractmethod
import pandas as pd
from typing import Dict, Any, Type
from ..logger import logger

class BasePredictor(ABC):
    """
    Abstract Base Class for all Glucose Prediction Models (XGBoost, TFT, etc.).
    Ensures that as the project scales, new models can be swapped seamlessly.
    """
    
    @abstractmethod
    def train(self, df: pd.DataFrame, target_col: str = 'sgv_target'):
        """Train the model on the provided historical DataFrame."""
        pass

    @abstractmethod
    def predict(self, current_state: Dict[str, Any]) -> float:
        """
        Predict the glucose value 30 minutes into the future based on the current state.
        current_state might include: SGV, Velocity, Acceleration, IOB, COB, DSI.
        """
        pass
    
    @abstractmethod
    def save(self, filepath: str):
        """Save model weights to disk."""
        pass
        
    @abstractmethod
    def load(self, filepath: str):
        """Load model weights from disk."""
        pass

class ModelRegistry:
    """Central registry to manage and instantiate different prediction models."""
    
    _models: Dict[str, Type[BasePredictor]] = {}
    
    @classmethod
    def register(cls, name: str):
        """Decorator to register a model class."""
        def wrapper(model_class: Type[BasePredictor]):
            cls._models[name] = model_class
            return model_class
        return wrapper
        
    @classmethod
    def get_model(cls, name: str, **kwargs) -> BasePredictor:
        """Instantiate a model by name."""
        if name not in cls._models:
            raise ValueError(f"Model '{name}' is not registered. Available: {list(cls._models.keys())}")
        logger.info(f"Instantiating model: {name}")
        return cls._models[name](**kwargs)
