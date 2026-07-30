# Handoff — Current Objectives

_Last updated: 2026-07-24_

## Current Phase
**R17-R29 are code-verified. R30 runtime reproducibility is repaired locally,
but Docker/live-provider and semantic-graph evidence remain external promotion
gates.**

## Last Historical Verified State (2026-07-18)
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

### 2026-07-24 superseding audit priority
1. **Completed:** R25 restricts the singleton pipeline to patient/caregiver;
   registry membership is not authorization.
2. **Completed:** R26 keeps current critical glucose alerts outside feedback
   dampening and requires fresh real cardiac telemetry for exercise suppression.
3. **Completed:** R27 exposes typed treatment provider state, REST fallback,
   bounded last-known-good context, and HUD/health degradation.
4. **Completed:** R28 separates core `ready` from `neural_ready`; `/healthz`
   remains liveness and `/readyz` consumes the core readiness contract.
5. **Completed:** R29 neutralizes calendar-derived model effects at `1.0`.
6. **Partially completed:** R30 now has durable CPython 3.12.13, 81 compatible
   packages, corrected docs, and two passing 105-test runs. Semantic graph and
   Docker runtime evidence remain unavailable.

### Deployment (next priority)
1. **Validate Docker/Compose on a Docker-capable host** — Compose 2.40.3 is
   installed here, but this account cannot access `/var/run/docker.sock`.
2. **Local deployment on old Asus laptop** — install Ubuntu, docker-compose up, point CGM uploader to local IP.
3. **ML weights retraining** — automatic training defaults off. Do not retrain
   until R25-R28, real aligned cardiac telemetry, and promotion readiness are
   cleared; then use `python -m diabetic.ml_engine.train --source mongo --epochs 20`.

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
- Docker runtime blocked by socket access despite a working Compose CLI.

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

## 2026-07-23 Deep Blast-Through Handoff

**Mode:** full repository audit, review-only. Application code was not changed.

**Verdict:** promotion blocked. DCS was reassessed from the archived 0.947 to
**0.720** after tracing current cross-boundary behavior.

**Critical path:**
1. R17 — fix Nightscout/Mongo SGV units; `sgv=39` must remain a severe low.
2. R18 — stop CLI/MCP disclosure of `TWA_DEV_TOKEN`.
3. R19 — add telemetry provenance and exclude synthetic inputs from clinical
   alerts/training.
4. R20 — establish single-owner, non-blocking, atomic model promotion with
   last-known-good rollback.
5. R21 — add explicit HUD availability and freshness; remove numeric sentinels.

**Current verification:**
- `git diff --check` passed.
- Working tree and fresh committed archive compile under system Python 3.14.
- The 70-test result remains historical committed-archive evidence from
  2026-07-18; it could not be rerun because `.venv` points to a deleted `/tmp`
  Python and system Python lacks the declared dependencies.
- Compose CLI exists; Docker daemon access is denied.
- Graph refresh was deliberately not run: graph tooling is absent and the
  untracked runner would degrade semantic output without an exported API key.

**Durable audit outputs:** `workspace/DEV_REVIEW.md`,
`workspace/REVIEW_LEDGER.md`, and `workspace/DEV_COMMENTS.md`.

**Next-session instruction:** use a scoped mass-implementation pass in the
remediation order above. Do not claim production readiness until R17-R21 are
closed and verified from a fresh Python 3.11 environment and Docker-capable host.

## 2026-07-23 Implementation Handoff

R17-R23 are closed in the working tree and R24 is code-complete. The full
repository suite passes (**85 tests plus 5 subtests**) in the fresh Python
3.12.13 environment. Dependency compatibility, compileall, Compose static
validation, shell syntax, and diff hygiene all pass.

The requested Mongo extraction is complete under
`storage/migrations/from-2026-06-01/` (ignored): 7,204 entries and one profile,
2.1 MiB, with all manifest hashes independently verified. The source contains
no qualifying treatments, device-status, activity, or food rows. The first
entry is June 5 and the latest is July 1.

