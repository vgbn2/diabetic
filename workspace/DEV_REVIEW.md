# Developer Review Ledger
_Reviewer decisions required. Evidence-based. Updated: 2026-06-04_

---

## Active Review Items

### [R1] NightscoutClient.fetch_recent_treatments — 401 Fallback Silently Drops Data
**File:** `diabetic/ingestion/nightscout.py:211-223`  
**Why:** On 401 with token auth, the fallback retries the call with `api-secret` headers — but immediately discards the response and returns `([], [])` regardless of whether the retry succeeded. Treatment data is lost on the first 401 encounter; subsequent calls work correctly because `_is_token_mode` is now `False`.  
**Decision required:** Fix the fallback to parse and return the retried response, or accept one silent drop per auth-switch session.  
**Verification gate:** Treatment data appears in coordinator snapshots after a fresh 401 is encountered.  
**Severity:** Medium — affects meal and insulin data fidelity on Heroku-hosted Nightscout instances.

---

### [R2] main.py admin CLI — Hardcoded Retention Days
**File:** `diabetic/main.py:83`  
**Why:** `run_retention_cleanup(days=180)` is hardcoded in the admin `cleanup` CLI command; the comment says "fix later". `config.BACKFILL_MAX_HOURS` exists, but there's no `RETENTION_DAYS` config field for CLI override.  
**Decision required:** Add `config.RETENTION_DAYS` (default 180) or accept hardcode as intentional operational policy.  
**Verification gate:** CLI `cleanup` command respects the configured value.  
**Severity:** Low — cosmetic, but blocks per-deployment tuning.

---

### [R3] config.py — print() in validate_config()
**File:** `diabetic/config.py:156`  
**Why:** `print("Configuration validated: System ready.")` fires at boot but bypasses the structured logger, so it won't appear in remote log aggregators.  
**Decision required:** Replace with `logging.getLogger("Bio-Quant.Config").info(...)`.  
**Verification gate:** Boot message appears in logging output, not bare stdout.  
**Severity:** Low — cosmetic, no runtime impact.

---

### [R4] twa_api.py — Module-Level print
**File:** `diabetic/telegram_bot/twa_api.py:118`  
**Why:** `print("🚀 Bio-Quant TWA Bridge Interface Loaded.")` fires on every import.  
**Decision required:** Replace with `logger.info(...)` or remove.  
**Severity:** Low.

---

## 2026-06-05 Focused Audit — New Active Items

### [R5] requirements.txt removed `asyncpg` but Postgres path is still live
**Files:** `requirements.txt` (asyncpg dropped) ↔ `diabetic/storage/engine.py:22-30`, reached from `diabetic/coordinator.py:108`
**Why:** `requirements.txt` deleted `asyncpg>=0.29.0`, but `engine._build_url()` still rewrites any `DATABASE_URL` of the form `postgres://`/`postgresql://` to `postgresql+asyncpg://`, and `coordinator.__aenter__` calls `init_db()` unconditionally at boot. On any Heroku/Cloud Run deploy where `DATABASE_URL` is provisioned, `create_async_engine` will raise `ModuleNotFoundError: No module named 'asyncpg'`. The SQLite local fallback (aiosqlite, still present) is unaffected. `engine.py:5` docstring still claims "Supports SQLite (local dev) and PostgreSQL (Heroku/Cloud Run production)."
**Decision required:** (a) restore `asyncpg>=0.29.0` to requirements if Postgres is still a target, OR (b) if Postgres is being retired, also remove the asyncpg URL-rewrite branch in `engine.py`, update the module docstring, and confirm no Heroku Postgres add-on is provisioned.
**Verification gate:** With `DATABASE_URL=postgres://...` set, `python -m diabetic.main live` reaches `init_db()` without `ModuleNotFoundError`; OR the Postgres branch is gone and the docstring no longer promises it.
**Severity:** Medium — silent until a Postgres URL is present, then hard crash at coordinator boot. Internal inconsistency between infra manifest and storage layer.

---

