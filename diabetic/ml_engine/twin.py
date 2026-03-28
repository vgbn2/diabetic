import numpy as np
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from diabetic.registry import MealEvent, MetabolicSnapshot
from diabetic import medical_constants

class DigitalTwin:
    """
    Simulation engine for 4-hour forward projections of carb metabolic impact.
    Uses adaptive physiological baselines that auto-tune based on user CGM data.
    """
    def __init__(self, csf: float = medical_constants.CARB_SENSITIVITY_DEFAULT):
        self.csf = csf
        self.liquid_tau = medical_constants.CARB_ABS_LIQUID_TAU
        self.starch_tau = medical_constants.CARB_ABS_STARCH_TAU
        self.regime_multiplier = 1.0

    def simulate_carb_impact(self, carbs_g: float, gi_type: str = "STARCH", resolution_mins: float = 5.0) -> np.ndarray:
        """
        Generates a 4-hour absorption curve.
        Equation: f(t) = (t / tau) * exp(-t / tau)
        Normalized to ensure the area under the curve matches (carbs_g * csf).
        """
        tau = self.liquid_tau if gi_type.upper() == "LIQUID" else self.starch_tau
        
        # 4 hours = 240 mins
        t = np.arange(0, 240 + resolution_mins, resolution_mins)
        
        # Impulse response
        # We use (t/tau) * exp(1 - t/tau) so that peak value is at t=tau
        impact = (t / tau) * np.exp(1 - t / tau)
        
        # Scale by carbs and sensitivity
        # Area calculation: impact integrates to tau * e
        # But we want the total peak rise to be consistent with CSF
        # Peak of (t/tau)*exp(1-t/tau) is 1.0 at t=tau.
        # So we scale by (carbs_g * csf)
        total_rise = carbs_g * self.csf * self.regime_multiplier
        curve = impact * total_rise
        
        return curve

    def predict_4h_trajectory(self, history: List[MetabolicSnapshot], meal: Optional[MealEvent] = None) -> np.ndarray:
        """
        Combines current kinematic trajectory with any pending meal impact.
        Returns 48 data points (4h @ 5min).
        """
        if not history:
            return np.zeros(49)

        latest = history[-1]
        dt = medical_constants.SAMPLING_INTERVAL_MINS
        t = np.arange(0, 240 + dt, dt)
        
        # 1. Base Trajectory (Physics-based projection)
        # We assume the current velocity tapers off over 90 mins (linear decay)
        velocity_decay = np.maximum(0, 1.0 - (t / 90.0))
        kinematic_delta = (latest.velocity * t) * velocity_decay
        
        base_curve = latest.filtered_value + kinematic_delta
        
        # 2. Add Meal Impact if present
        if meal and meal.carbs:
            # Shift meal start time if it was logged in the past relative to 'latest'
            dt_meal_mins = (latest.glucose.timestamp - meal.timestamp).total_seconds() / 60.0
            
            # Simple approach: simulate from meal start and crop
            full_meal_curve = self.simulate_carb_impact(meal.carbs, meal.gi_type)
            
            # If meal was logged 20 mins ago, our projection (t=0) corresponds to meal-t=20
            dt = medical_constants.SAMPLING_INTERVAL_MINS
            start_idx = int(max(0, dt_meal_mins // dt))
            meal_projection = full_meal_curve[start_idx : start_idx + len(t)]
            
            # Pad with 0s if meal impacts end before simulation
            if len(meal_projection) < 49:
                 meal_projection = np.pad(meal_projection, (0, 49 - len(meal_projection)))
                 
            base_curve += meal_projection

        return np.maximum(medical_constants.PHYSIO_FLOOR, base_curve)

    def auto_tune(self, actual_glucose: float, predicted_glucose: float):
        """
        Feedback Loop (Plan 8.3): Adjust sensitivity based on error.
        Gradual learning rate (10%) to prevent over-correction.
        """
        if predicted_glucose <= 0.1: return # Prevent div by zero
        
        error_ratio = actual_glucose / predicted_glucose
        # Bound correction to 0.8 - 1.2
        adjustment = np.clip(1.0 + (error_ratio - 1.0) * 0.1, 0.8, 1.2)
        
        self.csf *= adjustment
        print(f"Twin Auto-Tune: New CSF = {self.csf:.4f}")

    def detect_regime(self, multi_day_history: List[MetabolicSnapshot]) -> str:
        """
        Plan 8.4: Regime Detection (Hormonal/Circadian).
        Flags baseline shifts greater than 10% as 'HIGH_RESISTANCE'.
        """
        if len(multi_day_history) < 200: # Needs ~1 day of data
            return "NORMAL"
            
        # Compare last 6 hours to last 3 days
        recent_avg = np.mean([s.filtered_value for s in multi_day_history[-72:]]) # 6 hours
        long_avg = np.mean([s.filtered_value for s in multi_day_history])
        
        if recent_avg > long_avg * 1.15:
            self.regime_multiplier = medical_constants.REGIME_SENSITIVITY_MULT
            return "HIGH_RESISTANCE"
        
        self.regime_multiplier = 1.0
        return "NORMAL"

if __name__ == "__main__":
    # Internal test
    twin = DigitalTwin()
    curve = twin.simulate_carb_impact(60, "STARCH")
    print(f"Peak Glucose Rise: {np.max(curve):.2f} mmol/L at {np.argmax(curve)*5} mins")
