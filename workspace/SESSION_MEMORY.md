# Session Memory — Verified Facts & Cautions

_Cumulative. Never delete; append corrections._

## Architecture

### ML Engine
- **CNN model**: v15 (`diabetic/ml_engine/weights/diabetic_cnn_v15.pth`) — absolute-path resolved from project root via `config.py`
- **Inference contract**: Two temporal channels only. Inference and training must stay aligned on this.
- **Sliding window**: 30-reading saturation required before inference activates; emits `ValueError` on under-saturation
- **Hot reload**: `scheduler.py` skips `reload_weights` when training returns no deployable model (prevents false scheduler success)

### Training Pipeline
- **Scheduler**: `MetabolicScheduler` anchored to `Coordinator` lifecycle — never runs as a standalone zombie process
- **Safety guards**: Loss floor MSE > 2.0 purges weights; physiological range clamp 2.0–25.0 mmol/L
- **Timezone check**: Fails fast at boot (CRITICAL BOOT FAILURE) if timezone invalid — 3 AM training loop timing is safety-critical
- **Environment anchoring**: `pd.merge_asof` with 60m tolerance joins weather data to bio-telemetry for training

### Storage
- **VesselRegistry**: Async SQLAlchemy 2.0 + aiosqlite; uses Eager Loading for `bio_traits` to avoid migration loop bug
- **MongoDB retention**: `run_retention_cleanup` is null-safe when DB collections are uninitialized
- **Test isolation**: Integration tests must use real DB (not mocks); `test_c3.py` uses temp SQLite for audit DB

### Coordinator & Ingestion
- **Treatment bridge**: REST and Mongo treatment shapes normalized in `coordinator.py`; Mongo preferred when available
- **Nightscout auth**: Falls back from token-based to `api-secret` headers on 401; uses `?token=` param for long Heroku secrets
- **RLHF dampening**: FeedbackEngine wired for all alert types; 1.4× trigger heightening after 3+ net false alarms

### Security
- **Exception handlers**: HTTP errors log `e.__class__.__name__` only — no token/secret strings in logs
- **PID lock**: `.bot.lock` singleton in `main.py` with `atexit` cleanup

## Known Issues / Debt
- **Graph debt**: 38 isolated nodes, 31 thin communities in `graphify-out/GRAPH_REPORT.md` — needs relabeling pass
- **Nightscout 401 instability**: Possible header vs. query-param auth conflict in `MongoDBClient` bridge (flagged, not resolved)
- **Twin plot parity**: `twin.py` returns 13-point sliced arrays; any plotting/TWA renderers consuming raw twin output need update

## Process Rules
- Never skip git hooks (`--no-verify`)
- Confirm before force-push or destructive git operations
- Prefer absolute paths; avoid CWD-relative path resolution in ML engine code
- `compileall` + `pytest -q` before claiming a session complete

## Session 2026-06-05 — CLI/TUI, MCP, Web Auth (all uncommitted; 49 passed / 2 skipped)

### New surfaces
- `diabetic/cli/` — structured CLI/TUI (manifest → dispatcher → commands → rich engine). 10 cmds / 5 categories. Launch: `diabetic` (PS function) · `python -m diabetic.cli.tui` · `python -m diabetic.cli <cat> <cmd>`. Contract test `ops/lab/test_cli_manifest.py`. Numbered-selection menus (win32-safe); arrow-key nav deferred.
- `diabetic/mcp/` — FastMCP stdio server; 3 read-only `bio_*` tools (ping/health/config), `TOOL_SPECS` registry. Run `python -m diabetic.mcp`; probe `scripts/mcp_probe.py`; test `ops/lab/test_mcp_tools.py`.
- `diabetic/auth/` — Telegram WebApp `initData` HMAC verify (`secret = HMAC(b"WebAppData", bot_token)`) + `is_authorized` (patient/caregiver/registry, **fails closed**). FastAPI dep `require_twa_user` guards all `/api/v1/*`. Tests `ops/lab/test_twa_auth.py` (7); TestClient probe: no-auth 401, stranger 403, patient 200, calibration-no-auth 401.
- `twa/` — refined vanilla frontend: index/login/settings/history + `assets/{app.css,auth.js,api.js,dashboard.js,settings.js,history.js}`; Telegram-themed, mobile-first. Doc `docs/engineering/architecture.md`.
- New config: `TWA_ALLOWED_ORIGINS`, `TWA_DEV_TOKEN`, `TWA_AUTH_MAX_AGE_SECS`. Launcher `diabetic.ps1` + `diabetic` PS-profile function (replaced `bq`).

