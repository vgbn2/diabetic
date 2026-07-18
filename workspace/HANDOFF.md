# Handoff — Current Objectives

_Last updated: 2026-07-18_

## Current Phase
**Phase 5 complete. Deployment reproducibility hardening committed in `a8bd5f4`.**
The implementation passed clean committed-archive verification; Docker/Compose validation remains host-blocked.

## Last Verified State
- **Test baseline: `70 passed`** — isolated Python 3.11.15, `python -m pytest ops/lab -q` → 70 passed, 5.19s
- Pre-commit clean-HEAD candidate archive with the implementation overlay → 70 passed, 5.22s
- Committed `HEAD` archive → 70 passed, 5.70s
- v15 state dictionary loads with `weights_only=True`: 14 keys, no missing or unexpected keys
- Dependency environment: 130 packages installed; compatibility check passed
- `python -m diabetic.main health` → live JSON; MongoDB `ok`; weights 39 days stale
- `python -m diabetic.main simulation` → CNN fires from reading 31 onward (`NEURAL_BRAIN: Pred Glu=9.x`)
- Live data probe: 288 real readings from MongoDB; CNN active; oracle fit (A=2.39, φ=−1.70, C=8.36); 4h + 1d horizons populated
- Implementation commit: `a8bd5f4 fix(ml): make inference artifact contract reproducible`
- `run_graphify.py` and `.graphifyignore` remain untracked and intentionally untouched

## What Was Done This Session (2026-07-18)

### Deployment reproducibility mass-implement
- Added the configured `diabetic_cnn_v15.pth` artifact to the implementation batch
- Neural inference now fails closed when weights are missing or invalid; the kinematic fallback remains active
- Health output requires both a saturated buffer and successfully loaded weights before reporting `inference_active`
- Added `ops/lab/test_runtime_contract.py` for artifact and dependency-manifest contracts
- Declared direct runtime dependencies (`fastapi`, `uvicorn`, `psutil`) and test dependencies (`pytest`, `pytest-asyncio`)
- Added `.gitattributes` and removed CRLF-only working-tree noise; added ignores for local Claude settings and graph chunk lists
- Replaced stale README commands and Windows-only file links with verified Python 3.11 and Docker instructions
- Corrected the Docker-volume finding: empty named volumes copy image contents by default; the actual blocker was that committed source did not contain v15

## What Was Done This Session (2026-06-27)

### Blast-through full audit (commit anchor: e08a93e)
- Full line-by-line audit of all tracked + untracked code
- Live data probe: verified CNN fires on real MongoDB readings, oracle fits, horizons populate
- Found R9–R13 (see DEV_REVIEW.md); R11 was a false alarm (scheduler IS started in main.py)

### R9 — Committed all untracked Phase 5 work (4 commits)
- `diabetic/auth/`, `diabetic/cli/`, `diabetic/mcp/`, `forecast.py`, `health.py`
- `twa/login.html`, `twa/settings.html`, `twa/history.html`, `twa/assets/`
- All 8 Phase 5 test files (`ops/lab/test_*.py`)
- `workspace/`, `scripts/`, `diabetic.ps1`, `docs/engineering/`

### R10 — COORDINATOR_REF Docker gap fixed
- `main.py`: TWA API now starts as daemon thread in live mode (same process = same COORDINATOR_REF)
- `docker-compose.yml`: removed standalone `bio-quant-twa` service; port 8000 on `bio-quant-core`; dropped obsolete `version:` key

### R12 — train.py `weights_only=True`
- `train.py:154`: added `weights_only=True` to torch.load in anti-hallucination guard (consistent with inference.py)

### R13 — scheduler respects config
- `scheduler.py`: replaced `hour=3` hardcode with `config.MAINTENANCE_LOCAL_HOUR`

### Simulation CNN fix
- Bumped all three sim scenarios from 10 → 35 readings so CNN saturates by reading 30

