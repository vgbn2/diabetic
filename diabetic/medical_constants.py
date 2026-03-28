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

# ── Unit conversion ───────────────────────────────────────────────────────────
MMOL_TO_MGDL = 18.018                      # exact SI factor
MGDL_TO_MMOL = 1 / 18.018

# ── Glucose thresholds (mmol/L) ───────────────────────────────────────────────
# Source [2] — Battelino 2019, Table 1. International consensus targets.
HYPO_CRITICAL    = 3.1    # <56 mg/dL  — EMERGENCY, impaired cognition     # FIXED: was "<55"; 3.1×18.018=55.9
HYPO_WARNING     = 3.9    # <70 mg/dL  — WARNING, intervention needed
HYPER_CRITICAL   = 19.4   # >350 mg/dL — CRITICAL, ketoacidosis risk
FAINT_GLUCOSE    = 16.7   # >300 mg/dL — faint risk threshold
PHYSIO_FLOOR     = 2.2    # ~40 mg/dL  — absolute survivable minimum

# ── Rate of change (mmol/L per 5-min CGM interval) ───────────────────────────
# FIXED: unit base is per 5-min interval throughout this section — not /min.
# All names carry _PER_5MIN suffix to prevent ambiguity at call sites.
# Source [4] — Sparacino 2007, physiological glucose dynamics.

# NOTE: 0.5 mmol/L per 5-min is supra-physiological (~0.1/min max in literature).
# These thresholds function as artifact discriminators, not physiological
# event detectors. Downstream checks should be named accordingly.
FAINT_VELOCITY_PER_5MIN         = 0.5    # mmol/L per 5-min — artifact-level upward spike
COMPRESSION_DROP_LIMIT_PER_5MIN = 2.0    # mmol/L per 5-min — artifact-level downward spike
PHYSIO_MAX_DROP_PER_5MIN        = 1.5    # mmol/L per 5-min — max biological drop (insulin overdose ceiling)
                                          # Basis: clinical observation; formal citation pending.

# Deprecated aliases — kept for backward compatibility.
# Remove after dsp.py, decision_matrix.py, ml_engine.py are updated.
FAINT_VELOCITY         = FAINT_VELOCITY_PER_5MIN
COMPRESSION_DROP_LIMIT = COMPRESSION_DROP_LIMIT_PER_5MIN
PHYSIO_MAX_DROP        = PHYSIO_MAX_DROP_PER_5MIN

# ── Kalman filter ─────────────────────────────────────────────────────────────
# Source [3] — Ottai M8 absolute accuracy ±0.5–0.8 mmol/L.
# FIXED: "MARD" removed — MARD is a unitless %; this figure is absolute error.
# R = σ² = 0.5² = 0.25 mmol²/L² (lower-bound assumption — optimistic).
# If sensor operates near 0.8 mmol/L end, true R ≈ 0.64. Treat as tunable.
KALMAN_MEASUREMENT_NOISE = 0.25

# ── DSP and timing ────────────────────────────────────────────────────────────
SAMPLING_INTERVAL_MINS   = 5.0
STALE_DATA_TIMEOUT_SECS  = 900    # 15 minutes — beyond this, data is unreliable

# ── Signal quality (per 5-min CGM interval) ──────────────────────────────────
# Derived from mizhtam Jun 2025 data — per-5min absolute changes avg 0.08-0.30.
# 0.5 fires only on genuinely chaotic movement, not normal physiological variance.
HIGH_VOLATILITY_PER_5MIN = 0.5    # mmol/L per 5-min interval
HIGH_VOLATILITY_MMOL     = HIGH_VOLATILITY_PER_5MIN  # deprecated alias
EMA_RESIDUAL_SPAN        = 6      # 6 readings × 5min = 30min EMA window

# ── Pharmacokinetics (Starting Seeds for Personalization) ────────────────────
# The Digital Twin auto-tunes these during the feedback loop.
INSULIN_HALFLIFE_MINS = 45.0    # rapid-acting analogue baseline
CARB_ABS_LIQUID_TAU   = 15.0   # Fast-GI absorption peak (mins)
CARB_ABS_STARCH_TAU   = 60.0   # Slow-GI absorption peak (mins)

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