Current read-only health is intentionally not ready: MongoDB responds, the
configured Nightscout endpoint does not, no coordinator is running, and the
existing v15 artifact has no trusted promotion manifest. Automatic retraining
is disabled by default and cannot promote without real aligned cardiac data.

The remaining queue is external and ordered:

1. Grant the local user Docker socket access, then run
   `docker compose up -d --build` and inspect `docker compose ps`.
2. Stage the verified export with
   `python scripts/ops/migrate_nightscout.py stage-restore --source
   storage/migrations/from-2026-06-01`; compare counts before any cutover.
3. Verify Nightscout at port 1337, Bio-Quant `/healthz` and `/readyz`, then take
   the first local backup.
4. Add real cardiac telemetry before any deployable model retraining.
5. Refresh the semantic graph only with credentialed graph tooling; do not let
   the existing untracked AST fallback overwrite semantic evidence.

## 2026-07-24 Session Closeout

The implementation and skill mirror sync are committed and pushed:
`3984025 feat: harden local Nightscout runtime and sync skills`. Remote
`main` was verified at the same hash. The repository suite remains green at
85 tests plus 5 subtests.

The working tree has only the intentional pre-existing untracked graph helper
files `run_graphify.py` and `.graphifyignore`. The graph was not refreshed
because semantic tooling/API credentials are unavailable.

Next session should begin with the external runtime queue: obtain Docker
socket access, start and inspect Compose, stage the verified June export,
verify Nightscout and Bio-Quant readiness, then take a backup. Do not retrain
for deployment until real aligned cardiac telemetry exists.

## 2026-07-24 R25-R30 Mass Implementation

- R25-R29 are implemented and directly covered.
- Durable interpreter:
  `/home/vgbn1/.local/share/uv/python/cpython-3.12.13-linux-x86_64-gnu`;
  `.venv` and `~/.local/bin/python3.12` resolve to it.
- Focused proof: `53 passed, 10 subtests`.
- Full working-tree proof: `105 passed, 10 subtests`.
- Isolated `git archive HEAD` plus tracked implementation patch:
  `105 passed, 10 subtests`.
- Compatibility: 81 locked packages pass `uv pip check`.
- `compileall`, Compose config, backup shell syntax, `git diff --check`,
  `git fsck --strict`, and v15 hash verification pass.
- DCS: `0.800 -> 0.942` (freshness `0.90`, schema `0.96`, coverage `0.96`).
- Promotion remains blocked because no Docker runtime, live Nightscout/Mongo
  readiness, restart/recovery, backup/restore, real cardiac, or graph refresh
  proof was produced.

## 2026-07-24 Session Closeout - Frontend Deferred

- User ended the session after reviewing current blood-sugar monitoring UI
  capabilities.
- Frontend redesign and alert-UI design are explicitly deferred to a later
  session; no additional frontend edits were made.
- Current verified boundary remains R25-R29 code-verified with working-tree and
  isolated-source results of `105 passed, 10 subtests`.
- Next UI session should begin by defining glucose units, degraded-state
  presentation, alert history/acknowledgement, meal/insulin entry boundaries,
  and offline asset strategy before implementation.
- Production/runtime gates remain unchanged: Docker/live providers,
  restart/recovery, backup/restore, real cardiac, and semantic graph.

## 2026-07-30 Session Closeout — Skill Mirroring & Clean Release Revision

- **Skill Sync**: Mirroring between `.agent/skills` and tracked `.agents/skills` is complete. Imported `feature-exerciser` and `refactor-readability` from `personal_finance_draft`. Integrated `bio-quant-protocols` skill.
- **Repository Revision**: All uncommitted working-tree changes, historical data ingestion features, R25-R30 core refactorings, and doc updates were committed into 5 clean, verified Conventional Commits.
- **Verification**: `114 passed` across all 12 test suites in `ops/lab`.
- **Working Tree**: Clean on `main`, 14 commits ahead of `origin/main`.
- **Next Steps**:
  1. Validate Docker runtime and Compose deployment once socket access is available.
  2. Perform initial local Nightscout backup and verify `/healthz` and `/readyz` endpoints.

