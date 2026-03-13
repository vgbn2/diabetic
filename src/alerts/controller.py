from typing import Dict, Any, Tuple
from ..logger import logger

class AIAlertController:
    """
    The 'Brain' that decides whether to send an alert based on predicted glucose,
    current glucose, and the Dynamic Stress Index (DSI).
    """
    
    def __init__(self, hypo_threshold: float = 70.0, hyper_threshold: float = 300.0, stress_threshold: float = 1.8):
        self.hypo_threshold = hypo_threshold
        self.hyper_threshold = hyper_threshold
        self.stress_threshold = stress_threshold

    def evaluate_state(self, current_glucose: float, predicted_glucose: float, dsi: float) -> Tuple[str, str]:
        """
        Evaluates the current metabolic state and returns an alert level and a contextual message.
        """
        
        # 1. CRITICAL HYPO PREDICTION
        if predicted_glucose < self.hypo_threshold:
            # If DSI is rapidly rising alongside a low, it could be a compression low (false) or panic
            if dsi > self.stress_threshold and current_glucose > self.hypo_threshold + 20:
                logger.warning("Hypo predicted, but high stress detected. Possible sensor compression.")
                return "WARNING", "Predicted low, but biometric stress is high. Check sensor for compression before treating."
            
            logger.critical("Hypoglycemic crash predicted.")
            return "CRITICAL_HYPO", f"CRASH ALERT: Glucose predicted to hit {predicted_glucose:.0f} mg/dL in 30 mins. Treat now."

        # 2. HYPER / FAINT RISK
        if current_glucose > self.hyper_threshold:
            if dsi > self.stress_threshold:
                logger.critical("Faint Risk: High Glucose + High Stress (Sympathetic Surge).")
                return "FAINT_RISK", f"DANGER: Glucose {current_glucose:.0f} + Extreme Stress (DSI: {dsi:.1f}). Risk of syncope/dehydration. Hydrate and check ketones."
            else:
                logger.warning("Standard Hyperglycemia.")
                return "WARNING_HYPER", f"High Glucose ({current_glucose:.0f} mg/dL). Consider correction if no active insulin."

        # 3. EMOTIONAL SPIKE (The "Cute Cat" / "Traffic" scenario)
        # If glucose is rising fast but it's largely driven by a stress spike (DSI)
        if predicted_glucose > current_glucose + 30 and dsi > 1.5:
             logger.info("Emotional glucose spike detected.")
             return "INFO", f"Glucose rising, but Heart Rate Variability suggests an emotional/stress response (DSI: {dsi:.1f}). Wait 15 mins before taking insulin."

        return "OK", "Metabolic state is stable."
