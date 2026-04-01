import numpy as np
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from diabetic.registry import MealEvent, InsulinDose, MetabolicSnapshot
from diabetic import medical_constants as mc

class DigitalTwin:
    """
    Simulation engine for 4-hour forward projections of carb AND insulin impact.
    Uses adaptive physiological baselines that auto-tune based on user CGM data.
    Tracks both Carb Sensitivity (CSF) and Insulin Sensitivity (ISF).
    """
    def __init__(self, csf: float = mc.CARB_SENSITIVITY_DEFAULT,
                 isf: float = mc.INSULIN_SENSITIVITY_DEFAULT):
        self.csf = csf
        self.isf = isf  # mmol/L drop per 1 Unit of rapid-acting insulin
        self.liquid_tau = mc.CARB_ABS_LIQUID_TAU
        self.starch_tau = mc.CARB_ABS_STARCH_TAU
        self.regime_multiplier = 1.0

    def simulate_carb_impact(self, carbs_g: float, gi_type: str = "STARCH", resolution_mins: Optional[float] = None) -> np.ndarray:
        """
        Generates a 4-hour absorption curve.
        Equation: f(t) = (t / tau) * exp(1 - t / tau)
        Peak value is 1.0 at t = tau, scaled by (carbs_g * csf).
        """
        if resolution_mins is None:
            resolution_mins = mc.SAMPLING_INTERVAL_MINS
        tau = self.liquid_tau if gi_type.upper() == "LIQUID" else self.starch_tau

        t = np.arange(0, 240 + resolution_mins, resolution_mins)

        # Impulse response — peak at t=tau, value=1.0
        impact = (t / tau) * np.exp(1 - t / tau)

        total_rise = carbs_g * self.csf * self.regime_multiplier
        curve = impact * total_rise

        return curve

    def simulate_insulin_impact(self, units: float, insulin_type: str = "RAPID",
                                resolution_mins: Optional[float] = None) -> np.ndarray:
        """
        Generates a 4-hour insulin activity curve (downward glucose pressure).

        RAPID (Bolus): Impulse-response with onset lag.
            - At t < INSULIN_ONSET_LAG_MINS (~15m): impact ≈ 0 (subcutaneous absorption delay).
            - Peak at t = INSULIN_PEAK_TAU_RAPID (~55m).
            - Total duration: INSULIN_ACTION_WINDOW_MINS (240m).
            This models why glucose keeps rising immediately after injection.

        LONG (Basal): Flat distribution over 24 hours.
            - Constant downward pressure = (units * ISF) / (24h in intervals).
        """
        if resolution_mins is None:
            resolution_mins = mc.SAMPLING_INTERVAL_MINS

        duration = mc.INSULIN_ACTION_WINDOW_MINS
        t = np.arange(0, duration + resolution_mins, resolution_mins)

        if insulin_type.upper() == "LONG":
            # Flat 24h distribution — only project the 4h window we care about
            total_drop = units * self.isf
            drop_per_min = total_drop / (mc.BASAL_DURATION_HOURS * 60.0)
            curve = np.full_like(t, drop_per_min * resolution_mins, dtype=float)
            return np.cumsum(curve)

        # RAPID: impulse-response with onset lag
        tau = mc.INSULIN_PEAK_TAU_RAPID
        onset = mc.INSULIN_ONSET_LAG_MINS

        # Base impulse: f(t) = (t/tau) * exp(1 - t/tau), peak=1.0 at t=tau
        impact = (t / tau) * np.exp(1 - t / tau)

        # Apply onset lag: near-zero impact before onset threshold
        # Smooth sigmoid ramp instead of hard cutoff for numerical stability
        onset_ramp = 1.0 / (1.0 + np.exp(-(t - onset) / 3.0))
        impact *= onset_ramp

        total_drop = units * self.isf * self.regime_multiplier
        curve = impact * total_drop

        return curve

    def predict_4h_trajectory(self, history: List[MetabolicSnapshot],
                              meal: Optional[MealEvent] = None,
                              insulin: Optional[InsulinDose] = None) -> np.ndarray:
        """
        Combines current kinematic trajectory with any pending meal impact.
        Returns 49 data points (4h @ 5min intervals, t=0 to t=240).

        Kinematic decay: current velocity tapers linearly to zero over
        KINEMATIC_DECAY_MINS (mc, default 90 min).
        FIX T2: the 90-minute figure is now a named constant in mc
        rather than a magic number. Past KINEMATIC_DECAY_MINS, the kinematic
        contribution is zero and only meal absorption drives the curve. For
        fasting scenarios this means the trajectory is flat after t=90 — which
        is the intended behaviour (no nutrient input = momentum exhausted).
        """
        if not history:
            points=int(240/mc.SAMPLING_INTERVAL_MINS)+1
            return np.zeros(points)
        latest = history[-1]
        dt = mc.SAMPLING_INTERVAL_MINS
        t = np.arange(0, 240 + dt, dt)

        # Kinematic base: velocity decays linearly over KINEMATIC_DECAY_MINS
        decay_mins = mc.KINEMATIC_DECAY_MINS
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

        # Subtract Insulin Impact if present
        if insulin and insulin.units > 0:
            dt_insulin_mins = (latest.glucose.timestamp - insulin.timestamp).total_seconds() / 60.0

            full_insulin_curve = self.simulate_insulin_impact(insulin.units, insulin.type)

            start_idx = int(max(0, dt_insulin_mins // dt))
            insulin_projection = full_insulin_curve[start_idx : start_idx + len(t)]

            if len(insulin_projection) < len(t):
                insulin_projection = np.pad(insulin_projection, (0, len(t) - len(insulin_projection)))

            base_curve -= insulin_projection

        return np.maximum(mc.PHYSIO_FLOOR, base_curve)

    def auto_tune(self, actual_glucose: float, predicted_glucose: float,
                  context: str = "MEAL"):
        """
        Feedback Loop: Adjust CSF or ISF based on prediction error.
        - context="MEAL": tunes CSF (carb sensitivity).
        - context="CORRECTION": tunes ISF (insulin sensitivity).
        Gradual learning rate (10%) to prevent over-correction.
        """
        if predicted_glucose <= 0.1:
            return  # Prevent div by zero

        error_ratio = actual_glucose / predicted_glucose
        adjustment = np.clip(1.0 + (error_ratio - 1.0) * 0.1, 0.8, 1.2)

        if context == "CORRECTION":
            self.isf *= adjustment
            print(f"Twin Auto-Tune: New ISF = {self.isf:.4f}")
        else:
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
        if len(multi_day_history) < mc.REGIME_MIN_SNAPSHOTS:
            return "NORMAL"

        # Compare last 6 hours (~360 mins) against full available history
        recent_samples = int(360 / mc.SAMPLING_INTERVAL_MINS)
        recent_avg = np.mean([s.filtered_value for s in multi_day_history[-recent_samples:]])
        long_avg = np.mean([s.filtered_value for s in multi_day_history])

        if recent_avg > long_avg * 1.15:
            self.regime_multiplier = mc.REGIME_SENSITIVITY_MULT
            return "HIGH_RESISTANCE"

        self.regime_multiplier = 1.0
        return "NORMAL"

if __name__ == "__main__":
    twin = DigitalTwin()
    interval = mc.SAMPLING_INTERVAL_MINS

    # Carb test
    carb_curve = twin.simulate_carb_impact(60, "STARCH")
    print(f"[CARB] Peak Rise: {np.max(carb_curve):.2f} mmol/L at {np.argmax(carb_curve)*interval:.0f} mins")

    # Rapid insulin test
    rapid_curve = twin.simulate_insulin_impact(2.0, "RAPID")
    peak_idx = np.argmax(rapid_curve)
    print(f"[RAPID INSULIN] Peak Drop: {np.max(rapid_curve):.2f} mmol/L at {peak_idx*interval:.0f} mins")
    print(f"[RAPID INSULIN] Impact at t=0: {rapid_curve[0]:.4f} (should be ~0)")
    onset_idx = int(mc.INSULIN_ONSET_LAG_MINS / interval)
    print(f"[RAPID INSULIN] Impact at t={mc.INSULIN_ONSET_LAG_MINS}m: {rapid_curve[onset_idx]:.4f} (ramping)")

    # Long insulin test
    long_curve = twin.simulate_insulin_impact(20.0, "LONG")
    print(f"[LONG INSULIN] Cumulative 4h drop: {long_curve[-1]:.2f} mmol/L")