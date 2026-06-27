# Handoff — Current Objectives

_Last updated: 2026-06-05_

## Current Phase
**Phase 5 — Scheduler Stress Test + Graph Debt**
All prior phases complete and committed.

## Last Verified State
- **Test baseline: `66 passed`** (all new-session surfaces covered, no mocks)
- `python -m pytest ops/lab -q` → 66 passed
- `python -m scripts.simulation.stress_scheduler` → 100/100, hot-reload clean
- `python -m diabetic.main health` → live JSON (ml_weights, mongodb, snapshot_buffer)
- Working tree: **clean** — user committed entire session in logical chunks

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

### Architectural Debt (Future Session)
1. **coordinator.py decomposition** — 865+ LOC. Extract `_maintenance_loop`, `_refit_oracle_loop`, `_deep_historical_sync` to `diabetic/monitoring/maintenance.py`. Requires coordinator-level integration tests first.

### Deferred (Requires Live Infrastructure)
2. **Phase 5 MongoDB thread-pool stress test** — live Atlas test deferred until connection available.
3. **1d circadian chart** — populated only after oracle accumulates ≥24h of fasting data (expected; no code change needed).

### Minor deferred
4. **Arrow-key TUI** — library not chosen (questionary/prompt_toolkit/readchar); numbered menus work fine for now.
5. **`/api/v1/forecast` Monte Carlo** — `predict_monte_carlo` exists on twin but not exposed; `build_horizons` uses deterministic path only. Add P5/P95 bands when needed.
6. **Graph refresh** — `graphify-out/` stale (~900 new LOC unrepresented). Run `/graphify` when `GEMINI_API_KEY` available.

## Blockers
- Graph refresh blocked (no `GEMINI_API_KEY`)
- Phase 5 MongoDB stress test blocked (no live Atlas)
- Windows Sandbox: `socket.socketpair()` restriction — async paths work on real machine, verify empirically

## Section Grades (current)
| Section | Grade |
|---|---|
| `diabetic/ml_engine/forecast.py` | A |
| `diabetic/telegram_bot/twa_api.py` | A |
| `diabetic/auth/` | A |
| `diabetic/storage/vessel_registry.py` | A |
| `diabetic/cli/` | A |
| `diabetic/mcp/` | A |
| `diabetic/coordinator.py` | B |
| `twa/` frontend | B |
| infra | B |