### Corrections to earlier notes
- **Nightscout 401**: now centralized in `_request_with_auth_retry`; on exhaustion it **raises `RuntimeError`** (was silently returning `None`). The "401 instability" caution above is largely addressed (R1/R6 cleared). `asyncpg` restored to `requirements.txt`.
- **Auth single-sourced**: bot `handlers.authorized_only` now delegates to `auth.is_authorized` — the duplicate allowlist/registry block is gone.
- **Graph node counts** in "Graph debt" are stale (see caution).

### Cautions
- **Graph STALE**: `graphify-out/` predates cli/mcp/auth (~636 new LOC unrepresented). Refresh via `/graphify` (needs `GEMINI_API_KEY`). Do NOT run `run_graphify.py` without the key — AST-only output would degrade the semantic graph.
- **Dead claim**: `/api/v1/forecast` 4h horizon reads `last_prediction_4h`, which is **never produced anywhere** → HUD "Metabolic Horizon" line always empty. Design-heavy fix (Digital Twin/oracle).
- **FIXED (forecast, 2026-06-05):** `/api/v1/forecast` 4h + 1d horizons wired. New pure module `diabetic/ml_engine/forecast.py` — `build_horizons/project_4h/project_24h/build_basal_drift`. `coordinator.py` stores `self.last_prediction_4h` / `self.last_prediction_1d`, refreshed each live cycle (try/except guard — forecast errors can't break the alert loop). Meal handler deduped to use `build_basal_drift`. Endpoint returns `horizon` (now populated, ~97 pts), `horizon_1d` (25 pts after oracle fits at ~24h), `resolution_mins`. Dashboard: 4h⇄1d toggle added (`chart-head` + `seg-btn`); 1d shows "learning" note pre-fit. 15 new unit tests (`test_forecast.py`). Suite **66 passed**.
- **FIXED (blast-through 2026-06-05, [R7] + [R8]):** `POST /api/v1/calibration` was calling the **non-existent** `vessel_registry.update_user_traits(...)` → guaranteed 500. Now `VesselRegistry.update_user_traits(telegram_id, traits)` exists as a **whitelisting** wrapper over `update_biometrics` (`_ALLOWED_TRAIT_FIELDS` frozenset = mass-assignment guard; unknown keys would otherwise `TypeError` in `update_biometrics(**...)`). Frontend `insulin_sensitivity` dropped (ISF is twin-learned, not a `BioTraits` column). Integration test `ops/lab/test_twa_calibration.py` (temp-SQLite, no mock) drives the real write path — closed the gap where auth probes ran with `COORDINATOR_REF=None`. [R8]: `TWA_DIR` now `Path(__file__).resolve().parents[2]/"twa"` (CWD-independent). `twa_api.py` **D→A, ungated**. Suite **51 passed**.
- **Sandbox quirk**: this environment blocks `socket.socketpair()`, so bare `asyncio.run` entrypoints, the interactive TUI, and occasionally the async test loop fail *here only* — they work on the real machine. Verify async paths empirically.
- **FIXED (2026-06-27):** All Phase 5 work committed in 5 logical commits. Working tree clean.

## Session 2026-06-27 — Blast-Through Audit + Mass-Implement

### Live data verified
- MongoDB has **288 real readings** (CGM syncing continuously to MongoDB even while coordinator was offline 22 days)
- CNN fires on real data: `Pred Glu=5.11 mmol/L` from 288-snapshot window
- Oracle fit confirmed: `A=2.39, φ=−1.70, C=8.36` (low amplitude = stable circadian pattern; C=8.36 is elevated fasting baseline — watch if sustained)
- Both forecast horizons populated: 4h (49 pts, peak 5.12) and 1d (25 pts, range 5.99–10.74)
- Latest BG at time of test: 4.38 mmol/L, velocity −0.003 (flat), alpha gate NOT fired, blended 30m pred = 4.62

### Corrections to earlier notes
- **R11 was false alarm**: `MetabolicScheduler` IS started from `main.py:105-107` before `start_live_mode()`. `coordinator._scheduler_task` is assigned there. Coordinator.shutdown() is correct.
- **COORDINATOR_REF Docker gap (R10) FIXED**: TWA API now starts as daemon thread inside `main.py live` branch. `bio-quant-twa` standalone service removed from docker-compose.
- **Simulation CNN gap FIXED**: all three sim scenarios now generate 35 readings; CNN activates from reading 31.

### Architecture facts
- **TWA serving pattern**: `twa_api.py` uses `threading.Thread(target=start_api, daemon=True)` started from `main.py`. This is the correct pattern — same process = same `COORDINATOR_REF`. Do NOT put TWA back in a separate container.
- **docker-compose services**: 3 services only — `mongodb`, `nightscout`, `bio-quant-core`. Core exposes port 8000 for TWA.
- **ML weights staleness**: weights age tracked in `health.py` via `Path.stat().st_mtime`. Stale threshold = 7 days. At 39 days stale — retrain needed on next live run.

### Cautions
- **Oracle C=8.36 elevated**: the fasting baseline the oracle learned is high for a T1D patient. Could reflect dawn phenomenon, meals during the 24h window, or sensor drift. Monitor over multiple days.
- **Graph STALE**: ~1500+ new LOC from Phases 4-5 unrepresented in graphify-out. Do not use graph for structural queries until refreshed. Needs `GEMINI_API_KEY`.
- **Heroku vs local**: user plans to move from Heroku to local Ubuntu deployment on old Asus laptop. docker-compose is ready; CGM uploader (phone app) needs to be pointed at local IP. Discussed but not executed.

## Session 2026-07-18 — Deployment Reproducibility

### Corrections
- Docker empty named volumes copy existing image content into the volume by default. The weights volume was not the first-boot data-loss bug; the image built from clean `HEAD` lacked `diabetic_cnn_v15.pth`.
- The v15 artifact in the working tree is a valid PyTorch state dictionary: `weights_only=True`, 14 keys, no missing or unexpected model keys.
- Missing or invalid weights must never permit randomly initialized CNN output. `MetabolicInferenceRunner.weights_loaded` now gates inference and preserves the kinematic fallback.
- `inference_active` is true only when the snapshot buffer is saturated and validated neural weights are loaded.

### Verification
- Isolated CPython 3.11.15 environment created under `.venv`
- 130 declared packages installed; dependency compatibility check passed
- Full working-tree suite: 70 passed in 5.19s
- Pre-commit clean-HEAD candidate archive plus intended implementation files: 70 passed in 5.22s
- Committed `HEAD` archive: 70 passed in 5.70s
- Standard-library contract gate: 3 passed

### Cautions
- The implementation is committed as `a8bd5f4` and passed the clean committed-archive suite.
- Docker/Compose runtime verification is still host-blocked because Docker is unavailable.
- The sandbox can stall the aiosqlite integration tests; the identical suite passes outside the sandbox.

## Session 2026-07-23 — Deep Blast-Through Audit

### Corrections
- Nightscout `sgv` is not safely unit-detectable by numeric threshold. Current
  REST and Mongo logic can invert a 39 mg/dL severe hypo to 39 mmol/L.
- Mock cardiac readings currently inherit `source="ble"`; mock weather is
  persisted without provenance and can enter training.
- The deployed ML path is overwritten before post-training safety checks.
  Failed guards delete the deployed path instead of preserving last-known-good.
- Both scheduler and coordinator maintenance own retraining near the same daily
  window; the synchronous PyTorch loop runs inside the live async event loop.
- TWA cold state uses glucose `0.0`, which the frontend classifies as low and can
  turn into a haptic warning. Snapshot freshness is not exposed.
- Health `"mongodb": "ok"` means a Motor collection handle exists, not that
  MongoDB was pinged successfully.

### Verification
- `git diff --check` passed.
- System Python 3.14 compileall passed in the working tree and fresh HEAD archive.
- Current pytest could not run: system Python lacks project dependencies and
  `.venv/bin/python` is a broken link to deleted `/tmp` CPython 3.11.
- Docker Compose 2.40.3 is installed; Docker daemon access is denied.
- Graph remains stale; absent tooling/API credentials prevented a safe semantic
  refresh.

### Decision
- Promotion remains blocked. Current DCS is 0.720.
- Remediation order is R17 unit safety, R18 secret masking, R19 provenance,
  R20 atomic/background training, then R21 HUD freshness.

## Session 2026-07-23 — R17-R24 implementation

### Durable facts
- R17-R23 are implemented and the full suite passes: 85 tests plus 5 subtests.
- The local environment is CPython 3.12.13 with 81 compatible packages and
  generated runtime/dev lockfiles.
- Mongo export from 2026-06-01 is complete under ignored storage: 7,204 entries,
  one profile, 2.1 MiB, six verified hashes. Data spans June 5 through July 1.
- Docker Compose is loopback-first and validates statically. Runtime remains
  blocked because this account cannot open `/var/run/docker.sock`.
- Current live health is not ready: MongoDB responds, Nightscout does not, the
  coordinator is offline, and v15 has no promotion-manifest checksum.
- Automatic training defaults off and deployable Mongo training requires real
  aligned cardiac telemetry.

### Cleanup decisions
- Removed the unused cloud push, semantic-memory, and XGBoost claims/dependencies.
- Removed obsolete Heroku files, tracked bytecode, duplicate/orphan ingestion
  modules, and a broken climate simulation.
- Preserved the working offline parser wrapper because
  `scripts/tools/extract_historical.py` still imports it.
- Preserved untracked graph tooling and the session skill mirror as pre-existing
  user files; semantic graph refresh remains intentionally deferred.
