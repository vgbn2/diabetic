# Cross-Project Learnings
_Shared intelligence between hyperglycemia-faint-predictor and personal_finance_draft._
_Updated: 2026-06-04. Append; never rewrite._

---

## Overview

| Attribute | hyperglycemia-faint-predictor | personal_finance_draft |
|---|---|---|
| Stack | Python, PyTorch, SQLAlchemy async, MongoDB, Telegram | Node.js, TypeScript, C++, Supabase, React/Vite |
| Domain | Real-time physiological monitoring + faint-risk prediction | Algorithmic trading + portfolio management |
| Phase | 4.1 complete → Phase 5 | Phase 9 active |
| Tests | 5 (sparse) | 62 (organized by contract) |
| ML | Real CNN training + safety guards | Deterministic adapters (no real training yet) |
| DCS | 0.89 (graph stale) | 1.0 under integrity policy |

---

## 1. Database

### What medical does well → finance should adopt
- **Dual-write with graceful degradation**: MongoDB primary + SQLite WAL local fallback (`audit_logger.py`). When cloud DB is down, the system keeps running. Finance has no equivalent local fallback for Supabase outages.
- **SQLite WAL mode + async lock**: `PRAGMA journal_mode=WAL` + `asyncio.Lock()` for concurrent writes in the same process. Finance's Supabase calls have no concurrency guard.
- **Retention policy enforcement**: `run_retention_cleanup(days=180)` deletes data strictly older than threshold. Finance accumulates stale cache indefinitely — add a `data quarantine` TTL sweep.
- **MongoDB singleton pattern** (`utils/db.py`): prevents Atlas connection pool exhaustion by sharing one client across all consumers. Finance opens new connections per request in some paths.
- **Date serialization clarity**: pass `datetime` object directly to Motor/PyMongo (BSON Date), not `.isoformat()` string. Finance stores ISO strings in Supabase which then require string comparison — use typed columns.

### What finance does well → medical should adopt
- **Integrity check command**: `backend integrity --json` returns `ok`, `cached`, `missing`, `stale` counts. A `system_health()` async function in medical would surface MongoDB staleness, ML weight age, and snapshot buffer size without requiring a full run.
- **Cache quarantine command**: `data quarantine` isolates suspect cache entries. Medical has no equivalent for flagging corrupt Nightscout readings without deleting them.
- **TS-index writes after backfill**: finance writes a timestamp index entry immediately after backfill completes so freshness checks are accurate. Medical relies on reading collection counts which can be slow.

---

## 2. User Auth

### What medical does well → finance should adopt
- **Secret scrubbing at construction**: `NightscoutClient.__init__` computes `sha1(raw)` immediately and lets the plaintext go out of scope. `self._token` is stored only when the secret is an opaque access token (not a raw password). Exception handlers use `e.__class__.__name__` only — no token strings in logs.
- **Token mode detection**: `len(raw) > 24 or '-' in raw or raw.startswith("subject-")` distinguishes opaque access tokens from hashed passwords to pick the right auth path (Bearer header vs query param vs hashed `api-secret`).
- **Auth fallback on 401**: automatically falls back from token auth to `api-secret` header mode when a 401 is received, updating internal mode flag so subsequent calls use the correct method.
- **Decorator-based auth**: `authorized_only` Telegram decorator checks VesselRegistry SQL rather than hardcoded IDs.

### What finance does well → medical should adopt
- **Auth command with connectivity test**: `backend/cli/commands/auth.js` has a `connectivity` subcommand that tests the Supabase connection and reports clearly. Medical should add `python -m diabetic.main health` that tests Nightscout + MongoDB + BLE connectivity.
- **Non-TTY fallthrough**: auth.js handles the case where stdin is not a TTY (CI environment, piped execution) by returning a non-interactive error code. Medical's Telegram auth has no equivalent for headless/non-interactive execution.