## What Was Done This Session (2026-06-05)

### [R7] Calibration write fixed
- `VesselRegistry.update_user_traits(telegram_id, traits)` added — whitelisting wrapper over `update_biometrics`
- `_ALLOWED_TRAIT_FIELDS` frozenset = mass-assignment guard
- `insulin_sensitivity` dropped from frontend (ISF is twin-learned, not a stored trait)
- `twa_api.py` error message corrected; `TWA_DIR` now `Path(__file__).resolve()`-based [R8]
- Integration test: `ops/lab/test_twa_calibration.py` (3, temp-SQLite, real DB)

### [F1] 4h + 1d forecast horizons wired
- New pure module `diabetic/ml_engine/forecast.py` — `build_horizons`, `project_4h`, `project_24h`, `build_basal_drift`
- `coordinator.py` stores `self.last_prediction_4h` / `self.last_prediction_1d`, refreshed every live cycle (try/except guarded, never breaks alert loop)
- Meal handler basal-drift loop deduplicated via `build_basal_drift`
- Endpoint `GET /api/v1/forecast` returns `horizon` (live, ~97 pts), `horizon_1d` (25 pts once oracle fits ≥24h), `resolution_mins`
- Dashboard: 4h⇄1d segmented toggle; 1d shows "Circadian model learning" pre-fit
- 15 unit tests: `ops/lab/test_forecast.py`

### Blast-through audit
- All sections OPEN, no gated sections
- `twa_api.py` regraded D → A (gate cleared)
- No security findings, no stubs, no orphan commands

## Open Work

### Deployment (next priority)
1. **Validate Docker/Compose on a Docker-capable host** — the current verification host has no Docker executable.
2. **Local deployment on old Asus laptop** — install Ubuntu, docker-compose up, point CGM uploader to local IP.
3. **ML weights retraining** — current v15 is structurally valid but stale. It will auto-retrain on the live schedule. Force early: `python -m diabetic.ml_engine.train --source mongo --epochs 20`.

### Architectural Debt (Future Session)
3. **coordinator.py decomposition** — 872 LOC. Extract `_maintenance_loop`, `_refit_oracle_loop`, `_deep_historical_sync` to `diabetic/monitoring/maintenance.py`. Needs coordinator integration tests first.

### Deferred (Requires Live Infrastructure)
4. **Phase 5 MongoDB thread-pool stress test** — deferred until live Atlas available.
5. **1d circadian chart** — populated after oracle accumulates ≥24h fasting data (by design; no code needed).

### Minor deferred
6. **Arrow-key TUI** — numbered menus work; arrow-key nav not chosen yet.
7. **`/api/v1/forecast` Monte Carlo P5/P95** — `predict_monte_carlo` exists on twin, not exposed.
8. **Graph refresh** — stale (~1500+ new LOC from this session unrepresented). Run `/graphify` when `GEMINI_API_KEY` available.

## Blockers
- Graph refresh blocked (no `GEMINI_API_KEY`)
- Phase 5 MongoDB stress test blocked (no live Atlas)
- Docker build/Compose runtime validation blocked (Docker is not installed on this host)

## Section Grades (committed implementation — 2026-07-18)
| Section | Grade |
|---|---|
| `diabetic/auth/` | A |
| `diabetic/ml_engine/forecast.py` | A |
| `diabetic/ml_engine/train.py` | A |
| `diabetic/ml_engine/scheduler.py` | A |
| `diabetic/telegram_bot/twa_api.py` | A |
| `diabetic/storage/vessel_registry.py` | A |
| `diabetic/cli/` | A |
| `diabetic/mcp/` | A |
| `diabetic/ingestion/nightscout.py` | A |
| `diabetic/utils/health.py` | A |
| ML artifact/inference contract | A |
| Runtime/test dependency contract | A |
| `diabetic/coordinator.py` | B |
| `twa/` frontend | B |
| `docker-compose.yml / infra` | B |
