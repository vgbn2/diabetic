# State — Bio-Quant Session State

_Mirrors `.gsd/STATE.md` but tracks workspace-level session continuity._

## Current Position
- **Phase**: 5 (Scheduler Stress Test + Graph Debt) — Not yet started
- **Prior Phase**: 4.1 (Alpha Gating) — Complete
- **Status**: Ready for Phase 5 work; workspace bootstrapped

## What Is Stable
- CNN inference → two-channel contract locked
- Training pipeline → loss floor + physiological clamp + lifecycle anchor
- Runtime bridge → treatment normalization, Mongo preference, inference saturation guard
- Auth fallback → Nightscout 401 → api-secret header fallback
- Test isolation → temp SQLite for `test_c3.py`

## Section Grades (2026-06-04 Full Audit + Tier 2)

| Section | Grade | Trend | Notes |
|---|---|---|---|
| `diabetic/ml_engine/` | A | B→A | Hot-reload stress test passes 100/100; inference contract tests in ops/lab/ |
| `diabetic/coordinator.py` | B | — | Excellent architecture; FIX-comments are doc, not clutter |
| `diabetic/ingestion/nightscout.py` | A | B→A | Auth retry centralized; R1 data-drop fixed; no print/stubs |
| `diabetic/ingestion/mongo.py` | A | — | Clean; treatment mapping preserves both channels |
| `diabetic/storage/` | A | — | Async SQLAlchemy service layer; idempotent migration |
| `diabetic/config.py` | A | B→A | print replaced with logger; RETENTION_DAYS field added |
| `diabetic/utils/audit_logger.py` | A | — | WAL, async locks, proper error handling |
| `diabetic/main.py` | A | B→A | cleanup uses config.RETENTION_DAYS; no hardcoded 180 |
| `diabetic/telegram_bot/twa_api.py` | A | B→A | module-level logger added; print replaced |

## Section Grades (2026-06-05 Blast-Through #2 — focused, post-forecast session)

| Section | Grade | Trend | Notes |
|---|---|---|---|
| `diabetic/ml_engine/forecast.py` | A | new | Pure module, no I/O, all guards explicit (`return []`/`None` are sentinel guards, not stubs). 15 unit tests cover all 4 functions, empty/unfit/live branches. |
| `diabetic/coordinator.py` | B | B | Forecast refresh correctly placed after backfill/uninit early returns; guarded with try/except; meal-handler basal-drift deduped. Still 865+ LOC — decomposition deferred. |
| `diabetic/telegram_bot/twa_api.py` | A | D→A | Gate cleared (R7+R8 done this session). All `/api/v1/*` guarded; `TWA_DIR` absolute; endpoint additive (no breaking changes). |
| `diabetic/storage/vessel_registry.py` | A | A | `update_user_traits` whitelist wrapper solid; `_ALLOWED_TRAIT_FIELDS` frozenset is the single gate. |
| `twa/` (frontend) | B | A→B | 4h⇄1d toggle wired correctly; `renderHorizon()` has a learning-note fallback. Minor: `history.js` still reads from `/api/v1/forecast` `points` key — works but shares an endpoint with the dashboard (acceptable; two read operations, no mutation). |
| `ops/lab/` (new tests) | A | A | 66 passed / 0 failed. `test_forecast.py` (15): length, t=0 anchor, finite check, empty-history, oracle unfit/fit, drift shape. `test_twa_calibration.py` (3): round-trip, whitelist guard, no-op. All real DB / real twin — no mocks per repo rule. |

## Section Grades (2026-06-05 Focused Audit — changed surface only)

Scope: files in `git diff HEAD` + same-section new files. Untouched sections carry forward 2026-06-04 grades (cached).