### Future (for both — website)
- **When adding a web layer**: follow medical's pattern of never storing raw secrets; use short-lived JWTs signed at the API layer; store only hashed or opaque tokens.
- **Supabase RLS** (finance already uses): Row-Level Security policies ensure one user can never read another's data. Medical should adopt this pattern when adding multi-user web access.
- **Session token rotation**: neither project currently rotates tokens on activity. Add a `refreshed_at` field to session tokens with a 24h sliding window.

---

## 3. Config

### What medical does well → finance should adopt
- **Centralized constants with citations**: `medical_constants.py` has source citations (Battelino 2019, WHO PM2.5 baseline), layer annotations (Layer 1-5), and explanatory comments for every magic number. Finance's `models.js` and `backtest.js` have uncited thresholds — add provenance comments for `confidenceScale`, `RATE_LIMITS` interval, and walk-forward split ratios.
- **Fail-fast boot validation**: `validate_config()` checks timezone validity, required env vars, and physiological plausibility at boot. Finance has no equivalent — it discovers missing config at runtime mid-request.
- **Absolute path resolution for ML weights**: `Path(__file__).resolve().parent.parent / "diabetic/ml_engine/weights/..."` prevents CWD-dependent failures when called from cron or a different working directory.
- **Pydantic Settings with validation aliases**: maps `TELEGRAM_BOT_TOKEN` → `TELEGRAM_TOKEN`, `NIGHTSCOUT_API_SECRET` → `API_SECRET`. Finance uses raw `process.env` reads scattered across files.

### What finance does well → medical should adopt
- **Config externalization to YAML**: strategy files (`config/strategies/*.yaml`) carry `signal_threshold`, `engine`, `features`, `indicators`, `risk_weight`. Medical's `ALPHA_GATE_DIVERGENCE_LIMIT` and `ALPHA_GATE_CONFIDENCE_THRESHOLD` are hardcoded in `medical_constants.py` — they should be patient-configurable via `.env` like `ALPHA_GATE_DIVERGENCE_LIMIT=2.5`.
- **`DEFAULT_USER_SETTINGS` in paths.js**: a single place that defines the default shape of user-configurable JSON. Medical has no equivalent; user preferences are scattered across config fields.
- **Settings command**: `settings.js` has 7 subcommands (show, timezone, layout, params, flags, alerts, reset) that persist to `storage/data/user_settings.json`. Medical should add a `/settings` Telegram command for patient parameters.

### Future (for both — website)
- **Environment tiers**: add `NODE_ENV`/`BIO_ENV` (`development`, `staging`, `production`) to separate configs. Both projects currently use a single `.env`.
- **Secrets management**: for production web deployment, move secrets to a vault (Doppler, HashiCorp) rather than `.env` files. Both projects are currently `.env`-only.

---

## 4. CLI / TUI

### PORTED 2026-06-05 — finance CLI/TUI pattern adopted into medical
Built `diabetic/cli/` mirroring `backend/cli/`: declarative `tui/manifest.py` (categories + commands + typed flags) → `dispatcher.py` routing → `commands/` handlers → rich `tui/engine.py`. Doc at `docs/engineering/tui_feature_map.md`. Contract test `ops/lab/test_cli_manifest.py` (manifest↔handler parity, no-stub gate) — closes the "no CLI tests" gap. 5 categories, 9 commands, all wired to existing code. Launch: `python -m diabetic.cli.tui` or `python -m diabetic.cli <cat> <cmd>`. Engine uses numbered selection (win32-robust) instead of arrow keys.

**Still open (vs finance):** settings-write subcommands (only `show`), universal `--json` (only status/settings), arrow-key + search navigation, "rerun last". Tracked in `tui_feature_map.md` Open Gaps.

