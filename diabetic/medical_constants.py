"""
Centralized medical thresholds and constants for the Metabolic Engine.
Ensures consistency across dsp, ml_engine, and decision_matrix.

Sources:
[1] Kovatchev et al. (2006) - LBGI/HBGI risk indices, UVA
[2] Battelino et al. (2019) - Clinical targets for CGM, Diabetes Care
[3] Ottai M8 product specification - sensor absolute accuracy ±0.5-0.8 mmol/L
[4] Sparacino et al. (2007) - Kalman-based CGM prediction
[5] Mhaskar et al. (2017) - Circadian features in T1 prediction
"""

# ── Kovatchev Risk Space Constants ───────────────────────────────────────────
# Source [1] — tuned for mg/dL input
KOVATCHEV_OFFSET    = 5.381
KOVATCHEV_PRE_MULT  = 1.509
KOVATCHEV_EXP       = 1.084
KOVATCHEV_RISK_MULT = 10.0
KOVATCHEV_FLOOR_MGDL = 20.0   # Required for log stability
KOVATCHEV_CEIL_MGDL  = 600.0  # Sensor saturation limit

# ── Unit conversion ───────────────────────────────────────────────────────────
MMOL_TO_MGDL = 18.018                      # exact SI factor
MGDL_TO_MMOL = 1 / 18.018

# ── Glucose thresholds (mmol/L) ───────────────────────────────────────────────
# Source [2] — Battelino 2019, Table 1. International consensus targets.
HYPO_CRITICAL    = 2.5    # <56 mg/dL  — EMERGENCY, impaired cognition     # FIXED: was "<55"; 3.1×18.018=55.9
HYPO_WARNING     = 3.9    # <70 mg/dL  — WARNING, intervention needed
HYPER_CRITICAL   = 14   # >350 mg/dL — CRITICAL, ketoacidosis risk
FAINT_GLUCOSE    = 17  # >300 mg/dL — faint risk threshold
PHYSIO_FLOOR     = 2.2    # ~40 mg/dL  — absolute survivable minimum

# ── Rate of change (Normalized to mmol/L per Minute) ─────────────────────────
# FIXED Wave 6: Unit base is now strictly per minute throughout the engine.
# This enables sampling-agnostic logic (Works for 2.5m, 3m, or 5m intervals).
# Source [4] — Sparacino 2007, normalized.

FAINT_VELOCITY_LIMIT_PER_MIN    = 0.1    # mmol/L per min (~0.5 per 5m)
COMPRESSION_DROP_LIMIT_PER_MIN  = 0.4    # mmol/L per min (~2.0 per 5m)
PHYSIO_MAX_DROP_PER_MIN         = 0.3    # mmol/L per min (~1.5 per 5m)

FAINT_VELOCITY         = FAINT_VELOCITY_LIMIT_PER_MIN
COMPRESSION_DROP_LIMIT = COMPRESSION_DROP_LIMIT_PER_MIN
PHYSIO_MAX_DROP        = PHYSIO_MAX_DROP_PER_MIN

# ── Biometric & Cardiac (Wave 4/5) ───────────────────────────────────────────
# Source: Literature review on RMSSD stability windows
CARDIAC_WINDOW_SAMPLES = 180   # ~120 seconds at 1Hz
CARDIAC_QUALITY_DIVISOR = 50.0 # volatility scale factor for signal quality
BPM_MOCK_CEILING       = 180
BPM_MOCK_FLOOR         = 45
HRV_MOCK_CEILING       = 120
HRV_MOCK_FLOOR         = 5

# ── Kalman filter ─────────────────────────────────────────────────────────────
# Source [3] — Ottai M8 absolute accuracy ±0.5–0.8 mmol/L.
# FIXED: "MARD" removed — MARD is a unitless %; this figure is absolute error.
# R = σ² = 0.5² = 0.25 mmol²/L² (lower-bound assumption — optimistic).
# If sensor operates near 0.8 mmol/L end, true R ≈ 0.64. Treat as tunable.
KALMAN_MEASUREMENT_NOISE = 0.25

# ── DSP and timing ────────────────────────────────────────────────────────────
SAMPLING_INTERVAL_MINS   = 2.5
STALE_DATA_TIMEOUT_SECS  = 900    # 15 minutes — beyond this, data is unreliable

# ── Signal quality (Normalized to Per Minute) ────────────────────────────────
# High volatility threshold normalized to per-minute rate.
HIGH_VOLATILITY_LIMIT_PER_MIN = 0.1    # mmol/L per minute (~0.5 per 5m)
EMA_RESIDUAL_SPAN        = 6      # 6 readings × 5min = 30min EMA window
COMPRESSION_RECOVERY_MIN = 1.0    # mmol/L — minimum bounce-back to confirm artifact
MIN_DT_FLOOR             = 0.5    # minutes — prevents division by zero / filter explosion

# ── Pharmacokinetics (Starting Seeds for Personalization) ────────────────────
# The Digital Twin auto-tunes these during the feedback loop.
INSULIN_HALFLIFE_MINS = 45.0    # rapid-acting analogue baseline
CARB_ABS_LIQUID_TAU   = 15.0   # Fast-GI absorption peak (mins)
CARB_ABS_STARCH_TAU   = 60.0   # Slow-GI absorption peak (mins)
MEAL_WINDOW_MINS   =240.0  # to prevent reading gli spike after meals