| Section | Grade | Trend | Notes |
|---|---|---|---|
| `diabetic/ingestion/nightscout.py` | A | A→B→A | R6 fixed: `_request_with_auth_retry` now raises on exhaustion instead of returning `None`; regression test added. Error-handling lens restored. |
| `diabetic/storage/` (engine + requirements) | A | A→C→A | **GATE CLEARED.** R5 fixed: `asyncpg>=0.29.0` restored to requirements (user kept Postgres support); engine/docstring unchanged. No more infra↔storage drift. |
| `diabetic/main.py` + `diabetic/utils/health.py` | A | A | `health` command wired; health.py deps all verified real (no hallucinated symbols); non-blocking, side-effect-free. |
| `diabetic/config.py` | A | A | `RETENTION_DAYS` field + logger fix verified in working tree. |
| `diabetic/telegram_bot/twa_api.py` | A | A→D→A | **GATE CLEARED.** [R7] fixed: `VesselRegistry.update_user_traits` added as a whitelisting wrapper over `update_biometrics` (`_ALLOWED_TRAIT_FIELDS` = mass-assignment guard); frontend `insulin_sensitivity` dropped; calibration error message corrected. [R8] fixed: `TWA_DIR` now `Path(__file__).resolve()`-based (CWD-independent, verified). Test gap closed: `ops/lab/test_twa_calibration.py` (3, temp-SQLite, no mock) drives the real write path. Suite **51 passed**. |
| Infra (`docker-compose.yml`) | B | — | Good: nightscout service, named volumes for storage/weights, corrected broken TWA module path (`twa.twa_api`→`diabetic.telegram_bot.twa_api`). `INSECURE_USE_HTTP=true` flagged for prod hardening. |
| `ops/lab/` (3 new test files) | A | — | 22 new tests, R1 regression gate present, asserts constants sourced from `medical_constants` (drift guard). 27 passed / 2 skipped. |
| `diabetic/cli/` (new CLI/TUI section, 2026-06-05) | A | new | Finance-parity manifest + dispatcher + rich TUI; 10 commands / 5 categories; manifest↔handler contract test (`test_cli_manifest.py`, 8 passing); no stubs; secret masking verified. Doc: `docs/engineering/tui_feature_map.md`. Launch: `diabetic` (PS function) → `python -m diabetic.cli.tui`. |
| `diabetic/mcp/` (new MCP server, 2026-06-05) | A | new | FastMCP stdio server; 3 read-only `bio_*` tools reuse `get_system_health()`/masked config; `TOOL_SPECS` registry; probe `scripts/mcp_probe.py`; contract test `test_mcp_tools.py` (6). Run: `python -m diabetic.mcp`. DB-agnostic for future Supabase move. |
| `diabetic/auth/` + `twa/` (web auth + UI, 2026-06-05) | A | new | **Security win:** Telegram WebApp `initData` HMAC verify + patient/caregiver authz now guards all 3 `/api/v1/*` endpoints — closed the previously-open, unauth'd, trait-MUTATING `POST /calibration`. CORS tightened to `TWA_ALLOWED_ORIGINS`. Modular vanilla frontend (dashboard/login/settings/history + assets). 7 auth tests + TestClient probe (no-auth 401, stranger 403, patient 200). Full suite **49 passed / 2 skipped**. Doc: `docs/engineering/architecture.md`. |

**Launcher rename (2026-06-05):** `bq.ps1`/`bq` → `diabetic.ps1` / `diabetic` PowerShell function (profile updated; old `bq` removed). **Deferred:** arrow-key TUI (library not chosen — questionary/prompt_toolkit available, readchar not). **Distribution:** Docker chosen (one-command); polish pending.

**Mass-implement (2026-06-05):** bot `authorized_only` centralized onto `auth.is_authorized` (removed duplicated allowlist+registry logic → no auth drift between bot & web); stale `config.API_PORT` comment in `twa_api.py` fixed. Graph refresh **BLOCKED** (no `GEMINI_API_KEY` → `run_graphify.py` would AST-degrade the semantic graph; run `/graphify` instead). Highest remaining real gap: `/api/v1/forecast` 4h horizon (`last_prediction_4h` never produced — design-heavy). Suite **49 passed / 2 skipped**.

## Test Coverage (2026-06-04)
- Baseline before Tier 2: `5 passed, 2 skipped`
- After Tier 2: `27 passed, 2 skipped`
- New tests: `ops/lab/test_ingestion_pipeline.py` (9), `ops/lab/test_alpha_gate.py` (6), `ops/lab/test_nightscout_auth.py` (7)
- Phase 5 stress script: `python -m scripts.simulation.stress_scheduler` → 100/100 pass