### Original gap analysis — What finance does well → medical should adopt
- **Organized command subfolders**: `backend/cli/commands/research/`, `settings/`, `strategy/` with `index.js` re-exports. ~~Medical's `main.py` is a monolithic `sys.argv` switch~~ → DONE: `diabetic/cli/commands/`.
- **Contract test suite**: `sovereign_cli.test.js`, `cli_ui_contract.test.js`, `settings_contract.test.js` — one test file per command contract. ~~Medical has no CLI tests at all.~~ → DONE: `ops/lab/test_cli_manifest.py`.
- **TUI manifest pattern**: `backend/cli/tui/manifest.js` declares every TUI surface in one place; the engine drives it. ~~Medical's Telegram bot has no manifest~~ → DONE: `diabetic/cli/tui/manifest.py`.
- **`--json` flag for automation**: every command has a `--json` output mode for scripting. PARTIAL: `status` + `settings show` have it; rest still log-only.
- **Sectioned terminal reports**: backtest results render as boxed, columnar terminal output with color coding (yellow=sample, dim-green=live). Medical's CLI output is unstructured log lines.
- **`rerun last` category menu**: TUI remembers the last full args and exposes "Rerun last" as a menu item. Medical could use this for `/meal` repeat patterns.

### What medical does well → finance should adopt
- **Emergency fallback**: if the alert/decision engine throws, `coordinator.py:397–405` still fires a bare critical alert. Finance's CLI has no backstop — if a command handler throws, the user sees an uncaught exception stack.
- **Graceful shutdown sequence**: `coordinator.shutdown()` cancels background tasks in order (scheduler → background tasks → bot polling → ingestion clients → storage). Finance's process exit is abrupt.
- **Interactive Telegram bot with RLHF feedback loop**: `/meal`, `/start`, callback buttons for alert confirmation. Finance has no user interaction layer — all commands are CLI-only.

### Future (for both — website)
- **Shared command registry**: when adding a web UI, both projects should emit the same command objects to CLI, TUI, and web. Finance's manifest.js is the best existing pattern to extend.
- **Keyboard shortcuts**: finance already has keybindings. Medical's future web layer should adopt the same shortcut registration pattern.
- **Breadcrumb navigation**: finance's TUI category → command structure maps cleanly to a web sidebar nav. Reuse the manifest hierarchy for the web router.

---

## 5. MCP Tools

### PORTED 2026-06-05 — Bio-Quant MCP server (v1, read-only)
Built `diabetic/mcp/` (FastMCP, stdio). Tools, `bio_*`-namespaced per the note below, reuse existing code: `bio_ping` (liveness/inventory), `bio_health` (`get_system_health()`), `bio_config` (masked config). Registry `TOOL_SPECS` is the single source of truth; probe at `scripts/mcp_probe.py` (lists tools without a client); contract test `ops/lab/test_mcp_tools.py` (6). Run: `python -m diabetic.mcp`. DB-agnostic (reads through health/config), so a Mongo→Supabase move won't break it. **Still open:** mutating tools + auth-token gate (`BIO_MCP_TOKEN`), HTTP MCP-gated routes, `--mock` mode.

### Original gap analysis — What finance does well → medical should adopt
- **MCP server with 14 tools** (`backend/mcp_server/index.ts`): exposes portfolio state, backtest results, system status to Claude directly. ~~Medical has no MCP server~~ → DONE (3 read-only tools; `bio_*`).
- **HTTP MCP-gated API**: sensitive API routes (`/api/config`) require an MCP header; read-only routes (`/api/system/status`) do not. Medical's API has no equivalent gate.
- **stdio probe script** (`scripts/mcp_stdio_probe.js`): lists all tools and verifies the server starts cleanly without needing a full client. Medical should add an equivalent `python scripts/mcp_probe.py` that calls `healthz` and lists available tools.
- **Tool naming by domain**: `portfolio.*`, `backtest.*`, `strategy.*` — namespaced tool names prevent collision when multiple servers are loaded. Medical's future MCP tools should be `bio.*` namespaced.

### What medical does well → finance should adopt
- **Simulated data mode for tool testing**: `SimulationReader` replays historical data deterministically. Finance's MCP tools always hit live APIs — add a `--mock` or `SOVEREIGN_MOCK_MODE=true` to replay cached responses for tool testing.

