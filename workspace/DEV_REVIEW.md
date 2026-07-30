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

---

## 2026-07-23 Deep Blast-Through — Active Findings

Audit mode: **full, review-only**. No application behavior was changed. Current
promotion status is **blocked**.

### [R17] Unlabelled low SGV values are inverted from severe hypo to extreme hyper
**Severity:** **Critical**

**Files:** `diabetic/ingestion/nightscout.py:116-132`,
`diabetic/ingestion/mongo.py:150-153`, `diabetic/ingestion/mongo.py:365-381`

**Why:** Both REST and Mongo paths infer `raw < 40` to mean mmol/L when units are
absent. Nightscout-compatible SGV records are commonly stored in mg/dL. A
legitimate `sgv=39` mg/dL severe low is therefore emitted as `39 mmol/L`, which
can suppress the hypo path and present an extreme hyper value.

**Decision required:** Make the source contract explicit. Treat Nightscout `sgv`
as mg/dL by default, convert only when an authoritative unit field says mmol/L,
and reject ambiguous/non-physiological input rather than guessing.

**Verification gate:** Parameterized REST and Mongo parity tests for 39, 40, 41,
70, and explicit mmol-labelled records; assert that 39 mg/dL becomes about
2.16 mmol/L and still reaches the critical-hypo decision path.

### [R18] `TWA_DEV_TOKEN` is disclosed by the CLI and MCP config surfaces
**Severity:** **High**

**Files:** `diabetic/cli/commands/settings.py:10-31`,
`diabetic/mcp/server.py:36-47`, `diabetic/auth/dependencies.py:32-36`

**Why:** `_SECRET_KEYS` omits `TWA_DEV_TOKEN`. Both `settings show` and
`bio_config` return it in full. That same token is accepted as an authentication
bypass and assumes the configured patient identity, including access to the
mutating calibration endpoint.

**Decision required:** Use deny-by-default secret serialization (Pydantic secret
types or field metadata), include all credential-bearing fields, and disable the
dev scheme outside an explicit development profile.

**Verification gate:** Set unique sentinel values for every credential field;
assert none appear in CLI JSON, rich output, MCP output, logs, or exceptions.

### [R19] Synthetic weather and cardiac data enter clinical decisions as real telemetry
**Severity:** **High**

**Files:** `diabetic/config.py:17-18,83`,
`diabetic/ingestion/weather.py:17-26,32-52,76-109`,
`diabetic/ingestion/cardiac.py:43-47,59-103`,
`diabetic/registry.py:30-38`, `diabetic/coordinator.py:232-265`,
`diabetic/ingestion/mongo.py:109-120,186-209`,
`diabetic/ml_engine/inference.py:127-160,179-186`,
`diabetic/telegram_bot/decision_matrix.py:69-143`

**Why:** Weather mock mode defaults on and API failures silently fall back to a
Hanoi baseline. Heart-rate input defaults to `MOCK`, but generated readings keep
the model default `source="ble"`. The coordinator persists and consumes these
values without provenance gates; they influence context labels, neural features,
training data, and alert suppression/escalation.

**Decision required:** Add first-class provenance/quality fields, mark all mock
readings explicitly, never persist them into the clinical training corpus, and
make live mode fail closed or degrade visibly when real sensors/providers are
unavailable.

**Verification gate:** End-to-end tests proving mock/weather-fallback readings
cannot be labeled BLE, cannot enter the deployable training set, and cannot
change clinical alert behavior.

### [R20] Retraining can block live monitoring and destroy the last-known-good model
**Severity:** **High**

**Files:** `diabetic/ml_engine/train.py:41-173`,
`diabetic/ml_engine/scheduler.py:16-80`,
`diabetic/coordinator.py:497-540`, `diabetic/main.py:100-115`