## Graph Status (2026-06-05)
- **Refreshed**: 796 nodes · 1091 edges · 97 communities
- God nodes: Coordinator (43), GlucoseReading (27), MongoDBClient (23), MetabolicSnapshot (21)
- Hyperedges confirmed: Live Ingestion Pipeline, Metabolic Registry Layer, DSP Signal Processing Layer
- Outputs: `graphify-out/graph.html` (browser), `graphify-out/GRAPH_REPORT.md`, `graphify-out/graph.json`
- Remaining debt: 57 isolated nodes (5 are metadata artifacts: `code`, `document`, `paper`, `image`, `video`)

## Section Grades (2026-06-27 Blast-Through — Full Audit, commit e08a93e)

| Section | Grade | Trend | Notes |
|---|---|---|---|
| `diabetic/auth/` | A | new→A | HMAC correct, constant-time compare, replay guard, fail-closed |
| `diabetic/ml_engine/forecast.py` | A | A | Pure, side-effect free, sentinel guards clean |
| `diabetic/mcp/server.py` | A | A | Read-only, TOOL_SPECS registry, no security surface |
| `diabetic/utils/health.py` | A | A | Non-blocking, good fallbacks |
| `diabetic/ingestion/nightscout.py` | A | A | Auth retry solid, raise-on-exhaust correct |
| `diabetic/ml_engine/inference.py` | A | A | Dynamic bounding, resampling guard, weights_only=True correct |
| `diabetic/telegram_bot/twa_api.py` | A | A | Auth dep clean; COORDINATOR_REF in-process pattern correct |
| `diabetic/cli/` | A | A | Manifest↔dispatcher 10/10 parity, no stubs |
| `diabetic/telegram_bot/handlers.py` | A | A | Auth centralized, no duplicate allowlist |
| `diabetic/config.py` | A | A | Pydantic settings, no hardcoded secrets, boot validation solid |
| `diabetic/coordinator.py` | B | B | 872 LOC; _scheduler_task ghost (R11); decomp deferred |
| `diabetic/ml_engine/train.py` | B | — | Anti-hallucination guard solid; line 154 missing weights_only=True (R12) |
| `diabetic/ml_engine/scheduler.py` | B | — | Never started from coordinator (R11 dead code); 3AM ignores config (R13) |
| `docker-compose.yml / infra` | C | B→C | **GATED.** TWA+core separate containers, COORDINATOR_REF never injected → all /api/v1/* dead in prod (R10); no healthchecks |

**last_audited_commit: e08a93e** | **last_audit_date: 2026-06-27**

## What Is Open
1. **[R9] CRITICAL: Commit all untracked Phase 5 files** — auth/, cli/, mcp/, forecast.py, health.py, twa pages+assets, all Phase 5 tests. `git clean -fd` would wipe them.
2. **[R10] HIGH: COORDINATOR_REF always None in Docker** — TWA bridge dead in production. Fix: run TWA inside core container or add IPC.
3. **[R11] MEDIUM: MetabolicScheduler orphaned** — never started; delete scheduler.py or wire it.
4. **[R12] LOW: train.py:154 torch.load missing `weights_only=True`** — trivial fix.
5. **[R13] LOW: scheduler.py 3AM hardcoded** — dormant (R11 blocks reachability).
6. Phase 5 MongoDB thread-pool test (requires live Atlas — skipped)
7. coordinator.py decomposition (872 lines — Tier 3 architectural, future session)
8. Dashboard 1d circadian chart needs 24h of real data for oracle to fit (expected, by design)

## Decisions Locked
- **Fail-fast timezone check** at boot: no silent fallback, CRITICAL halt if invalid
- **Absolute ML weight paths** resolved from project root (not CWD)
- **No mock DB in integration tests**: prior incident where mock/prod divergence masked broken migration

## Next Steps for Next Session
1. `git add` all untracked Phase 5 files and commit (R9 — highest priority)
2. Fix COORDINATOR_REF Docker issue: move TWA start into core container (R10)
3. Resolve MetabolicScheduler: delete or wire it (R11)
4. `train.py:154` add `weights_only=True` (R12 — one line)
5. `scheduler.py:34` replace `hour=3` with `config.MAINTENANCE_LOCAL_HOUR` (R13 — only if scheduler is kept)