### [R6] `_request_with_auth_retry` can return `None`, violating its `-> httpx.Response` contract
**File:** `diabetic/ingestion/nightscout.py:65-90` (`_request_with_auth_retry`)
**Why:** The 401-token-mode fallback does `continue`, which consumes a loop iteration. If the *first* 401 lands on the final attempt (`attempt == 2` — i.e. attempts 0 and 1 already failed with transient/non-401 errors), the `continue` exhausts `range(3)` and the function falls through, returning `None` implicitly. Callers: `fetch_recent_glucose` then calls `response.json()` on `None` → uncaught `AttributeError` (crash); `fetch_since` / `fetch_recent_treatments` swallow it via their generic `except Exception` → silent empty return + lost data with no error logged.
**Decision required:** Add an explicit `raise` after the loop (e.g. `raise RuntimeError("auth retry exhausted")`), or give the 401 fallback its own retry budget so it never silently exits.
**Verification gate:** A unit test where the first two attempts raise a transient error and the third raises a 401-in-token-mode asserts the method raises rather than returning `None`.
**Severity:** Low — narrow edge case (needs 2 prior transient failures then a first-time 401 on attempt 3), but the contract violation is real and one caller path crashes.

---

## Centralization Backlog

| Pattern | Files (count) | Proposed unit | Effort | Grade impact |
|---|---|---|---|---|
| Auth retry loop (3-attempt backoff + 401 fallback) | `nightscout.py` × 3 methods | Extract `_request_with_auth_retry(method, endpoint, params, headers)` → `nightscout.py` private helper | S (<2h) | B→A in nightscout.py |

---

## Cleared Items

### [R1] CLEARED — 2026-06-04
NightscoutClient auth retry centralized into `_request_with_auth_retry()`. `fetch_recent_treatments` now parses the fallback response instead of discarding it. One `return [], []` remains as the generic catch-all at the bottom.

### [R2] CLEARED — 2026-06-04
`RETENTION_DAYS: int = Field(180, validation_alias="BIO_RETENTION_DAYS")` added to `config.py`. `main.py` admin `cleanup` command now reads `config.RETENTION_DAYS`.

### [R3] CLEARED — 2026-06-04
`print("Configuration validated: System ready.")` replaced with `logging.getLogger("Bio-Quant.Config").info(...)` in `config.py:validate_config()`.

### [R4] CLEARED — 2026-06-04
Module-level `logger = logging.getLogger("Bio-Quant.TWA")` added to `twa_api.py`. Print replaced with `logger.info(...)`.

### Centralization Backlog — Auth retry — CLEARED — 2026-06-04
`_request_with_auth_retry()` extracted. Three duplicated retry blocks in `fetch_recent_glucose`, `fetch_since`, `fetch_recent_treatments` replaced.

### [R5] CLEARED — 2026-06-05
`asyncpg>=0.29.0` restored to `requirements.txt` (driver was dropped while `engine.py` still rewrites `DATABASE_URL`→`+asyncpg` and `coordinator.py:108` calls `init_db()` at boot). User chose to keep Postgres support; `engine.py` + docstring unchanged. Verified `import asyncpg` → 0.31.0 present in env; the missing requirements line would have broken fresh Heroku/Postgres deploys only.

### [R6] CLEARED — 2026-06-05
`_request_with_auth_retry` now ends with `raise RuntimeError("Auth retry exhausted ...")` instead of falling through to `None` when a 401 fallback consumes the final attempt. Restores pre-refactor semantics (`fetch_recent_glucose` propagates; `fetch_since`/`fetch_recent_treatments` degrade to empty via their `except Exception`). Regression test `test_auth_retry_exhaustion_raises_not_none` added to `ops/lab/test_nightscout_auth.py`. Suite: 28 passed / 2 skipped.

---

## 2026-06-05 Focused Audit — `diabetic/cli/` + `diabetic/mcp/` (new sections)

No bugs, no stubs, no security findings. Surface parity exact (10 handlers ↔ 10 manifest commands; 3 MCP tools ↔ TOOL_SPECS). Stub-scan hits were all false positives (`except: pass` ×2, a not-found `return None` sentinel). Two low-impact centralization items + a degraded path:

