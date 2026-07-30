import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional
from diabetic.registry import MealEvent, InsulinDose, MetabolicSnapshot
from diabetic import medical_constants as mc
from diabetic.utils.schedule import schedule_manager

# =============================================================================
# 🧬 [PHYSIOLOGICAL CORE]
# =Focus: Static Biometric Baselines and Hormonal/Circadian Multipliers
# =============================================================================
class DigitalTwin:
    """
    Simulation engine for 4-hour forward projections of carb AND insulin impact.
    Uses adaptive physiological baselines that auto-tune based on user CGM data.
    Tracks both Carb Sensitivity (CSF) and Insulin Sensitivity (ISF).
    """
    def __init__(self, 
                 csf: float = mc.CARB_SENSITIVITY_DEFAULT,
                 isf: float = mc.INSULIN_SENSITIVITY_DEFAULT,
                 gender: str = "FEMALE",
                 age: int = 30,
                 weight_kg: float = 45.0,
                 height_cm: float = 158.0,
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
        
        self.tau_table = {
            "LIQUID": mc.CARB_ABS_LIQUID_TAU,          # 15.0 min — fast GI peak
            "STARCH": mc.CARB_ABS_STARCH_TAU,          # 60.0 min — slow GI peak
            "SLOW_STARCH": mc.CARB_ABS_STARCH_TAU * 1.5, # 90.0 min — oats/beans/lentils
            "PROTEIN": mc.CARB_ABS_STARCH_TAU * 2.2,   # 132.0 min — protein-heavy meals
        }
        self.regime_multiplier = 1.0

    def get_hormonal_multiplier(self, timestamp: datetime) -> float:
        """
        Calculates insulin resistance multiplier based on clinical, biological, and circadian states.
        Multiplicative model to avoid ISF bias.
        """
        # 1. Base Multiplier & Clinical Bias
        resistance = 1.0
        if self.fructosamin > 285:
            resistance *= 1.10 # +10% base resistance from metabolic memory
        
        if self.is_inflamed:
            resistance *= 1.15 # +15% resistance from LEU/infection stress
            
        # 2. Circadian Logic (24h Multiplicative Oscillation)
        hour_pos = (timestamp.hour + timestamp.minute / 60.0) / 24.0
        circadian_mult = 1.0 + 0.05 * np.sin(2 * np.pi * (hour_pos - 0.375)) 
        resistance *= circadian_mult
        
        # 3. Macro-Cycle Logic
        if self.gender == "FEMALE":
            days_since = (timestamp - self.cycle_start).total_seconds() / (3600 * 24)
            cycle_pos = (2 * np.pi * (days_since % mc.MENSTRUAL_CYCLE_DAYS) / mc.MENSTRUAL_CYCLE_DAYS)
            luteal_factor = 0.5 * (1 + np.sin(cycle_pos - np.pi/2))
            resistance *= (1.0 + (mc.LUTEAL_RESISTANCE_MULT - 1.0) * luteal_factor)
            
        # 4. Behavioral Ground Truth (Schedule Overrides)
        event = schedule_manager.get_event_at(timestamp)
        if event:
            resistance *= event.sensitivity_mult

        return np.clip(resistance, 0.7, 1.5)

    def get_iob_fraction(self, minutes_ago: float, insulin_type: str = "RAPID") -> float:
        if minutes_ago < 0:
            return 1.0

        params = {
            "RAPID": dict(tau1=44, tau2=133, w=0.5, onset=mc.INSULIN_ONSET_LAG_MINS),
            "LONG":  dict(tau1=540, tau2=1200, w=0.7, onset=120),
        }
        p = params.get(insulin_type.upper(), params["RAPID"])

        action_window = mc.INSULIN_ACTION_WINDOW_MINS if insulin_type == "RAPID" else mc.BASAL_DURATION_HOURS * 60
        if minutes_ago >= action_window:
            return 0.0

        raw = p["w"] * np.exp(-minutes_ago / p["tau1"]) + \
              (1 - p["w"]) * np.exp(-minutes_ago / p["tau2"])
        
        # Match the onset ramp from simulate_insulin_impact
        onset_ramp = 1.0 / (1.0 + np.exp(-(minutes_ago - p["onset"]) / 3.0))
        
        return float(np.clip(raw * onset_ramp, 0.0, 1.0))

    def get_environmental_multiplier(self, env: Optional[MetabolicSnapshot]) -> float:
        """
        Calculates Layer 2 forcing: How weather and air quality shift ISF/CSF.
        """
        if not env or not env.environment:
            return 1.0
        
        e = env.environment
        mult = 1.0
        
        # [L2] Temperature Factor (Q10 rule)
        # For every 10C deviation from 25C, metabolic rate shifts by ~5%
        temp_delta = (e.temperature - 25.0) / 10.0
        mult *= (1.0 + (temp_delta * 0.05))
        
        # [L2] Air Quality Damping
        # High AQI (pollution) reduces insulin sensitivity by inflammatory stress
        if e.aqi > 100:
            mult *= (1.0 - (e.aqi - 100) * 0.0002)
            
        # [L2] Humidity Friction (Heat Stress)
        if e.humidity > 85.0 and e.temperature > 28.0:
            mult *= 1.05
            
        # [L2] Exposure Awareness (Indoor/Outdoor Damping)
        if not e.is_outdoor:
            forcing = mult - 1.0
            mult = 1.0 + (forcing * mc.ENVIRONMENT_INDOOR_DAMPING)
            
        return np.clip(mult, 0.7, 1.4)

# =============================================================================
# 🧪 [PHARMACODYNAMIC ENGINE]
# =Focus: Carb Absorption (GI-Tuning) and Insulin Depletion (PK/PD)
# =============================================================================
    def simulate_carb_impact(self,
                             carbs_g: float, gi_type: str = "STARCH", 
                            resolution_mins: Optional[float] = None,
                            stochastic: bool = False,
                            snapshot: Optional[MetabolicSnapshot] = None,
                            csf_override: Optional[float] = None) -> np.ndarray:
        if resolution_mins is None:
            resolution_mins = mc.SAMPLING_INTERVAL_MINS
        
        tau = self.tau_table.get(gi_type.upper(), self.tau_table["STARCH"])
        
        timestamp = snapshot.glucose.timestamp if snapshot else None
        hormonal_mult = self.get_hormonal_multiplier(timestamp) if timestamp else 1.0
        env_mult = self.get_environmental_multiplier(snapshot) if snapshot else 1.0

        if stochastic:
            tau *= np.random.uniform(0.8, 1.2)
            carbs_g *= np.random.uniform(0.85, 1.15)

        t = np.arange(0, 240 + resolution_mins, resolution_mins)
        x = t / tau
        impact = 1.0 - (1.0 + x) * np.exp(-x) 
        
        csf = csf_override if csf_override is not None else self.csf
        total_rise = carbs_g * csf * self.regime_multiplier * hormonal_mult * env_mult
        curve = impact * total_rise
        return curve

    def simulate_insulin_impact(self, units: float, insulin_type: str = "RAPID",
                                resolution_mins: Optional[float] = None,
                                stochastic: bool = False,
                                snapshot: Optional[MetabolicSnapshot] = None,
                                isf_override: Optional[float] = None) -> np.ndarray:
        if resolution_mins is None:
            resolution_mins = mc.SAMPLING_INTERVAL_MINS
        
        timestamp = snapshot.glucose.timestamp if snapshot else None
        hormonal_mult = self.get_hormonal_multiplier(timestamp) if timestamp else 1.0
        env_mult = self.get_environmental_multiplier(snapshot) if snapshot else 1.0
        
        isf = isf_override if isf_override is not None else self.isf
        effective_isf = isf / (hormonal_mult * env_mult)

        duration = mc.INSULIN_ACTION_WINDOW_MINS if insulin_type.upper() == "RAPID" else mc.BASAL_DURATION_HOURS * 60
        t = np.arange(0, duration + resolution_mins, resolution_mins)

        if insulin_type.upper() == "LONG":
            total_drop = units * effective_isf
            drop_per_min = total_drop / duration
            curve = np.full_like(t, drop_per_min * resolution_mins, dtype=float)
            return np.cumsum(curve)

        # 2-Compartment biexponential distribution
        tau1 = 44.0
        tau2 = 133.0
        w = 0.5
        onset = mc.INSULIN_ONSET_LAG_MINS

        if stochastic:
            tau1 *= np.random.uniform(0.9, 1.1)
            tau2 *= np.random.uniform(0.9, 1.1)
            onset *= np.random.uniform(0.8, 1.5)
            units *= np.random.uniform(0.95, 1.05)

        iob_fraction = w * np.exp(-t / tau1) + (1 - w) * np.exp(-t / tau2)
        iob_fraction = np.clip(iob_fraction, 0.0, 1.0)
        
        differential_impact = -np.diff(iob_fraction, prepend=1.0)
        onset_ramp = 1.0 / (1.0 + np.exp(-(t - onset) / 3.0))
        
        total_drop = units * effective_isf * self.regime_multiplier
        curve = differential_impact * onset_ramp * total_drop
        return curve

# =============================================================================
# 🔮 [TRAJECTORY PREDICTION]
# =Focus: 4-Hour Forward Projections and Monte Carlo Confidence Ranges
# =============================================================================
    def predict_4h_trajectory(self, history: List[MetabolicSnapshot],
                              meals: Optional[List[MealEvent]] = None,
                              insulin_doses: Optional[List[InsulinDose]] = None,
                              basal_drift: Optional[np.ndarray] = None,
                              csf_override: Optional[float] = None,
                              isf_override: Optional[float] = None) -> np.ndarray:
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
                if dt_meal_mins < 0 or dt_meal_mins > 1440 or dt_meal_mins > 240.0: continue

                full_meal_curve = self.simulate_carb_impact(meal.carbs, meal.gi_type, snapshot=latest, csf_override=csf_override)
                start_idx = int(dt_meal_mins // dt)
                meal_projection = full_meal_curve[start_idx : start_idx + len(t)]
                
                if len(meal_projection) < len(t):
                    meal_projection = np.pad(meal_projection, (0, len(t) - len(meal_projection)))
                base_curve += meal_projection

        if insulin_doses:
            for dose in insulin_doses:
                if dose.units <= 0: continue
                dt_insulin_mins = (latest.glucose.timestamp - dose.timestamp).total_seconds() / 60.0
                action_window = mc.INSULIN_ACTION_WINDOW_MINS if dose.type.upper() == "RAPID" else mc.BASAL_DURATION_HOURS * 60
                if dt_insulin_mins > action_window: continue

                full_insulin_curve = self.simulate_insulin_impact(dose.units, dose.type, snapshot=latest, isf_override=isf_override)
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
                            N: int = 100) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        if not history:
            pts = int(240 / mc.SAMPLING_INTERVAL_MINS) + 1
            return np.zeros(pts), np.zeros(pts), np.zeros(pts)

        all_sims = []
        for _ in range(N):
            local_isf = self.isf * np.random.uniform(0.85, 1.15)
            local_csf = self.csf * np.random.uniform(0.9, 1.1)
            traj = self.predict_4h_trajectory(history, meals, insulin, basal_drift, 
                                            csf_override=local_csf, isf_override=local_isf)
            all_sims.append(traj)

        stack = np.vstack(all_sims)
        p5_traj   = np.percentile(stack, 5, axis=0)
        p50_traj  = np.percentile(stack, 50, axis=0)
        p95_traj  = np.percentile(stack, 95, axis=0)

        pts_60 = int(60 / mc.SAMPLING_INTERVAL_MINS) + 1
        return p5_traj[:pts_60], p50_traj[:pts_60], p95_traj[:pts_60]

# =============================================================================
# 🛠️ [METABOLIC TUNING]
# =Focus: Adaptive Gain, Self-Correction, and Regime Inference
# =============================================================================
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
        
        latest_ts = history[-1].glucose.timestamp
        horizon_24h = latest_ts - timedelta(hours=24)
        
        history_24h = [s.filtered_value for s in history if s.glucose.timestamp >= horizon_24h]
        if not history_24h:
            return "NORMAL"
            
        long_avg = np.mean(history_24h)
        
        if recent_avg > long_avg * 1.15:
            self.regime_multiplier = mc.REGIME_SENSITIVITY_MULT
            return "HIGH_RESISTANCE"
        self.regime_multiplier = 1.0
        return "NORMAL"
