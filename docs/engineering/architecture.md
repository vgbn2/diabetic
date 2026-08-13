# Bio-Quant — Architecture (web + auth)

Updated: 2026-08-12 · Current scope: personal (patient + caregiver), single pipeline.

The selected future target is a shared multi-tenant service, but no second patient
is supported today. See [tenancy-and-identity.md](tenancy-and-identity.md) for the
patient UUID, isolation, process, and scale gates that must precede onboarding.

## Domains
```
diabetic/                 backend (one Coordinator, one data pipeline)
  coordinator.py          orchestration
  ingestion/ dsp/ ml_engine/ storage/   data → smoothing → inference → persistence
  telegram_bot/           bot handlers + twa_api.py (FastAPI bridge, serves the web HUD)
  auth/                   NEW — web auth (Telegram WebApp initData verify + authorization)
  cli/  mcp/              operator CLI/TUI + MCP server (read-only tools)
twa/                      frontend (vanilla, FastAPI-served, no build step)
  index.html login.html settings.html history.html
  assets/ app.css auth.js api.js dashboard.js settings.js history.js
docs/engineering/         this doc + tui_feature_map.md
```

## Web auth flow (Telegram WebApp)
```
Telegram client ──opens Mini App──► twa/index.html (loads telegram-web-app.js)
  dashboard.js → apiFetch(path)
     adds header:  Authorization: tma <window.Telegram.WebApp.initData>
        │
        ▼
  FastAPI (twa_api.py)  endpoint guarded by Depends(require_twa_user)
     diabetic/auth/dependencies.require_twa_user
        ├─ scheme "tma"  → telegram_webapp.validate_init_data(initData, BOT_TOKEN, max_age)
        │     HMAC: secret = HMAC(b"WebAppData", bot_token); hash == HMAC(secret, data_check_string)
        │     + auth_date freshness  → returns {id, first_name, ...}
        ├─ scheme "dev"  → only if config.TWA_DEV_TOKEN set (browser testing)
        └─ authorization.is_authorized(user.id)
              patient (USER_ID) / caregiver (CAREGIVER_ID)
     → 200 (ok) · 401 (missing/invalid initData) · 403 (valid but not authorized)
```

Outside Telegram (plain browser) there is no `initData`, so `auth.js` redirects to
`/login`, which explains "open via the Telegram bot" and offers a dev-token field
(only useful when the server has `TWA_DEV_TOKEN` set).

## Page / API map
| Page (served) | Purpose | API used (all guarded) |
|---|---|---|
| `/` index.html | live HUD (glucose, velocity, carbs/IOB, 4h horizon) | `GET /api/v1/hud`, `GET /api/v1/forecast` |
| `/history` | recent glucose trace | `GET /api/v1/forecast` (points) |
| `/settings` | edit bio-traits | `POST /api/v1/calibration` |
| `/login` | auth gate | — |

## Config (diabetic/config.py)
- `USER_ID` (patient Telegram id), `CAREGIVER_ID` (optional) — the allow-list.
- `TWA_ALLOWED_ORIGINS` (CORS; empty = same-origin only), `TWA_DEV_TOKEN` (dev bypass),
  `TWA_AUTH_MAX_AGE_SECS` (initData replay window, default 86400).

## Security posture
- Every `/api/v1/*` endpoint requires a verified Telegram identity (was fully open).
- The mutating `POST /api/v1/calibration` is gated — the headline fix.
- CORS no longer `*` by default; the HMAC dependency is the real gate (CORS is defense-in-depth).
- VesselRegistry rows do not grant access to the singleton patient pipeline.
- Both patient and caregiver may submit calibration, which always targets `USER_ID`.
- Auth fails **closed**. `hmac.compare_digest` is used for hash and dev-token checks.

## Alert delivery contract

- Alert evaluation, delivery attempt, Telegram acceptance, audit persistence, and
  cooldown are distinct states.
- A same-type in-flight reservation prevents concurrent duplicate sends. Cooldown is
  committed only after Telegram returns an accepted message ID; rejected, unavailable,
  rate-limited, and ambiguous outcomes remain explicitly undelivered.
- Network timeouts are ambiguous and bounded retries may produce a duplicate message.
  Delivery is therefore at-least-once, not exactly-once; one opaque alert ID follows
  all attempts and feedback.