### Centralization Backlog (low impact — optional)
| Pattern | Files (count) | Proposed unit | Effort | Grade impact |
|---|---|---|---|---|
| Sim scenario wrappers (`crash`/`faint`/`normal` are identical except the literal) | `cli/commands/simulation.py` × 3 | one handler + `functools.partial(run_scenario, "crash")` in dispatcher | S | none (A− → A; abstraction barely beats 3 one-liners) |
| `--json` emit `print(json.dumps(obj, indent=2, default=str))` | `cli/commands/health.py` × 2, `settings.py` × 1 | `cli/_render.py: emit_json(obj)` | S | none |

> Both are judgment-call extractions; the duplication is trivial and the command identities are genuinely distinct. Do not extract unless a 4th instance appears.

### Degraded path (DCS Freshness)
**`graphify-out/` is STALE** — the graph (refreshed 2026-06-05, pre-CLI/MCP) contains no nodes for `diabetic/cli/`, `diabetic/mcp/`, `dispatcher`, `manifest`, or `bio_*` tools (636 new LOC unrepresented). **Verification gate:** re-run `/graphify`; graph report lists a CLI/TUI and an MCP community. This is the lowest DCS factor and the next non-feature action.

### Doc drift — FIXED this pass
`tui_feature_map.md` + `STATE.md` said "9 commands"; actual is 10. Corrected. Added the `diabetic` PS launcher to the feature-map Launching section.

---

## 2026-06-05 — Web auth hardening (`diabetic/auth/` + `twa/`)

### [S1] CLOSED — TWA bridge was fully unauthenticated (Critical → fixed)
**Was:** `diabetic/telegram_bot/twa_api.py` exposed `GET /api/v1/hud`, `GET /api/v1/forecast`, and a trait-**mutating** `POST /api/v1/calibration` with **no auth** and CORS `*` — anyone who reached the host could read metabolic data and rewrite the patient's bio-traits.
**Now:** every `/api/v1/*` endpoint is guarded by `Depends(require_twa_user)` → `diabetic/auth/`: Telegram `initData` HMAC verification (`telegram_webapp.validate_init_data`, `secret=HMAC(b"WebAppData", bot_token)`, `hmac.compare_digest`, `auth_date` freshness) + `authorization.is_authorized` (patient `USER_ID` / caregiver `CAREGIVER_ID` / VesselRegistry). CORS tightened to `config.TWA_ALLOWED_ORIGINS` (default same-origin). Auth fails **closed**. Dev bypass (`Authorization: dev <token>`) only when `TWA_DEV_TOKEN` is set.
**Evidence (TestClient probe):** no-auth → 401, bad dev token → 401, valid patient `tma` → 200, stranger `tma` → 403, **`calibration` no-auth → 401**, `/login` → 200. Unit tests: `ops/lab/test_twa_auth.py` (7: valid/tampered/wrong-token/stale/missing-hash/empty + authz).
**Follow-ups:** ~~bot `restrict_access` adopt shared `is_authorized`~~ **DONE 2026-06-05** — `handlers.py authorized_only` now delegates to `auth.is_authorized`; the duplicated allowlist+registry block was removed (suite 49 passed / 2 skipped). Remaining: add a GET endpoint to pre-fill `/settings` (new feature, deferred).

---

## 2026-06-27 Blast-Through — NEW findings

### [R9] All Phase 5 work is untracked — NEVER committed
**Files:** `diabetic/auth/`, `diabetic/cli/`, `diabetic/mcp/`, `diabetic/ml_engine/forecast.py`, `diabetic/utils/health.py`, `twa/login.html`, `twa/settings.html`, `twa/history.html`, `twa/assets/`, `ops/lab/test_alpha_gate.py`, `test_cli_manifest.py`, `test_forecast.py`, `test_ingestion_pipeline.py`, `test_mcp_tools.py`, `test_nightscout_auth.py`, `test_twa_auth.py`, `test_twa_calibration.py`, `scripts/simulation/stress_scheduler.py`, `scripts/mcp_probe.py`, `workspace/`
**Why:** `git status` shows every Phase 5 deliverable as `??` (untracked). The HANDOFF said "clean tree" but that was the state of the index — these files were never staged or committed. Any `git checkout .`, `git clean -fd`, or fresh clone loses the entire auth surface, CLI, MCP server, and 8 of 9 test files.
**Decision required:** Commit all untracked Phase 5 files (66 tests pass; code is solid). Stage in logical groups: (1) auth+deps, (2) cli+mcp, (3) forecast+health, (4) twa pages+assets, (5) tests, (6) workspace docs.
**Verification gate:** `git status` shows clean tree; `git clone` of the repo yields a working `python -m pytest ops/lab -q` → 66 passed.
**Severity:** **Critical** — a year of Phase 5 work is one `git clean` away from being wiped.