**Why:** The async trainer performs the CPU/PyTorch training loop synchronously
after its initial database await, blocking the live event loop. Best epochs are
written directly to the deployed weight path before safety checks; rejection or
guard errors then unlink that path. There is no temporary candidate, atomic
promotion, rollback, or inter-owner lock. Both the scheduler and coordinator
maintenance loop can train the same artifact around the same configured hour;
only the scheduler hot-reloads it.

**Decision required:** Establish one training owner. Run training off the live
event loop, write a versioned candidate, validate it, atomically promote it under
a lock, preserve last-known-good weights, and reload only the promoted artifact.

**Verification gate:** Stress test concurrent scheduler/maintenance triggers,
failed guards, interruption during save, continued ingestion during training,
artifact checksum parity, and one successful hot reload.

### [R21] Cold and stale HUD data are rendered as live clinical state
**Severity:** **High**

**Files:** `diabetic/telegram_bot/twa_api.py:84-108`,
`twa/assets/dashboard.js:64-88`

**Why:** A cold engine returns HTTP 200 with `glucose=0.0`; the dashboard renders
it as a low and triggers haptic warning. Existing snapshots are returned
indefinitely with no age, freshness, or ready field, so stale values look live.

**Decision required:** Return an explicit availability/freshness contract and
never use numeric clinical sentinels. The UI must display unavailable/stale state
and suppress range classification and haptics unless the reading is fresh.

**Verification gate:** Browser/API tests for cold start, fresh data, stale data,
engine offline, and recovery.

### [R22] Treatment retention compares BSON dates against ISO-string records
**Severity:** **Medium**

**Files:** `diabetic/ingestion/nightscout.py:204-214`,
`diabetic/ingestion/mongo.py:157-165,337-359`,
`diabetic/coordinator.py:524-528`, `diabetic/config.py:88`

**Why:** Treatment ingestion and training expect `created_at` ISO strings, while
retention deletes with a BSON `datetime` cutoff. MongoDB type matching means
string-valued treatment records are not reliably selected by that date query.
The scheduled cleanup also hardcodes 180 days instead of `RETENTION_DAYS`.

**Decision required:** Normalize the stored schema or issue type-aware cleanup
queries during migration, then use the configured retention value everywhere.

**Verification gate:** Integration test with both ISO-string and BSON-date
treatments on both sides of the cutoff.

### [R23] Health reports configuration/handles as connectivity
**Severity:** **Medium**

**Files:** `diabetic/utils/db.py:35-60`, `diabetic/utils/health.py:21-47`

**Why:** Creating Motor collection handles performs no server ping, yet health
reports MongoDB `"ok"` whenever a handle exists. Nightscout is only reported as
configured. Model freshness is based on artifact mtime, which can be updated by
an unvalidated training candidate.

**Decision required:** Separate `configured`, `reachable`, `ready`, and
`degraded`; perform bounded live probes for readiness; identify the loaded model
by validated checksum/version rather than path mtime alone.

**Verification gate:** Health contract tests for invalid URI, unreachable host,
auth failure, stale CGM, missing/invalid/candidate weights, and a healthy stack.

### [R24] Deployment and repository reproducibility remain incomplete
**Severity:** **Medium**

**Files:** `README.md:40-67`, `docker-compose.yml:1-44`, `.gitignore:1-4`,
`run_graphify.py`, `.graphifyignore`

**Why:** `.env.example` is absent; the live `.env` uses `OPEN_WEATHER_KEY` while
the application reads `OPENWEATHER_API_KEY`; both MongoDB and Nightscout use
floating `latest` images and no healthchecks. The repository virtual environment
points to a deleted `/tmp` Python. Four ignored `.pyc` files remain tracked.
Graph tooling is untracked, has a `graphifyy` install typo, and will overwrite
the semantic graph with AST-only output when no API key is exported.

**Decision required:** Seal the environment contract, pin deployable image
versions/digests, add healthchecks, rebuild a local Python 3.11 environment, purge
tracked bytecode, and either harden/commit graph tooling or discard it.

**Verification gate:** Fresh clone/archive bootstrap, full 70-test suite,
Compose config plus healthy runtime on a Docker-capable host, and guarded
semantic graph refresh.