- Legacy feedback buttons remain readable, while new callbacks include the alert ID.

## Glucose event integrity

- Nightscout `_id` is the canonical source-event identity across REST and direct Mongo
  transports. Exact repeats have no clinical effect; pending corrections replace the
  event before processing, while corrections after processing are quarantined for
  bounded reconciliation.
- Live pending events are ordered by timestamp. Events older than the processed or
  in-flight watermark do not mutate the forward-only Kalman state and instead create a
  durable replay marker.
- Queue pressure never silently drops glucose. Before latest-first coalescing, SQLite
  records a machine-queryable source range in `replay_pending`; the bounded worker or a
  verified restart backfill transitions it to `replayed`.
- A generic clinical-processing exception is not retried in-process because the failed
  call may already have produced partial state or external side effects. The worker first
  records the exact event as `processing_failed`, stops admission, and terminates the live
  runtime. Process replacement then rebuilds state through side-effect-free warm-up and
  closes the durable gap only when verified provider history covers it.
- Cancellation before work acquisition is a clean worker stop. Cancellation after an event
  becomes in-flight records `processing_cancelled` before teardown; a failed marker write
  remains fatal and never marks the source event processed.
- Restart warm-up verifies and deduplicates up to 288 provider events, then rebuilds the
  filter with the latest 35 in chronological order. Warm-up performs no raw audit,
  provider context fetch, provider write, alert, forecast refresh, chart, or feedback
  side effect.
- Confidence is computed once from the current event-relative 90-minute history before
  neural alpha gating and alert evaluation.

## Model promotion recovery

- Candidate training writes only `.training/candidate.pth`; it never writes the deployed
  model directly. One process lock plus one non-blocking file lock owns preparation,
  replacement, activation, commit, and rollback.
- Preparation durably copies the current artifact and authoritative manifest, then
  writes a `prepared` journal containing both version identities. Artifact replacement
  and in-memory hot reload occur only after that journal is durable.
- `manifest.json` describes only the authoritative deployed artifact. Rejected/failed
  attempts are written separately to `last_attempt.json` and cannot invalidate the
  last-known-good manifest.
- Commit durably publishes the matching candidate manifest, then transitions the
  journal to `committed`. Cleanup is retryable and cannot turn a committed promotion
  into reported failure.
- Any in-process failure before commit restores the previous artifact, manifest, and
  loaded model while holding the same file lock. On restart, a `prepared` journal rolls
  back; a hash-matching `committed` journal finishes cleanup. Unrecoverable state fails
  neural inference closed before `torch.load`.

## Runtime state contracts
- `/healthz` is process liveness and remains the Compose healthcheck target.
- `/readyz` is core monitoring readiness: the authenticated Nightscout entries path
  is accepted, MongoDB responds, and the in-process coordinator has a fresh glucose
  snapshot. Rejected/rate-limited/misconfigured provider access is not ready.
- `neural_ready` is reported separately and requires fresh verified weights,
  successful in-process loading, and a 30-snapshot inference buffer.
- Treatment providers return explicit `ok` or `degraded` state. Fetch failure
  preserves only physiologically active last-known-good insulin/meal context.
- The legacy calendar resistance feature remains a neutral `1.0` model input
  for artifact-shape compatibility; weekends and holidays do not affect alerts
  or forecasts.

## Glucose unit boundary

- Every internal `GlucoseReading`, filter state, forecast, model input/output, and
  alert threshold uses mmol/L.
- `PREFER_MMOL` is a process-wide presentation preference only. REST, MongoDB, and
  historical replay never change their canonical internal values based on it.
- TWA, Telegram, and CLI adapters convert values and labels together at output. The
  browser consumes server-derived range and haptic states rather than reimplementing
  clinical thresholds in JavaScript.
- A per-patient display preference remains deferred until canonical patient profiles
  own UI settings.

## Profile and tenancy limits
- The current Registry schema is Telegram-keyed profile storage, not a multi-tenant
  isolation boundary.
- Saving calibration persists Registry values only. Active twin, forecaster, and
  CNN static inputs continue to use process configuration; restart alone does not
  activate Registry values.
- Multi-user pipelines, canonical patient UUIDs, versioned profile activation, and
  per-role access remain gated by the tenancy contract.
- A GET endpoint to pre-fill settings is not implemented.
