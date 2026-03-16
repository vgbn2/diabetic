import os
from typing import Dict, Optional, Tuple
from datetime import datetime
from groq import Groq
from ..config import Config
from ..logger import logger

class UserInteractionAgent:
    """
    Upgraded State-Machine Agent powered by Groq (LLama-3) for ultra-low latency.
    Handles user queries during ambiguous metabolic events and safety checks.
    """
    
    def __init__(self, api_key: str = Config.GROQ_API_KEY):
        self.client = Groq(api_key=api_key) if api_key else None
        self.current_state = "IDLE" # IDLE, AWAITING_CONTEXT, FAINT_CHECK, EMERGENCY
        self.last_interaction_time: Optional[datetime] = None
        self.model = "llama-3.3-70b-versatile" # High-speed reasoning model

    def _get_llm_response(self, system_prompt: str, user_input: str) -> str:
        """Helper to get fast response from Groq."""
        if not self.client:
            return "API_KEY_MISSING: Standby for manual intervention."
            
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input}
                ],
                temperature=0.2, # Low temperature for consistency
                max_tokens=150
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq API Error: {e}")
            return "ERROR: Critical API failure. Please check your metabolic state immediately."

    def process_alert(self, alert_level: str, dsi: float) -> Optional[str]:
        """
        Generates a dynamic query for the user based on the system alert.
        """
        if alert_level == "STRESS_DEVIATION":
            self.current_state = "AWAITING_CONTEXT"
            prompt = (
                "You are an AI metabolic assistant for a diabetic user. "
                "The system detected a glucose rise and a high Stress Index (DSI). "
                "Ask the user a very short, empathetic question to determine if this is food or stress."
            )
            return self._get_llm_response(prompt, f"Status: DSI {dsi:.1f}")
            
        if alert_level == "FAINT_RISK":
            self.current_state = "FAINT_CHECK"
            prompt = (
                "CRITICAL: User is at risk of passing out (Hyperglycemia + Extreme Stress). "
                "Ask the user if they are lightheaded. Command them to reply 'OK' or 'YES' to stop an emergency alert."
            )
            return self._get_llm_response(prompt, "STATUS: CRITICAL FAINT RISK")
            
        return None

    def handle_user_response(self, response: str) -> Tuple[str, Dict]:
        """
        Parses human response using the LLM to decide on actions (Action Parser).
        """
        if self.current_state == "IDLE":
            return "I am monitoring your stats. No action required.", {"action": "NONE"}

        # Use LLM to classify the user's response into an action
        prompt = (
            "You are a medical data classifier. Classify the user response into one of these actions: "
            "1. LOG_TREATMENT (if they mention food/eating) "
            "2. IGNORE_SPIKE (if they mention stress/excitement/work) "
            "3. EMERGENCY_HALT (if they say they are OK during a faint check) "
            "4. CALL_EMERGENCY (if they say NO or don't seem OK) "
            "Return ONLY the action name followed by a short supportive message."
        )
        
        raw_analysis = self._get_llm_response(prompt, f"User said: {response} (State: {self.current_state})")
        
        # Determine instruction
        instructions = {"action": "NONE"}
        if "LOG_TREATMENT" in raw_analysis:
            instructions = {"action": "LOG_TREATMENT", "type": "MEAL"}
        elif "IGNORE_SPIKE" in raw_analysis:
            instructions = {"action": "IGNORE_SPIKE", "duration_mins": 30}
        elif "EMERGENCY_HALT" in raw_analysis:
            instructions = {"action": "NONE"}
        elif "CALL_EMERGENCY" in raw_analysis:
            instructions = {"action": "EMERGENCY_ALERT"}

        self.current_state = "IDLE"
        return raw_analysis, instructions