---

## 2026-07-23 R17-R24 Remediation Status

- **R17 CLEARED**: REST and Mongo use one SGV normalizer; missing units default
  to mg/dL and 39 mg/dL reaches critical-hypo logic.
- **R18 CLEARED**: config output is allowlisted and the dev token only works in
  an explicit development profile.
- **R19 CLEARED LOCALLY**: mock cardiac/weather readings carry synthetic
  provenance and cannot enter persisted deployable telemetry.
- **R20 CLEARED LOCALLY**: training runs off-loop, is serialized by process and
  file locks, validates a candidate, atomically promotes, preserves a backup,
  and exposes explicit CLI controls. Automatic training defaults off.
- **R21 CLEARED**: HUD/forecast report waiting/live/stale state and the browser
  suppresses clinical colors/haptics unless fresh.
- **R22 CLEARED**: treatment timestamps support millis, BSON dates, and ISO;
  cleanup batches legacy IDs and all retention owners use config.
- **R23 CLEARED LOCALLY**: bounded Mongo/Nightscout probes, model manifest
  checksum checks, and detail-free health/readiness endpoints are present.
- **R24 PARTIAL**: environment, locks, pinned Compose images, healthchecks,
  migration/backup tools, and cleanup are complete. Compose runtime and staged
  restore remain blocked by Docker socket permissions.

Verification: 85 tests plus 5 subtests passed; dependency check, compileall,
Compose config, shell syntax, migration hashes, and diff hygiene passed.

---

## 2026-07-24 Deep Blast-Through - New Active Findings

Audit mode: **full, review-only**. The R17-R24 implementation remains present,
but promotion is blocked by the following newly verified seams.

### [R25] Any registry user can access and mutate the single-patient pipeline
**Severity:** **Critical**

**Files:** `diabetic/auth/authorization.py:26-45`,
`diabetic/auth/dependencies.py:45-55`,
`diabetic/telegram_bot/twa_api.py:90-179`,
`docs/engineering/architecture.md:3,32-34,60-62`

**Why:** The architecture declares one patient pipeline, but `is_authorized`
accepts every user found in `VesselRegistry`. All guarded reads then return the
singleton coordinator's patient data, and calibration always writes to
`config.USER_ID` instead of the authenticated identity. A second registry user
can therefore read the primary patient's HUD/forecast and alter the primary
patient's traits.

**Decision required:** Keep the current single-patient contract and restrict
authorization to the patient/caregiver allowlist, or implement real per-user
pipeline ownership and bind every read/write to the authenticated user.

**Verification gate:** Add a second registry user and prove that user receives
403 for the primary pipeline and cannot mutate `config.USER_ID`; retain patient
and caregiver success tests.

### [R26] Untrusted adaptation and predicted cardiac output can suppress alerts
**Severity:** **High**

**Files:** `diabetic/telegram_bot/decision_matrix.py:28-55,69-95,157-161`,
`diabetic/coordinator.py:323-330`,
`diabetic/ml_engine/inference.py:202-207`

**Why:** When real cardiac telemetry is absent, the decision matrix treats the
CNN's predicted heart rate as current exercise evidence and can suppress a
predicted-hypoglycemia warning. Separately, three recent "false alarm" taps
raise the threshold for a current `CRITICAL_HYPER`, allowing values above the
medical constant to return no alert. Neither suppression is covered by the
active test suite.

**Decision required:** Never use model-predicted HR to suppress a safety alert;
require fresh, real cardiac provenance for exercise context. Keep current
critical glucose thresholds outside RLHF dampening, or constrain adaptation to
non-critical advisory alerts.

**Verification gate:** Decision-matrix tests for no cardiac data, predicted HR
above the exercise threshold, real fresh exercise telemetry, and three false
alarms at glucose values immediately above `HYPER_CRITICAL`.

### [R27] Treatment query failure is indistinguishable from no active treatment
**Severity:** **High**