---

### [R10] COORDINATOR_REF always None in Docker — TWA bridge dead in production
**File:** `docker-compose.yml` (bio-quant-twa service) + `diabetic/telegram_bot/twa_api.py:82`
**Why:** The `bio-quant-twa` container runs `uvicorn diabetic.telegram_bot.twa_api:app` as a separate process. `COORDINATOR_REF` is a module-level variable that is only populated by `start_api(coordinator_instance)`, called from `diabetic.main`. The core engine and the TWA bridge are in **separate containers** with no shared memory or IPC. In production Docker, every `/api/v1/hud` returns the zero-glucose placeholder and every `/api/v1/forecast` returns `{"error": "Engine Offline"}`.
**Decision required:** One of: (a) run TWA inside the core container (same process, same COORDINATOR_REF); (b) add a lightweight IPC layer (Redis pub/sub, SSE stream, or shared volume JSON dump) so the TWA bridge reads from somewhere the core writes to; (c) convert `/api/v1/hud` to query the StatelessPush websocket or a shared storage record. Option (a) is the lazy correct fix — move the uvicorn start into `main.py` as a background thread alongside the live loop.
**Verification gate:** `docker-compose up` → `curl http://localhost:8000/api/v1/hud` returns non-zero glucose while core container is running live.
**Severity:** **High** — the entire TWA frontend is non-functional in the Docker production deployment.

---

### [R11] MetabolicScheduler is orphaned — never started, shutdown tries to cancel a ghost task
**File:** `diabetic/coordinator.py:833-838` + `diabetic/ml_engine/scheduler.py`
**Why:** `coordinator.shutdown()` does `if hasattr(self, '_scheduler_task') and self._scheduler_task: self._scheduler_task.cancel()`. But `_scheduler_task` is **never assigned** anywhere in coordinator (no `asyncio.create_task(MetabolicScheduler(...).run_forever())`). The attribute never exists, so the `hasattr` guard passes silently. `MetabolicScheduler.run_forever()` is dead — autonomous retraining never runs. The daily maintenance window in `_maintenance_loop` does call `train_metabolic_cnn`, so training happens once/day, but the MetabolicScheduler's staleness-check logic (7-day threshold, separate window) is completely unreachable.
**Decision required:** Either (a) start `MetabolicScheduler` from `start_live_mode` and assign `self._scheduler_task = asyncio.create_task(...)`, or (b) delete `scheduler.py` and the orphaned shutdown block — `_maintenance_loop` already handles retraining. Option (b) is simpler; the scheduler is redundant.
**Verification gate:** `python -m diabetic.main live` logs `[Scheduler] Automated Metabolic Training Scheduler initialized.` on startup, or `scheduler.py` is deleted and `coordinator.py:833-838` is cleaned up.
**Severity:** Medium — no silent data loss, just dead code and misleading shutdown logic.

---

### [R12] train.py anti-hallucination guard uses torch.load without weights_only=True
**File:** `diabetic/ml_engine/train.py:154`
**Why:** `model.load_state_dict(torch.load(weight_path))` in the physiological guard block (lines 153-171) omits `weights_only=True`, while the inference runner's equivalent call (`inference.py:36`) correctly includes it. PyTorch `weights_only=False` allows arbitrary pickle deserialization — low risk since these weights were just saved by the same process, but the inconsistency means the guard's `torch.load` will emit a FutureWarning in PyTorch ≥2.0 and will break when `weights_only=True` becomes the default.
**Decision required:** Add `weights_only=True` to `train.py:154`.
**Verification gate:** `python -m diabetic.ml_engine.train --source csv` completes without FutureWarning; inference test suite still passes.
**Severity:** Low — low practical risk; trivial fix.

---

