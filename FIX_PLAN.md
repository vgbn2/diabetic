# FIX_PLAN: Metabolic Engine & Safety Shield

This document outlines the systematic resolution of identified technical debt and safety logic flaws in the `hyperglycemia-faint-predictor` project.

## 1. Centralized Medical Constants
**Goal**: Remove all "magic numbers" and ensure a single source of truth for medical thresholds.
- **File**: `diabetic/medical_constants.py` [NEW]
- **Values**:
  - `MMOL_TO_MGDL = 18.018`
  - `HYPO_CRITICAL = 3.1`
  - `HYPO_WARNING = 3.9`
  - `HYPER_CRITICAL = 19.4`
  - `FAINT_GLUCOSE = 16.7`
  - `FAINT_VELOCITY = 0.5`
  - `PHYSIO_FLOOR = 2.2`
  - `SAMPLING_INTERVAL = 5.0`

## 2. Safety Shield (Decision Matrix)
**Goal**: Fix the Circuit Breaker "silence" bug and integrate cardiac data.
- **Circuit Breaker**: Add `EMERGENCY_BYPASS`. If `severity == EMERGENCY`, bypass the 15-minute cooldown.
- **Faint Risk**: Update `evaluate()` to check `PATIENT_HRV_BASELINE`. Increase risk score if `current.bpm > 100` or `current.hrv < 20`.

## 3. Prediction Engine (ML)
**Goal**: Replace the "Phantom" XGBoost fallback with a scientifically sound model.
- **File**: `diabetic/ml_engine/predictor.py`
- **Fix**: Implement a **Weighted Kinematic Predictor** (`G_now + Velocity * 30 * Deceleration_Factor`).

## 4. Stability & Production Readiness
**Goal**: Fix the "Silent Death" and concurrency race conditions.
- **Error Handling**: Update `start_live_mode` to raise `FatalConfigError` for invalid API secrets/URLs, forcing a process exit instead of infinite failing loops.
- **Kalman Tuning**: Update `GlucoseFilter` to include a "Sanity Check" (Mahalanobis distance or simple delta check) to prevent explosion from "Wild Sensor Readings" (e.g., 40.0 mmol/L).
- **Task Management**: Change fire-and-forget `asyncio.create_task` calls to use a background task manager (e.g., `asyncio.gather` on shutdown) to prevent memory leaks/piling.
- **Dawn Phenomenon**: Add a basic "Time of Day" awareness to `DecisionMatrix` to dampen Faint Risk alerts between 4 AM - 8 AM.

## 5. Architectural Cleanup
- **Config**: Move UI/Emoji strings to `config.py` as `UI_SETTINGS`.
- **Simulation**: Refactor `diabetic/main.py` simulation curves to use constants.
- **Dependencies**: Remove `groq` from `requirements.txt`.
- **Security**: Update Flask CORS to restrict origins to specific trusted domains (if UI exists).

## 6. Execution Order
1.  Create `medical_constants.py`.
2.  Update `config.py` with UI settings and physiological baselines.
3.  Refactor `MetabolicMath` and `Kalman` (add sanity checks).
4.  Implement `Emergency Bypass` and `Dawn Damping` in `DecisionMatrix`.
5.  Refactor `Forecaster` and `Coordinator` error handling.
6.  Final simulation verification (`crash`, `faint`, `normal`).

---
**Status**: [PLANNING]
**Approved**: [ ]
