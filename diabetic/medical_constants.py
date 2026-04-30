"""
Centralized medical thresholds and constants for the Metabolic Engine.
Organized by the 5-Layer Metabolic Intelligence Specification.

Sections:
1. Layer 1: The Bio-Basal Vessel (Hardware & Vital Thresholds)
2. Layer 2: The Adaptive Regimes (Climatology & Biological Cycles)
3. Layer 3: The Behavioral Engine (Agency & Pharmacodynamics)
4. Layer 4: The Meta-Correction Layer (Self-Awareness)
5. Layer 5: The Interaction Layer (Interface & User Logic)
"""

# =============================================================================
# 🏗️ [LAYER 1: THE BIO-BASAL VESSEL]
# =Focus: Static Physiology, Hardware Sampling, and Critical Thresholds
# =============================================================================

# ── Unit Conversion ──────────────────────────────────────────────────────────
MMOL_TO_MGDL = 18.018                      # exact SI factor
MGDL_TO_MMOL = 1 / 18.018

# ── Hardware & Sampling ──────────────────────────────────────────────────────
SAMPLING_INTERVAL_MINS   = 5
STALE_DATA_TIMEOUT_SECS  = 3600    # 60 minutes — beyond this, data is unreliable, harder to predict
KALMAN_MEASUREMENT_NOISE = 0.25   # R = σ² = 0.5² (Ottai M8 base accuracy)
MIN_DT_FLOOR             = 0.5    # minutes — prevents division by zero / filter explosion

# ── Cardiac Telemetry (HR & HRV) ─────────────────────────────────────────────
# Source: Clinical telemetry defaults for T1D activity detection.
CARDIAC_WINDOW_SAMPLES  = 12      # 1 hour window at 5 min sampling
CARDIAC_QUALITY_DIVISOR = 4.0     # Threshold for signal-to-noise validation
BPM_MOCK_CEILING        = 120.0   # Upper bound for internal logic testing
BPM_MOCK_FLOOR          = 60.0    # Lower bound for internal logic testing
HRV_MOCK_CEILING        = 80.0
HRV_MOCK_FLOOR          = 20.0

# ── Glucose Thresholds (mmol/L) ──────────────────────────────────────────────
# Source: Battelino 2019, Table 1. International consensus targets.
PHYSIO_FLOOR     = 2.2    # ~40 mg/dL  — absolute survivable minimum
HYPO_CRITICAL    = 2.5    # <56 mg/dL  — EMERGENCY, impaired cognition
HYPO_WARNING     = 3.9    # <70 mg/dL  — WARNING, intervention needed
HYPER_CRITICAL   = 14.0   # ~288 mg/dL — CRITICAL, ketoacidosis risk
FAINT_GLUCOSE    = 20.0   # ~396 mg/dL — faint risk threshold
TOP_TARGET       = 8.4    # Ideal clinical midpoint

# ── Fatal Limits (Rate of Change) ────────────────────────────────────────────
# Normalized to mmol/L per Minute.
FAINT_VELOCITY_LIMIT_PER_MIN    = 0.1    # ~0.5 per 5m
PHYSIO_MAX_DROP_PER_MIN         = 0.3    # ~1.5 per 5m

FAINT_VELOCITY         = FAINT_VELOCITY_LIMIT_PER_MIN
PHYSIO_MAX_DROP        = PHYSIO_MAX_DROP_PER_MIN

# ── Kovatchev Risk Space (Source [1]) ────────────────────────────────────────
KOVATCHEV_OFFSET    = 5.381
KOVATCHEV_PRE_MULT  = 1.509
KOVATCHEV_EXP       = 1.084
KOVATCHEV_RISK_MULT = 10.0
KOVATCHEV_FLOOR_MGDL = 20.0
KOVATCHEV_CEIL_MGDL  = 600.0

# =============================================================================
# 🌊 [LAYER 2: THE ADAPTIVE REGIMES]
# =Focus: Climatology, Hormonal Cycles, and Temporal Intelligence
# =============================================================================

# ── Environmental Forcing (Climatology) ──────────────────────────────────────
DEFAULT_LATITUDE  = 21.0285  # Hanoi baseline for solar/circadian syncing
DEFAULT_LONGITUDE = 105.8542

# Magic numbers extracted from Digital Twin (Wave 7)
ENVIRONMENT_TEMP_BASELINE       = 22.0 # °C
ENVIRONMENT_Q10_COEFFICIENT     = 0.20 # +20% sensitivity per 10°C rise
ENVIRONMENT_AQI_BASELINE        = 15.0 # WHO PM2.5 baseline (µg/m³)
ENVIRONMENT_POLLUTION_RESISTANCE = 0.03 # +3% resistance per 10µg/m³ rise
ENVIRONMENT_INDOOR_DAMPING      = 0.30 # 70% reduction in external forcing when indoors

# ── Hormonal & Circadian Waves ──────────────────────────────────────────────
MENSTRUAL_CYCLE_DAYS     = 28.0  # standard baseline
LUTEAL_RESISTANCE_MULT   = 1.30  # +30% resistance peak during luteal phase
REGIME_SENSITIVITY_MULT  = 1.25  # +25% resistance during sick/dawn phenomenon

