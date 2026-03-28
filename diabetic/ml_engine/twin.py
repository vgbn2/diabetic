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
        Equation: f(t) = (t / tau) * exp(1 - t / tau)
        Peak value is 1.0 at t = tau, scaled by (carbs_g * csf).
        """
        tau = self.liquid_tau if gi_type.upper() == "LIQUID" else self.starch_tau

        t = np.arange(0, 240 + resolution_mins, resolution_mins)

        # Impulse response — peak at t=tau, value=1.0
        impact = (t / tau) * np.exp(1 - t / tau)

        total_rise = carbs_g * self.csf * self.regime_multiplier
        curve = impact * total_rise

        return curve

    def predict_4h_trajectory(self, history: List[MetabolicSnapshot], meal: Optional[MealEvent] = None) -> np.ndarray:
        """
        Combines current kinematic trajectory with any pending meal impact.
        Returns 49 data points (4h @ 5min intervals, t=0 to t=240).

        Kinematic decay: current velocity tapers linearly to zero over
        KINEMATIC_DECAY_MINS (medical_constants, default 90 min).
        FIX T2: the 90-minute figure is now a named constant in medical_constants
        rather than a magic number. Past KINEMATIC_DECAY_MINS, the kinematic
        contribution is zero and only meal absorption drives the curve. For
        fasting scenarios this means the trajectory is flat after t=90 — which
        is the intended behaviour (no nutrient input = momentum exhausted).
        """
        if not history:
            return np.zeros(49)

        latest = history[-1]
        dt = medical_constants.SAMPLING_INTERVAL_MINS
        t = np.arange(0, 240 + dt, dt)

        # Kinematic base: velocity decays linearly over KINEMATIC_DECAY_MINS
        decay_mins = medical_constants.KINEMATIC_DECAY_MINS
        velocity_decay = np.maximum(0, 1.0 - (t / decay_mins))
        kinematic_delta = (latest.velocity * t) * velocity_decay

        base_curve = latest.filtered_value + kinematic_delta

        # Add Meal Impact if present
        if meal and meal.carbs:
            dt_meal_mins = (latest.glucose.timestamp - meal.timestamp).total_seconds() / 60.0

            full_meal_curve = self.simulate_carb_impact(meal.carbs, meal.gi_type)

            start_idx = int(max(0, dt_meal_mins // dt))
            meal_projection = full_meal_curve[start_idx : start_idx + len(t)]

            if len(meal_projection) < len(t):
                meal_projection = np.pad(meal_projection, (0, len(t) - len(meal_projection)))

            base_curve += meal_projection

        return np.maximum(medical_constants.PHYSIO_FLOOR, base_curve)

    def auto_tune(self, actual_glucose: float, predicted_glucose: float):
        """
        Feedback Loop (Plan 8.3): Adjust CSF based on post-meal prediction error.
        Gradual learning rate (10%) to prevent over-correction.

        FIX V2 dependency: this method now receives the correct predicted_glucose
        value because coordinator.py writes snapshot.predict_30m = prediction_30m
        before calling auto_tune. Previously snapshot.predict_30m was always 0.0,
        causing the early-exit guard below to fire every time.
        """
        if predicted_glucose <= 0.1:
            return  # Prevent div by zero — should not occur after V2 fix

        error_ratio = actual_glucose / predicted_glucose
        adjustment = np.clip(1.0 + (error_ratio - 1.0) * 0.1, 0.8, 1.2)

        self.csf *= adjustment
        print(f"Twin Auto-Tune: New CSF = {self.csf:.4f}")

    def detect_regime(self, multi_day_history: List[MetabolicSnapshot]) -> str:
        """
        Plan 8.4: Regime Detection (Hormonal/Circadian).
        Flags baseline shifts greater than 15% as 'HIGH_RESISTANCE'.

        FIX T4: requires REGIME_MIN_SNAPSHOTS (200) readings = ~16.7 hours.
        coordinator.py now caps the ring buffer at SNAPSHOT_CAP (300) instead
        of the previous 100, so this threshold can actually be reached.
        If called with fewer snapshots, returns NORMAL conservatively.
        """
        if len(multi_day_history) < medical_constants.REGIME_MIN_SNAPSHOTS:
            return "NORMAL"

        # Compare last 6 hours (~72 readings) against full available history
        recent_avg = np.mean([s.filtered_value for s in multi_day_history[-72:]])
        long_avg = np.mean([s.filtered_value for s in multi_day_history])

        if recent_avg > long_avg * 1.15:
            self.regime_multiplier = medical_constants.REGIME_SENSITIVITY_MULT
            return "HIGH_RESISTANCE"

        self.regime_multiplier = 1.0
        return "NORMAL"

if __name__ == "__main__":
    twin = DigitalTwin()
    curve = twin.simulate_carb_impact(60, "STARCH")
    print(f"Peak Glucose Rise: {np.max(curve):.2f} mmol/L at {np.argmax(curve)*5} mins")