**Files:** `diabetic/ingestion/nightscout.py:160-207`,
`diabetic/ingestion/mongo.py:84-125`,
`diabetic/coordinator.py:165-169,226-243`

**Why:** Both treatment providers convert errors into empty/`None` tuples. The
coordinator treats those tuples as successful reads and clears insulin/meal
context instead of preserving last-known-good state or marking the seam
degraded. This can understate IOB/COB and produce a misleading HUD or 4-hour
forecast during provider failure.

**Decision required:** Return an explicit success/degraded result contract,
preserve bounded last-known-good treatment context on fetch failure, and expose
its age/provenance.

**Verification gate:** Provider-failure integration tests proving fetch failure
is distinct from a valid empty result, active treatment state is retained only
within its physiological window, and degraded state reaches HUD/health output.

### [R28] System health can report ready with no fresh telemetry or active model
**Severity:** **Medium**

**Files:** `diabetic/utils/health.py:78-121`,
`diabetic/cli/commands/health.py:37-47`,
`docker-compose.yml:75-82`

**Why:** `get_system_health()["ready"]` only checks provider reachability and a
manifest-matched weight file. It ignores `last_reading_age_mins`,
`inference_weights_loaded`, and `inference_active`, and accepts stale weights.
The container healthcheck targets liveness-only `/healthz`, so Compose can
report healthy while clinical readiness is false.

**Decision required:** Separate liveness from readiness in Compose and make the
readiness contract require fresh CGM plus the explicitly chosen inference
policy. Do not label stale or unloaded model state ready.

**Verification gate:** Health and Compose tests for no readings, stale readings,
unloaded weights, stale weights, provider-only reachability, and a fully ready
stack; the service healthcheck must target the intended contract.

### [R29] Placeholder temporal multipliers are production model features
**Severity:** **Medium**

**Files:** `diabetic/medical_constants.py:90-93`,
`diabetic/utils/temporal.py:15-88`,
`diabetic/utils/scaling_engine.py:58-73`,
`diabetic/ml_engine/metabolic_dataset.py:104-112`,
`diabetic/ml_engine/inference.py:96-106,179-207`,
`diabetic/ml_engine/twin.py:63-96`

**Why:** Weekend/holiday/festival resistance values are labelled placeholder or
experimental in source, but they feed both training/live CNN static vectors and
digital-twin forecasts. The optional `holidays` dependency is undeclared, so
holiday behavior silently differs by environment. No tests validate the feature
or prove training/inference parity across those states.

**Decision required:** Remove these factors from deployable paths until they
have an evidence-backed contract, or make them explicit experimental features
that cannot influence clinical alerts.

**Verification gate:** Dependency parity plus controlled training/inference
tests for weekday/weekend/holiday states, with an approved rationale and a
feature flag that defaults off for clinical operation.

### [R30] Current executable and architecture evidence are stale
**Severity:** **Medium**

**Files:** `.venv/pyvenv.cfg`, `.venv/bin/python`, `README.md:42-58`,
`graphify-out/GRAPH_REPORT.md`, `graphify-out/manifest.json`,
`docs/architecture.md:48-75`, `run_graphify.py`, `.graphifyignore`

**Why:** The local Python 3.12 environment and the user-local `python3.12`
symlink both target a deleted `/tmp/hfp-uv-python` interpreter, so the 85-test
result cannot be reproduced today. The graph is dated 2026-06-05, contains
Windows checkout paths and the removed TWA service, while the architecture doc
still uses Windows `file:///` links and references a missing `ROADMAP.md`.

**Decision required:** Rebuild Python 3.12 from a durable interpreter, run the
suite from both working tree and clean archive, and refresh or explicitly retire
stale graph/docs evidence. Decide whether the untracked graph runner is
canonical tooling.

**Verification gate:** Current 85-test run plus subtests, package check, clean
archive run, Docker runtime proof, and a guarded graph refresh whose manifest
uses this checkout and cannot degrade semantic output.

## 2026-07-24 R25-R30 Implementation Result

