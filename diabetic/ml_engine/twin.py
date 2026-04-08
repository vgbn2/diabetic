import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional
from src.shared.core.registry import MealEvent, InsulinDose, MetabolicSnapshot
from src.shared.core import medical_constants as mc

class DigitalTwin:
    """
    Simulation engine for 4-hour forward projections of carb AND insulin impact.
    Uses adaptive physiological baselines that auto-tune based on user CGM data.
    Tracks both Carb Sensitivity (CSF) and Insulin Sensitivity (ISF).
    """
    def __init__(self, csf: float = mc.CARB_SENSITIVITY_DEFAULT,
                 isf: float = mc.INSULIN_SENSITIVITY_DEFAULT,
                 gender: str = "MALE",
                 age: int = 30,
                 weight_kg: float = 75.0,
                 height_cm: float = 175.0,
                 ethnicity: str = "ASIAN",
                 nationality: str = "VIETNAMESE",
                 religion: str = "NON_RELIGIOUS",
                 diabetes_type: str = "T1D",
                 diagnosis_year: int = 2020,
                 activity_level: str = "MODERATE",
                 fructosamin: float = 250.0,
                 is_inflamed: bool = False,
                 cycle_start: str = "2026-04-01"):
        self.csf = csf
        self.isf = isf
        self.gender = gender.upper()
        self.age = age
        self.weight_kg = weight_kg
        self.height_cm = height_cm
        self.ethnicity = ethnicity.upper()
        self.nationality = nationality.upper()
        self.religion = religion.upper()
        self.diabetes_type = diabetes_type.upper()
        self.diagnosis_year = diagnosis_year
        self.activity_level = activity_level.upper()
        self.fructosamin = fructosamin
        self.is_inflamed = is_inflamed
        
        try:
            self.cycle_start = datetime.strptime(cycle_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            self.cycle_start = datetime(2026, 4, 1, tzinfo=timezone.utc)
        
        self.liquid_tau = mc.CARB_ABS_LIQUID_TAU
        self.starch_tau = mc.CARB_ABS_STARCH_TAU
        self.regime_multiplier = 1.0

    def get_hormonal_multiplier(self, timestamp: datetime) -> float:
        """
        Calculates insulin resistance multiplier based on clinical, biological, and circadian states.
        """
        # 1. Base Multiplier & Clinical Bias
        # Fructosamin > 285 indicates persistent historic hyperglycemia (resistance)
        clinical_bias = 1.0
        if self.fructosamin > 285:
            clinical_bias += 0.10 # +10% base resistance from metabolic memory
        
        if self.is_inflamed:
            clinical_bias += 0.15 # +15% resistance from LEU/infection stress
            
        resistance = clinical_bias
        
        # 2. Circadian Logic (24h Oscillation)
        hour_pos = (timestamp.hour + timestamp.minute / 60.0) / 24.0
        circadian_resistance = 0.05 * np.sin(2 * np.pi * (hour_pos - 0.375)) 
        resistance += circadian_resistance

        # 3. Macro-Cycle Logic
        if self.gender == "FEMALE":
            days_since = (timestamp - self.cycle_start).total_seconds() / (3600 * 24)
            cycle_pos = (2 * np.pi * (days_since % mc.MENSTRUAL_CYCLE_DAYS) / mc.MENSTRUAL_CYCLE_DAYS)
            resistance += (mc.LUTEAL_RESISTANCE_MULT - 1.0) * (0.5 * (1 + np.sin(cycle_pos - np.pi/2)))
            
        return resistance

    def simulate_carb_impact(self, carbs_g: float, gi_type: str = "STARCH", 
                            resolution_mins: Optional[float] = None,
                            stochastic: bool = False,
                            timestamp: Optional[datetime] = None) -> np.ndarray:
        if resolution_mins is None:
            resolution_mins = mc.SAMPLING_INTERVAL_MINS
        tau = self.liquid_tau if gi_type.upper() == "LIQUID" else self.starch_tau
        
        hormonal_mult = self.get_hormonal_multiplier(timestamp) if timestamp else 1.0

        if stochastic:
            tau *= np.random.uniform(0.8, 1.2)
            carbs_g *= np.random.uniform(0.85, 1.15)

        t = np.arange(0, 240 + resolution_mins, resolution_mins)
        impact = (t / tau) * np.exp(1 - t / tau)
        total_rise = carbs_g * self.csf * self.regime_multiplier * hormonal_mult
        curve = impact * total_rise
        return curve

    def simulate_insulin_impact(self, units: float, insulin_type: str = "RAPID",
                                resolution_mins: Optional[float] = None,
                                stochastic: bool = False,
                                timestamp: Optional[datetime] = None) -> np.ndarray:
        if resolution_mins is None:
            resolution_mins = mc.SAMPLING_INTERVAL_MINS
        
        hormonal_mult = self.get_hormonal_multiplier(timestamp) if timestamp else 1.0
        effective_isf = self.isf / hormonal_mult

        duration = mc.INSULIN_ACTION_WINDOW_MINS
        t = np.arange(0, duration + resolution_mins, resolution_mins)

        if insulin_type.upper() == "LONG":
            total_drop = units * effective_isf
            drop_per_min = total_drop / (mc.BASAL_DURATION_HOURS * 60.0)
            curve = np.full_like(t, drop_per_min * resolution_mins, dtype=float)
            return np.cumsum(curve)

        tau = mc.INSULIN_PEAK_TAU_RAPID
        onset = mc.INSULIN_ONSET_LAG_MINS

        if stochastic:
            tau *= np.random.uniform(0.9, 1.1)
            onset *= np.random.uniform(0.8, 1.5)
            units *= np.random.uniform(0.95, 1.05)

        impact = (t / tau) * np.exp(1 - t / tau)
        onset_ramp = 1.0 / (1.0 + np.exp(-(t - onset) / 3.0))
        impact *= onset_ramp

        total_drop = units * effective_isf * self.regime_multiplier
        curve = impact * total_drop
        return curve

    def predict_4h_trajectory(self, history: List[MetabolicSnapshot],
                              meals: Optional[List[MealEvent]] = None,
                              insulin_doses: Optional[List[InsulinDose]] = None,
                              basal_drift: Optional[np.ndarray] = None) -> np.ndarray:
        if not history:
            points = int(240 / mc.SAMPLING_INTERVAL_MINS) + 1
            return np.zeros(points)
        latest = history[-1]
        dt = mc.SAMPLING_INTERVAL_MINS
        t = np.arange(0, 240 + dt, dt)

        decay_mins = mc.KINEMATIC_DECAY_MINS
        velocity_decay = np.maximum(0, 1.0 - (t / decay_mins))
        kinematic_delta = (latest.velocity * t) * velocity_decay

        base_curve = latest.filtered_value + kinematic_delta
        
        if basal_drift is not None:
            if len(basal_drift) >= len(t):
                base_curve += (basal_drift[:len(t)] - basal_drift[0])

        if meals:
            for meal in meals:
                if not meal.carbs: continue
                dt_meal_mins = (latest.glucose.timestamp - meal.timestamp).total_seconds() / 60.0
                if dt_meal_mins > 240.0: continue

                full_meal_curve = self.simulate_carb_impact(meal.carbs, meal.gi_type, timestamp=meal.timestamp)
                start_idx = int(max(0, dt_meal_mins // dt))
                meal_projection = full_meal_curve[start_idx : start_idx + len(t)]
                
                if len(meal_projection) < len(t):
                    meal_projection = np.pad(meal_projection, (0, len(t) - len(meal_projection)))
                base_curve += meal_projection

        if insulin_doses:
            for dose in insulin_doses:
                if dose.units <= 0: continue
                dt_insulin_mins = (latest.glucose.timestamp - dose.timestamp).total_seconds() / 60.0
                if dt_insulin_mins > mc.INSULIN_ACTION_WINDOW_MINS: continue

                full_insulin_curve = self.simulate_insulin_impact(dose.units, dose.type, timestamp=dose.timestamp)
                start_idx = int(max(0, dt_insulin_mins // dt))
                insulin_projection = full_insulin_curve[start_idx : start_idx + len(t)]

                if len(insulin_projection) < len(t):
                    insulin_projection = np.pad(insulin_projection, (0, len(t) - len(insulin_projection)))
                base_curve -= insulin_projection

        return np.maximum(mc.PHYSIO_FLOOR, base_curve)

    def predict_monte_carlo(self, history: List[MetabolicSnapshot],
                            meals: List[MealEvent],
                            insulin: List[InsulinDose],
                            basal_drift: Optional[np.ndarray] = None,
                            N: int = 30) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        if not history:
            pts = int(240/mc.SAMPLING_INTERVAL_MINS)+1
            return np.zeros(pts), np.zeros(pts), np.zeros(pts)

        all_sims = []
        orig_isf = self.isf
        orig_csf = self.csf
        orig_liquid = self.liquid_tau
        orig_starch = self.starch_tau

        for _ in range(N):
            self.isf = orig_isf * np.random.uniform(0.85, 1.15)
            self.csf = orig_csf * np.random.uniform(0.9, 1.1)
            self.liquid_tau = orig_liquid * np.random.uniform(0.8, 1.2)
            self.starch_tau = orig_starch * np.random.uniform(0.8, 1.2)
            
            traj = self.predict_4h_trajectory(history, meals, insulin, basal_drift)
            all_sims.append(traj)

        self.isf = orig_isf
        self.csf = orig_csf
        self.liquid_tau = orig_liquid
        self.starch_tau = orig_starch

        stack = np.vstack(all_sims)
        mean_traj = np.mean(stack, axis=0)
        p5_traj   = np.percentile(stack, 5, axis=0)
        p95_traj  = np.percentile(stack, 95, axis=0)

        return mean_traj, p5_traj, p95_traj

    def auto_tune(self, actual_glucose: float, predicted_glucose: float, context: str = "MEAL"):
        if predicted_glucose <= 0.1: return
        error_ratio = actual_glucose / predicted_glucose
        adjustment = np.clip(1.0 + (error_ratio - 1.0) * 0.1, 0.8, 1.2)
        if context == "CORRECTION":
            self.isf *= adjustment
        else:
            self.csf *= adjustment

    def detect_regime(self, history: List[MetabolicSnapshot]) -> str:
        if len(history) < mc.REGIME_MIN_SNAPSHOTS:
            return "NORMAL"
        recent_samples = int(360 / mc.SAMPLING_INTERVAL_MINS)
        recent_avg = np.mean([s.filtered_value for s in history[-recent_samples:]])
        long_avg = np.mean([s.filtered_value for s in history])
        if recent_avg > long_avg * 1.15:
            self.regime_multiplier = mc.REGIME_SENSITIVITY_MULT
            return "HIGH_RESISTANCE"
        self.regime_multiplier = 1.0
        return "NORMAL"