# ── Insulin Pharmacodynamics ─────────────────────────────────────────────────
# Source: Rapid-acting analogue (Novorapid/Humalog) population PK data.
# Long-acting (Lantus/Levemir) modelled as flat 24h distribution.
INSULIN_SENSITIVITY_DEFAULT = 2.0     # mmol/L drop per 1 Unit (ISF seed — auto-tuned)
INSULIN_ACTION_WINDOW_MINS  = 240.0   # 4 hours — total duration of rapid-acting insulin
INSULIN_PEAK_TAU_RAPID      = 55.0    # minutes — peak activity for rapid-acting
INSULIN_ONSET_LAG_MINS      = 15.0    # minutes — near-zero impact before this point
BASAL_DURATION_HOURS        = 24.0    # hours — long-acting insulin distribution window

# ── Context Classifier Thresholds ────────────────────────────────────────────
# Used by dsp/context_classifier.py to label metabolic snapshots.
# Source: General population HR/HRV ranges; treat as personalization seeds.
BPM_EXERCISE_THRESHOLD  = 110   # HR above this → EXERCISE
BPM_STRESS_THRESHOLD    = 85    # HR above this (but below exercise) → STRESS
BPM_SLEEP_CEILING       = 65    # HR below this → SLEEP candidate
HRV_STRESS_CEILING      = 30    # ms — HRV below this during elevated HR → stress confirmed
HRV_SLEEP_FLOOR         = 60    # ms — HRV above this during low HR → sleep confirmed

# ── Kinematic projection ──────────────────────────────────────────────────────
# Assumed timescale over which current glucose velocity linearly decays to zero
# in the Digital Twin 4-hour trajectory model.
# Basis: empirical — glucose momentum from a meal typically exhausts within
# 60-120 mins. 90 min is the midpoint assumption. Auto-tune candidate.
KINEMATIC_DECAY_MINS = 90.0

# ── Glucosuria Damping (long-horizon brake — NOT for per-reading prediction) ──
# RENAMED from "Renal Clearance Logic" to make timescale explicit.
#
# Mechanism: above the renal threshold, kidneys spill glucose into urine,
# reducing blood glucose over 1-4 hours depending on GFR and urine output.
# THIS BRAKE OPERATES ON A MULTI-HOUR TIMESCALE.
# Apply ONLY in long-horizon trajectory modelling (>=60 min lookahead).
# Do NOT apply it inside the 5-min prediction loop — it will compound
# per-reading and systematically under-predict hyperglycemic rises exactly
# when alert accuracy matters most.
#
# RENAL_THRESHOLD: population mean ~10.0 mmol/L (180 mg/dL).
# Long-standing diabetes may shift this to 11-12 mmol/L (hyperfiltration).
# Treat as personalization target for mizhtam; current value is a seed.
#
# RENAL_CLEARANCE_SLOPE: empirical tuning value, no direct literature source.
# Should be auto-tuned by Digital Twin, not held as a fixed constant.
#
# METABOLIC_BRAKE_FLOOR: floor engages at ~22 mmol/L, above HYPER_CRITICAL
# (19.4). In the 19.4-22.0 mmol/L critical zone, brake is still ramping
# (25%->30%). Under-predicting a rise here is more dangerous than over-predicting.
# Brake is disabled above HYPER_CRITICAL in predictor.py.
RENAL_THRESHOLD       = 10.0   # mmol/L — tubular reabsorption saturation (person-variable)
RENAL_CLEARANCE_SLOPE = 0.025  # empirical — 2.5% brake per mmol/L over threshold
METABOLIC_BRAKE_FLOOR = 0.70   # maximum 30% reduction; floor engages at ~22 mmol/L

# ── Counter-regulatory Braking (low-side diminishing returns) ────────────────
# Mechanism: at the onset of hypoglycemia, the body initiates a defense
# (glucagon/epinephrine) which slows the rate of glucose decline.
# Apply ONLY when velocity is negative (falling).
LOW_SIDE_THRESHOLD   = 3.9    # mmol/L — point where counter-regulation typically begins (seed)
LOW_SIDE_BRAKE_SLOPE = 0.25   # 25% brake per mmol/L below threshold (more aggressive damping)

# ── Regime Detection & Hormonal Cycles ────────────────────────────────────────
REGIME_SENSITIVITY_MULT  = 1.25  # +25% resistance during Luteal Phase / Dawn Phenomenon
CARB_SENSITIVITY_DEFAULT = 0.16  # approx 1g = 0.16 mmol/L rise (~2.9 mg/dL)

# ── Snapshot ring buffer sizing ───────────────────────────────────────────────
# detect_regime() requires REGIME_MIN_SNAPSHOTS to produce a result.
# SNAPSHOT_CAP must exceed REGIME_MIN_SNAPSHOTS or regime detection is
# permanently blocked. 288 readings/day at 5-min intervals.
# 200 readings = ~16.7 hours (minimum for regime comparison baseline).
# 300 readings = ~25 hours (cap — allows full prior-day comparison).
REGIME_MIN_SNAPSHOTS = 200      # minimum history for regime detection
SNAPSHOT_CAP         = 300      # ring buffer hard cap — must be > REGIME_MIN_SNAPSHOTS
# ── Context Classifier Thresholds (personalization seeds) ────────────────────
BPM_EXERCISE_THRESHOLD = 110   # bpm — above this = exercise territory
BPM_STRESS_THRESHOLD   = 85    # bpm — above this + low HRV = stress
BPM_SLEEP_CEILING      = 65    # bpm — below this = sleep territory
HRV_STRESS_CEILING     = 30    # ms  — below this = stress/exercise
HRV_SLEEP_FLOOR        = 60    # ms  — above this = sleep/recovery