### Future (for both — website)
- **Web → MCP bridge**: when adding a web UI, expose the same MCP tools over WebSocket so the browser can drive the same tool surface as Claude. Finance's architecture is already closest to this.
- **Tool authorization**: MCP tools that mutate state (place order, inject insulin, delete data) must require an authorization token. Finance already uses `SOVEREIGN_TRADE_PIN`; medical should add an equivalent.
- **Streaming tool responses**: long-running tools (backtest, training, backfill) should stream progress events rather than blocking. Both projects return synchronous responses today.

---

## 6. ML / Model Pipeline

### What medical does well → finance should adopt
- **Loss floor before deployment**: `train.py` rejects weights if `best_val > 2.0` MSE. Finance has no safety check before deploying new model weights.
- **Physiological/domain range clamp on outputs**: if predictions are outside `[2.0, 25.0]` mmol/L, weights are purged. Finance should add: if a trained model produces confidence scores outside `[0, 1]` or equity curves below -100%, reject the weights.
- **Hot-reload without service interruption**: `reload_weights()` swaps model weights on the running inference runner. Finance trains manually and restarts. Add hot-reload to finance's training pipeline.
- **Alpha Gating**: when CNN prediction diverges from kinematic baseline by > `ALPHA_GATE_DIVERGENCE_LIMIT` AND confidence < `ALPHA_GATE_CONFIDENCE_THRESHOLD`, use the simpler baseline. Finance should apply the same gate when C++ native signal and JS model signal diverge.
- **Two-channel contract enforcement**: `inference.py` and `train.py` are explicitly locked to the same 2-channel spec. Finance has no enforced contract between `models.js` features and `indicators.js` feature production.

### What finance does well → medical should adopt
- **Walk-forward validation**: rolling OOS windows vs single train/test split. Medical's autonomous training uses a fixed 80/20 split — add a rolling walk-forward that reports per-window loss before deploying.
- **Threshold calibration pass**: finance discovered the `cnn_window_v0` confidence never cleared 0.62 on real data and lowered the threshold. Medical should run a similar calibration: does the CNN prediction, after the Alpha Gate, actually improve over kinematic-only? Run a backtest over stored snapshots.
- **Model registry / version tracking**: finance tracks `ML_WEIGHTS_VERSION` (`v15`) and warns when version mismatch. Finance should add a model card (`config/models/v15_card.json`) with training date, dataset, validation loss, and intended use.

---

## 7. Web / Frontend (Future)

_Neither project has a production web frontend yet (finance has React/Vite scaffold; medical has only a TWA HUD). These are learnings to codify before building._