### [R13] MetabolicScheduler hardcodes 3AM, ignoring config.MAINTENANCE_LOCAL_HOUR
**File:** `diabetic/ml_engine/scheduler.py:34`
**Why:** `target = now.replace(hour=3, ...)` hardcodes the training window. `config.MAINTENANCE_LOCAL_HOUR` exists and is used by `coordinator._maintenance_loop()`. If the scheduler were ever started (see R11), it would ignore any `BIO_MAINTENANCE_HOUR` env override. Minor, since R11 means this code never runs, but it should be fixed alongside R11 if the scheduler is kept.
**Decision required:** Replace `hour=3` with `hour=config.MAINTENANCE_LOCAL_HOUR` (only matters if R11 resolves to "start the scheduler").
**Severity:** Low — dormant (R11 blocks reachability).

---

## 2026-06-05 Blast-Through (review-only pass) — NEW findings

### [R7] POST /api/v1/calibration calls a non-existent registry method — guaranteed 500 on first real use
**File:** `diabetic/telegram_bot/twa_api.py:128`
**Sink:** `success = await COORDINATOR_REF.vessel_registry.update_user_traits(config.USER_ID, traits)`
**Why:** `VesselRegistry` (`diabetic/storage/vessel_registry.py`) has **no `update_user_traits`**. Its only biometric writer is `update_biometrics(telegram_id, *, age, height_cm, weight_kg, diabetes_type, diagnosis_year)` (typed keyword args). The endpoint is broken in three layers:
  1. **AttributeError** on the missing method the instant a real `COORDINATOR_REF` is attached and any authed patient hits Save → FastAPI 500.
  2. Even if renamed to `update_biometrics`, the call passes a **positional `traits` dict**; `update_biometrics` takes keyword args → TypeError.
  3. Frontend `twa/assets/settings.js:11-16` sends `insulin_sensitivity`, which has **no `BioTraits` column and no `update_biometrics` param** → silently unsupported even after a correct rename.
**Why tests miss it:** `ops/lab/test_twa_auth.py` asserts only auth status codes. The calibration path in those probes runs with `COORDINATOR_REF=None`, so it returns 503 *before* reaching the missing method. No test drives the real DB write — this is the test gap that let it ship.
**Reachability:** Fully wired — `twa/assets/settings.js:23` POSTs `readForm()` on the Save button / Telegram MainButton. This is the flagship "Bio-Traits editor" feature.
**Note on prior S1:** the auth hardening (correctly) guards this endpoint, but it guards a function that cannot work. "Trait-mutating POST" in the S1 note is aspirational — it 500s before mutating.
**Decision required:** Implement `VesselRegistry.update_user_traits(telegram_id, traits: dict)` as a **whitelisting** wrapper over `update_biometrics` (accept only `{age, height_cm, weight_kg, diabetes_type, diagnosis_year}` — never blind `setattr`, which would be mass-assignment). Decide whether `insulin_sensitivity` becomes a real `BioTraits` column or is dropped from the frontend.
**Verification gate:** Integration test (temp-SQLite registry, no mock DB per repo rule): authed patient POSTs `{age, weight_kg, height_cm}` → 200 `{"status":"success"}` AND `get_biometrics()` reflects the new values; unknown keys are ignored, not 500.
**Severity:** **High** — the primary settings feature is non-functional on the real path; only masked because no test exercises it with a live coordinator.

---

### [R8] twa_api static dir resolved from CWD, not project root
**File:** `diabetic/telegram_bot/twa_api.py:32` — `TWA_DIR = os.path.join(os.getcwd(), "twa")`
**Why:** Violates the repo hard constraint "absolute paths resolved from project root" — `config.py` already does this for ML weights via `Path(__file__).resolve()`. Launched from any CWD other than repo root (systemd unit, packaged run, `python -m` from a subdir), `/assets` won't mount and `_serve_page` returns `{"error": "<name> not found"}` JSON instead of the HUD/login/settings/history pages. Docker sets `WORKDIR /app` so the container masks this; it bites local and non-Docker launches.
**Decision required:** Resolve from `Path(__file__).resolve().parents[2] / "twa"` (project root), matching `config.py`.
**Verification gate:** From a temp CWD, `python -m diabetic.main live` → `GET /` returns index.html and `GET /assets/app.css` → 200.
**Severity:** Medium — latent; only fails outside Docker/root-CWD launches.