# ── Temporal Intelligence (Layer 2) ──────────────────────────────────────────
WEEKEND_RESISTANCE_MULT  = 1.05  # +5% resistance context(placeholder for now)
HOLIDAY_RESISTANCE_MULT  = 1.10  # +10% resistance context
FESTIVAL_RESISTANCE_MULT = 1.20  # +20% resistance context (e.g. Tet, Social Eating)

# ── Metabolic Braking (Spillover & Defense) ──────────────────────────────────
# RENAL_THRESHOLD: above this, kidneys spill glucose into urine.
RENAL_THRESHOLD       = 12.0   # mmol/L
RENAL_CLEARANCE_SLOPE = 0.025  # 2.5% brake per mmol/L over threshold
METABOLIC_BRAKE_FLOOR = 0.70   # maximum 30% reduction

# COUNTER-REGULATION: defensive defense slowing rate of decline.
LOW_SIDE_THRESHOLD    = 3.9    # mmol/L
LOW_SIDE_BRAKE_SLOPE  = 0.25   # damping aggressive drops

# =============================================================================
# 🎮 [LAYER 3: THE BEHAVIORAL ENGINE]
# =Focus: Pharmacodynamics, User Agency, and Activity Context
# =============================================================================

# ── Sensitivity Defaults (Seeds for auto-tuning) ─────────────────────────────
INSULIN_SENSITIVITY_DEFAULT = 2.0     # mmol/L drop per 1 Unit
CARB_SENSITIVITY_DEFAULT    = 0.16    # mmol/L rise per 1g Carb

# ── Pharmacokinetics (PK) ────────────────────────────────────────────────────
INSULIN_HALFLIFE_MINS = 45.0
CARB_ABS_LIQUID_TAU   = 15.0   # Fast-GI peak
CARB_ABS_STARCH_TAU   = 60.0   # Slow-GI peak
MEAL_WINDOW_MINS      = 240.0  # Digestion observation window

# ── Pharmacodynamics (PD) ────────────────────────────────────────────────────
INSULIN_ACTION_WINDOW_MINS  = 240.0   # 4 hours total
INSULIN_PEAK_TAU_RAPID      = 55.0    # peak activity
INSULIN_ONSET_LAG_MINS      = 15.0    # onset lag
BASAL_DURATION_HOURS        = 24.0

# ── Activity & Context Classifier ────────────────────────────────────────────
BPM_EXERCISE_THRESHOLD  = 110
BPM_STRESS_THRESHOLD    = 85
BPM_SLEEP_CEILING       = 65
HRV_STRESS_CEILING      = 30
HRV_SLEEP_FLOOR         = 60

# =============================================================================
# 🔬 [LAYER 4: THE META-CORRECTION LAYER]
# =Focus: Systemic Error, Signal Integrity, and Forecast Auditing
# =============================================================================

# ── Projection Parameters ────────────────────────────────────────────────────
KINEMATIC_DECAY_MINS = 90.0   # timescale for momentum exhaustion
MAX_RESIDUAL_ERROR_MMOL = 1.5  # Tolerable 30m drift before confidence drop

# ── Signal Integrity & Integrity ─────────────────────────────────────────────
SIGNAL_QUALITY_DIVISOR = 50.0  # volatility scale factor
COMPRESSION_DROP_LIMIT_PER_MIN = 0.4 # mmol/L per min (~2.0 per 5m)
COMPRESSION_DROP_LIMIT = COMPRESSION_DROP_LIMIT_PER_MIN
COMPRESSION_RECOVERY_MIN = 1.0 # mmol/L bounce-back confirm
EMA_RESIDUAL_SPAN        = 6   # window for stability analysis

# ── Buffer Management ────────────────────────────────────────────────────────
REGIME_MIN_SNAPSHOTS = 200      # minimum for detection
SNAPSHOT_CAP         = 500      # ring buffer cap
BACKFILL_DAYS_LIMIT  = 180      # System-wide limit for historical data retrieval

# =============================================================================
# 📱 [LAYER 5: THE INTERACTION LAYER]
# =Focus: User Logic, Alert Interface, and Personalized Calibration
# =============================================================================

ALERT_RETRY_MINS        = 15.0 # Delay between repeated critical alerts
FALSE_ALARM_DEBOUNCE    = 30.0 # Suppression window after "False Alarm" label
MAX_CONFIDENCE_BIAS     = 0.20 # +/- 20% shift based on RLHF feedback

# ── Audit Hardening (Plan 1.4) ────────────────────────────────────────────────
BPM_EXERCISE_MULTIPLIER = 1.4   # threshold multiplier for active context detection
SIGNAL_MIN_HISTORY      = 3     # minimum readings before compression check is meaningful
PALACE_ANOMALY_GLUCOSE  = 16.0  # mmol/L threshold for semantic memory indexing
PALACE_ANOMALY_BPM      = 110   # BPM threshold for semantic memory indexing