### From finance's React/Vite scaffold → medical
- **Vite + React** is the right choice for both projects. Finance's `Frontend/dashboard/` is the template.
- **Glassmorphism HUD pattern** (medical's `twa_api.py`): the TWA already serves a `/hud` endpoint with `HUDState`. Wire this to a Vite React app with the same endpoint contract.
- **`get_hud_data()` and `get_forecast()`** endpoints in `twa_api.py` are already a clean REST API — use them directly as the web backend without adding a new API layer.

### From medical's real-time architecture → finance
- **Server-Sent Events for live data**: medical already pushes updates to the frontend via `StatelessPush`. Finance's React dashboard has no real-time feed — add an SSE endpoint to `backend/api/app.js`.
- **Confidence index visualization**: medical tracks `snapshot.confidence_index` as a smoothed EMA. Finance's web dashboard should show a data-confidence badge alongside every chart panel.

### Shared patterns for future web builds
- **API-first, no business logic in React**: both medical (twa_api.py) and finance (app.js) correctly put all logic in the API layer. Keep React as a pure display layer.
- **Token-per-route, not global auth middleware**: medical uses `authorized_only` per Telegram handler; finance uses `PROTECTED_GET_ROUTES`. For web, apply per-route auth rather than a blanket middleware to allow public health/status endpoints.
- **Dark mode + responsive by default**: finance's Glassmorphism design is dark-mode native. Medical's HUD should match. Do not add light mode as an afterthought.
- **Chart libraries**: both projects use matplotlib (medical) and custom terminal charts (finance). For web: use Recharts (React native, zero-config) for medical biometrics; use TradingView lightweight-charts for finance OHLCV (better for financial time series).

---

## 8. Testing

### What finance does well → medical should adopt
- **Contract tests by surface**: one test file per command/feature contract (`sovereign_cli.test.js`, `cli_ui_contract.test.js`, `settings_contract.test.js`, `strategy_backtest_contract.test.js`). Medical's `ops/lab/` has only 5 tests with no contract organization.
- **Broad gate after every session**: `62/62 pass` before any commit. Medical should enforce: `pytest -q` passes before merging any change.
- **Structure contract test**: `structure_contract.test.js` verifies that generated/dependency paths are not tracked in git and that active entrypoints exist. Medical needs an equivalent that checks `ML_WEIGHTS_PATH` resolves to a real file at test time.
- **`--test-name-pattern` filtering**: run a subset of tests by name for focused regression. Medical's pytest already supports `-k` for this.

### What medical does well → finance should adopt
- **Empirical validation protocol**: medical's session journal records `input → transform → output → invariant` for each hypothesis (H1–H9). Finance's tests assert pass/fail without recording the evidence chain.
- **Simulation harness for data-independent tests**: `SimulationReader` replays deterministic data without needing live Nightscout. Finance's test suite relies on cached provider data that can go stale.

---

## 9. Session / Workspace Hygiene

### Finance's session hygiene (already mature)
- `workspace/HANDOFF.md` — current objectives + completed items
- `workspace/BLAST_THROUGH_REPORT.md` — rolling audit findings
- `workspace/DEV_REVIEW.md` — active reviewer decisions
- `workspace/NEXT_SESSION_GOAL.md` — next session's one-liner goal
- `workspace/FEATURE_TEST_MATRIX_*.md` — per-feature test evidence
- `docs/engineering/blast_through_checklist.md` — audit runbook
- `docs/engineering/architectural_debt.md` — long-lived structural debt
- `.gsd/STATE.md` — phase/posture mirror

### Medical's workspace (just initialized — add these over time)
- [x] `workspace/BOOTSTRAP.md`
- [x] `workspace/HANDOFF.md`
- [x] `workspace/SESSION_MEMORY.md`
- [x] `workspace/STATE.md`
- [x] `workspace/DEV_REVIEW.md`
- [x] `workspace/DEV_COMMENTS.md`
- [ ] `workspace/NEXT_SESSION_GOAL.md` — add after first work session completes
- [ ] `workspace/FEATURE_TEST_MATRIX.md` — add when integration tests are added
- [ ] `docs/engineering/` — add architecture doc once coordinator is decomposed

---

## 10. Infrastructure / DevOps

### What medical has → finance should note
- **Docker Compose** (`docker-compose.yml`): `mongodb`, `core`, and `twa` services. Finance has no container orchestration — add `docker-compose.yml` for `backend`, `frontend`, and `supabase-local`.
- **PID lock singleton** (`main.py`): `.bot.lock` with `psutil.pid_exists()` check prevents split-brain when process restarts. Finance has no equivalent for preventing duplicate bot/daemon processes.
- **`atexit` cleanup**: all cleanup paths (lock file, DB connections) are registered with `atexit`. Finance should add `process.on('exit', ...)` handlers for graceful gateway shutdown.

### What finance has → medical should note
- **Heroku `heroku.yml`**: finance is ready for Heroku container deployment. Medical's `RENDER_EXTERNAL_URL` config key suggests Render is the target — add a `render.yaml` or `Dockerfile` for one-click deploy.
- **CMakeLists.txt + Release build**: finance has a proper C++ build system. If medical ever adds a performance-critical native extension (e.g., Kalman filter in C++), use the same CMake pattern.