- **R25 closed:** registry users are denied; patient and caregiver remain
  allowed; calibration intentionally targets the singleton `USER_ID`.
- **R26 closed:** critical current glucose alerts cannot be feedback-dampened;
  exercise suppression accepts only fresh real cardiac telemetry.
- **R27 closed:** typed provider state distinguishes valid empty data from
  degradation, REST fallback is active, and last-known-good treatment context
  expires at physiological boundaries.
- **R28 closed at code level:** core and neural readiness are separate and
  machine-readable; `/readyz` uses core readiness while `/healthz` remains
  liveness.
- **R29 closed:** calendar multipliers are neutral and no optional `holidays`
  branch remains; model feature width stays 15.
- **R30 partial:** Python and documentation evidence are current, but semantic
  graph and Docker/live runtime proof remain external.

Verification: focused `53 passed, 10 subtests`; full working tree and isolated
HEAD-plus-patch source each `105 passed, 10 subtests`; 81-package compatibility,
compileall, Compose config, shell syntax, diff hygiene, Git integrity, and model
hash checks pass.

## 2026-07-25 Historical-Data And Repository-Hygiene Audit

**Mode:** blast-through connective-tissue, Hard Reading Mode. Audit-only; no
clinical data, application code, or generated artifact was modified.

### [R31] The verified historical archive has no replay/test adapter
**Severity:** **High**

**Files:** `storage/migrations/from-2026-06-01/manifest.json`,
`storage/migrations/from-2026-06-01/entries.jsonl`,
`scripts/ops/migrate_nightscout.py:56-122`,
`diabetic/ingestion/offline/sim_reader.py:7-35`,
`diabetic/ml_engine/metabolic_dataset.py:36-60`, `ops/lab/`

**Why:** `storage/migrations/from-2026-06-01/` is the strongest real historical
source in this checkout: all six manifest hashes currently match, and the
archive contains 7,204 Nightscout entries plus one profile from June 5 through
July 1. It preserves canonical Extended JSON rather than an already transformed
CSV. No active test references it. `SimulationReader` accepts only a JSON array
despite claiming JSON/CSV support, so it cannot read JSONL or CSV; the CSV
dataset loader requires a `timestamp` column and cannot consume Mongo-exported
`timestamp_utc` chapters.

**Decision required:** Make the migration archive the source of truth, then add
a deterministic, de-identified replay-fixture builder that validates the
manifest and passes each entry through the production Nightscout normalizer.
Keep the full ignored archive out of unit tests; commit a bounded derived
fixture plus its source hash and expected invariants.

**Verification gate:** A test must verify source hash, record selection,
unlabelled-SGV mg/dL normalization, timestamp order, rejected-row count, and
replay output through the active ingestion boundary.

### [R32] CSV shadows obscure the canonical clinical chapters
**Severity:** **Medium**

**Files:** `storage/exports/*.csv`, `storage/exports/test_audit/*.csv`,
`storage/raw/exports/*.csv`,
`scripts/troubleshooting/clinical/storage/exports/test_audit/*.csv`,
`scripts/troubleshooting/infrastructure/storage/test_exports/*.csv`,
`scripts/analysis/neural_refresh_cycle.py:18-45`

**Why:** The four top-level `storage/exports/*.csv` chapters contain 11,781
unique, non-duplicated Mongo-derived readings from April 11 through May 27.
Every real row in the nested `test_audit`, troubleshooting, and raw-export
folders is a subset of those chapters. All 38,575 real rows stored in those
shadow folders duplicate canonical content, with 19,020 repeated occurrences
inside the shadow sets themselves. The three
infrastructure CSVs are the same two-row synthetic fixture under different date
range names.

`consolidated_training.csv` is not a valid consolidation: 3,987 rows populate
`timestamp/glucose`, while 3,274 different rows populate
`timestamp_utc/glucose_mmol_l`. The active dataset loader uses only
`timestamp`, so the clinical-export half is discarded.

