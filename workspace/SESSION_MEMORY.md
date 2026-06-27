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
- **NOTHING COMMITTED** — the entire session is in the working tree. Next action: commit in logical chunks.
