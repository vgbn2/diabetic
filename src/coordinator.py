import time
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any

from .nightscout_client import NightscoutClient
from .ingestion_engine import IngestionEngine
from .filters.metabolic_ukf import MetabolicUKF
from .features.stress import DynamicStressIndex, HRVRecord
from .alerts.controller import AIAlertController
from .models.registry import ModelRegistry
from .logger import logger

class BioQuantCoordinator:
    """
    The central coordinator that manages the full Bio-Quant pipeline:
    Ingestion -> Filtering -> Stress Tracking -> ML Prediction -> AI Alerting.
    """
    
    def __init__(self, use_mock_model: bool = True):
        self.client = NightscoutClient()
        self.engine = IngestionEngine()
        self.ukf = MetabolicUKF()
        self.stress_tracker = DynamicStressIndex()
        self.alert_controller = AIAlertController()
        
        # Load the ML Predictor (XGBoost by default)
        try:
            self.predictor = ModelRegistry.get_model("xgboost")
            if use_mock_model:
                # In a real scenario, we'd load a trained .json/.pkl file
                # For now, we'll mark it as 'trained' for demonstration
                self.predictor.is_trained = True 
        except Exception as e:
            logger.error(f"Failed to initialize ML Predictor: {e}")
            self.predictor = None

    def run_cycle(self, 
                  current_hrv: Optional[float] = None, 
                  manual_insulin: float = 0.0, 
                  manual_carbs: float = 0.0) -> Dict[str, Any]:
        """
        Runs one complete metabolic analysis cycle.
        """
        logger.info("--- Starting Bio-Quant Analysis Cycle ---")
        
        # 1. Fetch Raw Data
        raw_glucose = self.client.fetch_latest_readings(count=5)
        if not raw_glucose:
            logger.warning("No data retrieved from Nightscout. Cycle aborted.")
            return {"status": "NO_DATA"}

        # 2. Update Dynamic Stress Index
        if current_hrv:
            self.stress_tracker.add_reading(HRVRecord(timestamp=datetime.now(), rmssd=current_hrv))
        dsi = self.stress_tracker.get_current_dsi(current_rmssd=current_hrv)
        
        # 3. Filter & State Estimation (UKF)
        # We take the latest reading as our 'observation'
        latest_g = raw_glucose[0].sgv
        
        # We calculate current IOB/COB from kinetics (simplified for real-time)
        # In production, this would pull from the treatments API
        filtered_state = self.ukf.update(
            z_glucose=latest_g, 
            iob=manual_insulin, 
            cob=manual_carbs, 
            dsi=dsi
        )
        
        # 4. ML Prediction (30-min Lead Time)
        predicted_g = latest_g # Fallback
        if self.predictor:
            try:
                # Features: SGV, Velocity, Accel, IOB, COB, DSI
                pred_input = {
                    "sgv": filtered_state["glucose"],
                    "velocity": filtered_state["velocity"],
                    "acceleration": filtered_state["acceleration"],
                    "iob": manual_insulin,
                    "cob": manual_carbs,
                    "dsi": dsi
                }
                predicted_g = self.predictor.predict(pred_input)
            except Exception as e:
                logger.error(f"ML Prediction failed: {e}")

        # 5. AI Alert Evaluation
        alert_level, message = self.alert_controller.evaluate_state(
            current_glucose=latest_g,
            predicted_glucose=predicted_g,
            dsi=dsi
        )
        
        result = {
            "timestamp": datetime.now(),
            "glucose": latest_g,
            "filtered_glucose": filtered_state["glucose"],
            "velocity": filtered_state["velocity"],
            "predicted_30m": predicted_g,
            "dsi": dsi,
            "alert_level": alert_level,
            "message": message
        }
        
        logger.info(f"Cycle Complete. Status: {alert_level} | Msg: {message}")
        return result

if __name__ == "__main__":
    # Test Coordinator in a loop
    coordinator = BioQuantCoordinator()
    
    # Simulate a few cycles
    for i in range(3):
        res = coordinator.run_cycle(current_hrv=45.0)
        print(f"\n[{res['timestamp']}] G: {res['glucose']} | Pred: {res['predicted_30m']:.1f} | Stress: {res['dsi']:.1f}")
        print(f"Alert: {res['alert_level']} - {res['message']}")
        time.sleep(2)