**Decision required:** Treat `storage/exports/*.csv` as the sole legacy
clinical-CSV chapter set, label the two-row infrastructure files fixtures, and
quarantine or remove the redundant snapshot trees after preserving any needed
reproduction note.

**Verification gate:** One generated index/manifest must list chapter hashes,
schemas, source, time range, and non-overlap; a duplicate scan must report zero
unapproved shadows.

### [R33] The neural refresh script reports training success without training
**Severity:** **High**

**Files:** `scripts/analysis/neural_refresh_cycle.py:14-58`,
`diabetic/ml_engine/train.py:202-237`

**Why:** `train_metabolic_cnn` is async, but the script calls it without
`await` at line 50 and immediately prints `Training Complete`. Its input
consolidation also concatenates incompatible CSV schemas. The script has no
caller or regression test and can generate a forecast after a training no-op.

**Decision required:** Remove the obsolete orchestrator or rebuild it around
`run_training_pipeline` with an explicit source manifest and awaited result.
It must never print success unless a candidate was validated and promoted.

**Verification gate:** A subprocess test must fail on mixed schemas and prove
the awaited rejected/promoted result controls both exit status and subsequent
simulation.

### [R34] Historical-analysis utilities are stale or incomplete
**Severity:** **Medium**

**Files:** `scripts/tools/extract_historical.py:11-44`,
`scripts/analysis/check_csv_data.py:4-18`,
`scripts/verification/validate_v3_quality.py:4-25`,
`scripts/verification/validate_forensic_quality.py:4-29`,
`scripts/tools/visualize_lag.py:5-27`,
`scripts/troubleshooting/neural/verify_predictive_power.py:7-13`,
`scripts/analysis/neural_backtest_14day.py:10-80`,
`diabetic/ingestion/offline/sim_reader.py:7-35`

**Why:** The PDF extraction scripts still target `data/test/ottai_data`, while
the PDFs now live under `storage/raw/test/ottai_data`. Three CSV validators
hard-code an old Windows checkout and filenames that do not exist.
`visualize_lag` and `verify_predictive_power` require a missing
`synthetic_glucose_study.csv`. The backtest declares an unused legacy weights
path, swallows every inference exception, and writes to the old `data/` tree.
`SimulationReader` has no consumer and its CSV claim is false.

**Decision required:** Classify each script as supported developer tooling or
archive it. Supported tools need repo-root path resolution, explicit inputs,
nonzero failure exits, and smoke tests.

**Verification gate:** Run every retained script from a fresh checkout against
an explicit fixture; stale tools must be absent from active docs and audit
claims.

### [R35] Stage restore does not enforce the export hashes
**Severity:** **Medium**

**Files:** `scripts/ops/migrate_nightscout.py:98-122`,
`storage/migrations/from-2026-06-01/manifest.json`

**Why:** Export records SHA-256 for every collection, but `stage_restore`
checks only the staged document count. A valid-but-modified JSONL file with the
same number of records can pass staging. The current archive hashes were
independently rechecked and all match; the defect is in future enforcement.

**Decision required:** Verify every source file hash before opening the target
database or writing the first staging document.

**Verification gate:** Corrupt one byte without changing line count and prove
stage restore fails before connecting or writing.

### [R36] Storage/script audit claims are no longer trustworthy
**Severity:** **Low**

**Files:** `storage/AUDIT.md:3-13`, `scripts/AUDIT.md:3-18`,
`workspace/REVIEW_LEDGER.md`

**Why:** The storage audit calls all processed CSVs ground truth, and the script
audit calls missing-input utilities fully operational. The older orphan matrix
also reports a duplicate `diabetic/ingestion/sim_reader.py` that has already
been removed; only the incomplete offline reader remains.

**Decision required:** Replace blanket `SOLID` claims with the source
classification and verification status from this audit.

**Verification gate:** Documentation must distinguish source-preserving
clinical history, derived clinical CSVs, PDF-extracted estimates, fixtures, and
synthetic outputs.
