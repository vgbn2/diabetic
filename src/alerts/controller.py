import os
import requests
from typing import Dict, Any, Tuple
from ..logger import logger

class MetabolicAlertingService:
    """
    Evaluates metabolic states to determine if safety thresholds have been breached.
    Integrates glucose predictions with the Dynamic Stress Index (DSI).
    """
    
    def __init__(self, hypo_threshold: float = 70.0, hyper_threshold: float = 300.0, stress_threshold: float = 1.8):
        self.hypo_threshold = hypo_threshold
        self.hyper_threshold = hyper_threshold
        self.stress_threshold = stress_threshold
        
        # Telegram Credentials
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.caregiver_id = os.getenv('TELEGRAM_CAREGIVER_ID')

    def evaluate_state(self, current_glucose: float, predicted_glucose: float, dsi: float) -> Tuple[str, str]:
        """
        Inference logic for alert generation.
        """
        
        # 1. Hypoglycemic Prediction
        if predicted_glucose < self.hypo_threshold:
            if dsi > self.stress_threshold and current_glucose > self.hypo_threshold + 20:
                logger.info("Hypoglycemia predicted; however, high DSI suggests potential sensor attenuation.")
                return "CAUTION", "Predicted glucose below threshold. Biometric stress elevated; verify sensor placement."
            
            return "CRITICAL_HYPO", f"Metabolic crash forecast: {predicted_glucose:.0f} mg/dL in T+30m."

        # 2. Hyperglycemia & Syncope Risk
        if current_glucose > self.hyper_threshold:
            if dsi > self.stress_threshold:
                return "FAINT_RISK", f"Critical Hyperglycemia ({current_glucose:.0f}) with sympathetic surge (DSI: {dsi:.1f}). High syncope risk."
            else:
                return "WARNING_HYPER", f"Glucose above threshold: {current_glucose:.0f} mg/dL."

        # 3. Physiological Deviation (Stress-Induced)
        if predicted_glucose > current_glucose + 30 and dsi > 1.5:
             return "STRESS_DEVIATION", f"Positive glucose trend correlated with high DSI ({dsi:.1f}). Recommend observation."

        return "STABLE", "Metabolic parameters within nominal range."

    def _send_telegram(self, chat_id: str, message: str):
        """Helper to send POST request to Telegram API."""
        if not self.token or not chat_id:
            return
        try:
            response = requests.post(
                f'https://api.telegram.org/bot{self.token}/sendMessage',
                json={
                    'chat_id': chat_id,
                    'text': message,
                    'parse_mode': 'HTML'
                },
                timeout=5
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Telegram Delivery error: {e}")

    def alert(self, status: str, message: str):
        """Dispatches alerts to Telegram based on state severity."""
        if status == 'CRITICAL_HYPO':
            msg = f'🚨 <b>CRITICAL HYPO</b>\n{message}\n\nEat fast-acting carbs NOW.'
            self._send_telegram(self.chat_id, msg)
            self._send_telegram(self.caregiver_id, msg)
            
        elif status == 'FAINT_RISK':
            msg = f'⚠️ <b>FAINT RISK</b>\n{message}\n\nSit down. Hydrate. Check ketones.'
            self._send_telegram(self.chat_id, msg)
            self._send_telegram(self.caregiver_id, msg)
            
        elif status in ('WARNING_HYPER', 'STRESS_DEVIATION', 'CAUTION'):
            msg = f'⚡ <b>{status}</b>\n{message}'
            self._send_telegram(self.chat_id, msg)
