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
MMOL_TO_MGDL = 18.018
MGDL_TO_MMOL = 1 / 18.018

# ── Glucose thresholds (mmol/L) ───────────────────────────────────────────────
# Source [2] — Battelino 2019, Table 1. International consensus targets.
HYPO_CRITICAL    = 3.1    # <56 mg/dL  — EMERGENCY, impaired cognition     # FIXED: was "<55 mg/dL"; 3.1×18.018=55.9
HYPO_WARNING     = 3.9    # <70 mg/dL  — WARNING, intervention needed
HYPER_CRITICAL   = 19.4   # >350 mg/dL — CRITICAL, ketoacidosis risk
FAINT_GLUCOSE    = 16.7   # >300 mg/dL — faint risk threshold
PHYSIO_FLOOR     = 2.2    # ~40 mg/dL  — absolute survivable minimum

# ── Rate of change (mmol/L per 5-min CGM interval) ───────────────────────────
# FIXED: unit base changed from "/min" to "/5-min interval" throughout this
# section to match CGM sampling reality and inline comments.
# Source [4] — Sparacino 2007, physiological glucose dynamics.

# Rapid upward climb threshold for faint risk assessment.
# NOTE: 0.5 mmol/L per 5-min interval is still supra-physiological
# (~0.1/min max in literature). This constant functions as an artifact
# discriminator for upward sensor spikes, NOT a physiological faint trigger.
# Rename the downstream check if the intent is artifact detection only.
FAINT_VELOCITY_PER_5MIN    = 0.5   # mmol/L per 5-min interval — artifact-level climb
FAINT_VELOCITY             = FAINT_VELOCITY_PER_5MIN  # ADDED: deprecated alias — remove after consumers updated

# Drop >2.0 mmol/L in one 5-min interval = compression artifact
COMPRESSION_DROP_LIMIT_PER_5MIN = 2.0
COMPRESSION_DROP_LIMIT          = COMPRESSION_DROP_LIMIT_PER_5MIN  # ADDED: deprecated alias

# Max biological drop per 5-min interval without overdose event.
# Basis: ~1.5 mmol/L per 5-min observed ceiling in insulin overdose literature
# (source not yet formally cited — add reference before production).
PHYSIO_MAX_DROP_PER_5MIN   = 1.5   # mmol/L per 5-min interval             # FIXED: was /min; renamed for clarity
PHYSIO_MAX_DROP            = PHYSIO_MAX_DROP_PER_5MIN  # ADDED: deprecated alias

# ── Kalman filter ─────────────────────────────────────────────────────────────
# Source [3] — Ottai M8 absolute accuracy ±0.5–0.8 mmol/L.              # FIXED: was "MARD" — MARD is unitless %; this is absolute error
# R = σ² = 0.5² = 0.25 mmol²/L² (uses lower bound — optimistic assumption).
# If sensor operates near 0.8 mmol/L end, true R ≈ 0.64. Treat as tunable.
KALMAN_MEASUREMENT_NOISE = 0.25

# ── DSP and timing ────────────────────────────────────────────────────────────
SAMPLING_INTERVAL_MINS   = 5.0
STALE_DATA_TIMEOUT_SECS  = 900    # 15 minutes — beyond this, data is unreliable

# ── Signal quality (per 5-min CGM interval) ──────────────────────────────────
# Derived from mizhtam Jun 2025 data — per-5min absolute changes avg 0.08-0.30.
# 0.5 fires only on genuinely chaotic movement, not normal physiological variance.
HIGH_VOLATILITY_PER_5MIN = 0.5    # mmol/L per 5-min interval              # FIXED: renamed from HIGH_VOLATILITY_MMOL; unit now explicit
HIGH_VOLATILITY_MMOL     = HIGH_VOLATILITY_PER_5MIN  # ADDED: deprecated alias
EMA_RESIDUAL_SPAN        = 6      # 6 readings × 5min = 30min EMA window

# ── Pharmacokinetics (Starting Seeds for Personalization) ────────────────────
INSULIN_HALFLIFE_MINS     = 45.0  # rapid-acting analogue baseline
CARB_ABS_LIQUID_TAU       = 15.0  # Fast-GI absorption peak (mins)
CARB_ABS_STARCH_TAU       = 60.0  # Slow-GI absorption peak (mins)

# ── Regime Detection & Hormonal Cycles ────────────────────────────────────────
REGIME_SENSITIVITY_MULT   = 1.25  # +25% resistance during Luteal Phase/Dawn Phenom
CARB_SENSITIVITY_DEFAULT  = 0.16  # approx 1g = 0.16 mmol/L rise (≈2.9 mg/dL)
# 🚦 Dynamic Damping (Renal Clearance Logic)
RENAL_THRESHOLD           = 10.0  # mmol/L — point where glucose reabsorption saturates
RENAL_CLEARANCE_SLOPE     = 0.025 # 2.5% brake per mmol/L over threshold
METABOLIC_BRAKE_FLOOR     = 0.70  # Maximum 30% reduction in predicted rise
