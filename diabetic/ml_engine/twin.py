import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional
from diabetic.registry import MealEvent, InsulinDose, MetabolicSnapshot
from diabetic import medical_constants as mc
from diabetic.utils.temporal import temporal_engine
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
        
        self.liquid_tau = mc.CARB_ABS_LIQUID_TAU
        self.starch_tau = mc.CARB_ABS_STARCH_TAU
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
            
        # 4. Temporal Intelligence (Weekends/Holidays)
        resistance *= temporal_engine.get_multiplier(timestamp)
        
        # 5. Behavioral Ground Truth (Schedule Overrides)
        event = schedule_manager.get_event_at(timestamp)
        if event:
            resistance *= event.sensitivity_mult

        return np.clip(resistance, 0.7, 1.5)

    def get_iob_fraction(self, minutes_ago: float) -> float:
        """
        [L1] Calculates remaining Insulin On Board fraction using a biexponential
        pharmacological decay model (Bergman rapid-acting insulin kinetics).

        Model: IOB(t) = A * exp(-t/tau1) - B * exp(-t/tau2)
        
        Calibrated to a clinical Rapid-Acting insulin profile:
          - Onset: ~10-15 min
          - Peak activity: ~60-75 min
          - Duration: ~240 min (mc.INSULIN_ACTION_WINDOW_MINS)
        """
        if minutes_ago < 0:
            return 1.0
        if minutes_ago >= mc.INSULIN_ACTION_WINDOW_MINS:
            return 0.0

        # [L1] 2-compartment pharmacokinetic decay model (Sum of Exponentials)
        # Calibrated for Novorapid/Humalog (~4h duration)
        tau1 = mc.INSULIN_PEAK_TAU_RAPID * 0.8  # fast redistribution (~44 min)
        tau2 = mc.INSULIN_ACTION_WINDOW_MINS / 1.8 # slow elimination (~133 min)
        w = 0.4 # redistribution weight
        
        raw = w * np.exp(-minutes_ago / tau1) + (1 - w) * np.exp(-minutes_ago / tau2)
        return float(np.clip(raw, 0.0, 1.0))

    def get_environmental_multiplier(self, env: Optional[MetabolicSnapshot]) -> float:
        """
        Calculates Layer 2 forcing: How weather and air quality shift ISF/CSF.
        Formula: Baseline (1.0) + (Heat Shift) + (Pollution Shift)
        """
        if not env or not env.environment:
            return 1.0
        
        e = env.environment
        multiplier = 1.0
        
        # 1. Heat-Induced Absorption Shift (ISF up / Resistance down)
        # Baseline: mc.ENVIRONMENT_TEMP_BASELINE. +10°C -> mc.ENVIRONMENT_Q10_COEFFICIENT boost
        if e.temperature > mc.ENVIRONMENT_TEMP_BASELINE:
            heat_delta = e.temperature - mc.ENVIRONMENT_TEMP_BASELINE
            absorption_boost = (heat_delta / 10.0) * mc.ENVIRONMENT_Q10_COEFFICIENT
            multiplier -= absorption_boost # Less resistance
            
        # 2. Pollution-Induced Inflammation (AQI/PM2.5)
        # WHO baseline: mc.ENVIRONMENT_AQI_BASELINE. 
        # Every 10µg/m³ above increases resistance by mc.ENVIRONMENT_POLLUTION_RESISTANCE
        if e.aqi and e.aqi > mc.ENVIRONMENT_AQI_BASELINE:
            aqi_delta = e.aqi - mc.ENVIRONMENT_AQI_BASELINE
            pollution_resistance = (aqi_delta / 10.0) * mc.ENVIRONMENT_POLLUTION_RESISTANCE
            multiplier += pollution_resistance
            
        # 3. Humidity Friction (Heat Stress)
        if e.humidity > 85.0 and e.temperature > 28.0:
            multiplier += 0.05 # +5% fixed penalty for high heat index stress, why 5%
            
        # 4. Exposure Awareness (Indoor/Outdoor Damping)
        if not e.is_outdoor:
            # If indoors, reduce the entire environmental forcing (forcing = multiplier - 1.0)
            forcing = multiplier - 1.0
            multiplier = 1.0 + (forcing * mc.ENVIRONMENT_INDOOR_DAMPING)
            
        return np.clip(multiplier, 0.7, 1.4)

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
        tau = self.liquid_tau if gi_type.upper() == "LIQUID" else self.starch_tau
        
        timestamp = snapshot.glucose.timestamp if snapshot else None
        hormonal_mult = self.get_hormonal_multiplier(timestamp) if timestamp else 1.0
        env_mult = self.get_environmental_multiplier(snapshot) if snapshot else 1.0

        if stochastic:
            tau *= np.random.uniform(0.8, 1.2)
            carbs_g *= np.random.uniform(0.85, 1.15)

        t = np.arange(0, 240 + resolution_mins, resolution_mins)
        # Integral of (t/tau)*exp(1-t/tau) is used to create a persistent S-curve (Cumulative Appearance)
        # Formula: 1 - (1 + t/tau)*exp(-t/tau) * e^1
        x = t / tau
        # Normalize so that at infinity it reaches 1.0
        # The integral of x*e^(1-x) from 0 to inf is e. So we divide by e.
        impact = 1.0 - (1.0 + x) * np.exp(-x) 
        
        # Layer 2 & 3 Synthesis: Behavior * (Physiological + Environmental state)
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

        duration = mc.INSULIN_ACTION_WINDOW_MINS
        t = np.arange(0, duration + resolution_mins, resolution_mins)

        if insulin_type.upper() == "LONG":
            total_drop = units * effective_isf
            drop_per_min = total_drop / (mc.BASAL_DURATION_HOURS * 60.0)
            curve = np.full_like(t, drop_per_min * resolution_mins, dtype=float)
            return np.cumsum(curve)

        # 2-Compartment biexponential distribution (Fast redistribution + Slow elimination)
        tau1 = mc.INSULIN_PEAK_TAU_RAPID * 0.8  # ~44 mins
        tau2 = mc.INSULIN_ACTION_WINDOW_MINS / 1.8 # ~133 mins
        w = 0.4 # Weight of fast compartment

        onset = mc.INSULIN_ONSET_LAG_MINS

        if stochastic:
            tau1 *= np.random.uniform(0.9, 1.1)
            tau2 *= np.random.uniform(0.9, 1.1)
            onset *= np.random.uniform(0.8, 1.5)
            units *= np.random.uniform(0.95, 1.05)

        # Calculate remaining IOB at each time step `t`
        iob_fraction = w * np.exp(-t / tau1) + (1 - w) * np.exp(-t / tau2)
        iob_fraction = np.clip(iob_fraction, 0.0, 1.0)
        
        # The impact curve is the rate of *change* in IOB
        differential_impact = -np.diff(iob_fraction, prepend=1.0)
        
        # Apply onset lag ramp
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
                # [L2] Guard: skip future-dated meals (clock drift or TWA pre-log)
                # Without this, `max(0, negative // dt)` = 0, injecting a peak at t=0
                if dt_meal_mins < 0:
                    continue
                # Guard: skip zombie meals older than 24h (stale Nightscout entries)
                if dt_meal_mins > 1440:
                    continue
                if dt_meal_mins > 240.0: continue

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
                if dt_insulin_mins > mc.INSULIN_ACTION_WINDOW_MINS: continue

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
            
            # Note: liquid_tau/starch_tau stochasticity is handled inside simulate_carb_impact 
            # if we passed stochastic=True. For now we use the stateless override pattern.
            traj = self.predict_4h_trajectory(history, meals, insulin, basal_drift, 
                                            csf_override=local_csf, isf_override=local_isf)
            all_sims.append(traj)

        stack = np.vstack(all_sims)
        p5_traj   = np.percentile(stack, 5, axis=0)
        p50_traj  = np.percentile(stack, 50, axis=0)
        p95_traj  = np.percentile(stack, 95, axis=0)

        # Slice to 60 minutes (12 points at 5 min intervals + 1 for current state)
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
        
        # [L4] Dynamic 24-hour horizon instead of unbounded full-history
        latest_ts = history[-1].glucose.timestamp
        horizon_24h = latest_ts - timedelta(hours=24)
        
        # Filter for the last 24 hours
        history_24h = [s.filtered_value for s in history if s.glucose.timestamp >= horizon_24h]
        if not history_24h:
            return "NORMAL"
            
        long_avg = np.mean(history_24h)
        
        if recent_avg > long_avg * 1.15:
            self.regime_multiplier = mc.REGIME_SENSITIVITY_MULT
            return "HIGH_RESISTANCE"
        self.regime_multiplier = 1.0
        return "NORMAL"