---

### [R7] CLEARED — 2026-06-05
Added `VesselRegistry.update_user_traits(telegram_id, traits: dict) -> bool` (`vessel_registry.py`) — a **whitelisting** wrapper over `update_biometrics`. `_ALLOWED_TRAIT_FIELDS` frozenset (`{age, height_cm, weight_kg, diabetes_type, diagnosis_year}`) is the mass-assignment guard: unknown keys + None values are dropped before reaching the ORM (unfiltered, they would `TypeError` in `update_biometrics(**...)`). Empty-after-filter → `False` (no phantom success). `twa_api.py` calibration error message corrected ("Database Lock" → "Profile not found or no valid fields"). Frontend `insulin_sensitivity` dropped (no `BioTraits` column; ISF is twin-learned) — removed from `settings.js readForm()` + `settings.html` form-row. New integration test `ops/lab/test_twa_calibration.py` (3, temp-SQLite, no mock): round-trip persistence + bmi, whitelist-drops-unknown, empty/unknown-only no-op. **Closed the test gap** (auth probes ran with `COORDINATOR_REF=None` → 503 before the dead call). Suite **51 passed**.

### [R8] CLEARED — 2026-06-05
`twa_api.py` `TWA_DIR` now `str(Path(__file__).resolve().parents[2] / "twa")` (project root, matches `config.py` ML-weight pattern). Verified CWD-independence: from `C:\Users\Lenovo`, resolves to repo `twa/` with `index.html` present (old `os.getcwd()` form would have produced the nonexistent `C:\Users\Lenovo\twa`).

---

## 2026-07-18 Research -> Plan -> Mass-Implement

### [R14] CLEARED (`a8bd5f4`) — configured v15 artifact absent from clean HEAD
**Files:** `diabetic/config.py`, `diabetic/ml_engine/weights/diabetic_cnn_v15.pth`, `diabetic/ml_engine/inference.py`, `ops/lab/test_runtime_contract.py`

**Why:** `config.ML_WEIGHTS_VERSION` selected v15, but `git archive HEAD` contained only v14. The runner continued with random weights when the selected file was absent. Official Docker documentation confirms an empty named volume copies existing image content by default, so the first-boot root cause was the absent source artifact, not volume initialization.

**Implementation:** Added v15 to the scoped batch; introduced `weights_loaded`; neural inference now returns the existing sentinel fallback when weights are missing or invalid.

**Evidence:** `torch.load(..., weights_only=True)` produced 14 keys; `DiabeticCNN.load_state_dict` reported zero missing and zero unexpected keys. Missing-weight regression test passes.

**Verification:** Committed `HEAD` archive passed `python -m pytest ops/lab -q`: 70 passed in 5.70s.

### [R15] CLEARED (`a8bd5f4`) — runtime and test dependencies were undeclared
**Files:** `requirements.txt`, `requirements-dev.txt`, `diabetic/main.py`, `diabetic/telegram_bot/twa_api.py`

**Why:** Production directly imports `psutil`, `fastapi`, and `uvicorn`; tests require `pytest` and `pytest-asyncio`. The corresponding manifests did not directly declare them.

**Implementation:** Declared all direct runtime dependencies; made `requirements-dev.txt` include runtime requirements plus the test runner.

**Evidence:** Isolated Python 3.11.15 environment resolved 130 packages; compatibility check passed; 70 tests passed.

**Verification gate:** Fresh environment install from `requirements-dev.txt`, dependency compatibility check, and full suite.

### [R16] PARTIAL — repository status polluted by line-ending and generated-artifact drift
**Files:** `.gitattributes`, `.gitignore`, tracked text files, `run_graphify.py`, `.graphifyignore`

**Why:** Seventy files contained no semantic source delta but produced 7,805 whitespace findings. Local Claude settings and graph chunk lists were unignored.

**Implementation:** Added LF policy with Windows-script exceptions, normalized CRLF-only changes, and ignored confirmed local residue.

**Remaining decision:** Decide whether `run_graphify.py` and `.graphifyignore` are canonical tooling or disposable generated artifacts. They were left untracked and unchanged.

**Verification gate:** `git diff --check` is clean; after commit, `git status --short` contains only intentionally retained untracked tooling.
