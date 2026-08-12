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

## Runtime state contracts
- `/healthz` is process liveness and remains the Compose healthcheck target.
- `/readyz` is core monitoring readiness: Nightscout and MongoDB are reachable
  and the in-process coordinator has a fresh glucose snapshot.
- `neural_ready` is reported separately and requires fresh verified weights,
  successful in-process loading, and a 30-snapshot inference buffer.
- Treatment providers return explicit `ok` or `degraded` state. Fetch failure
  preserves only physiologically active last-known-good insulin/meal context.
- The legacy calendar resistance feature remains a neutral `1.0` model input
  for artifact-shape compatibility; weekends and holidays do not affect alerts
  or forecasts.

## Profile and tenancy limits
- The current Registry schema is Telegram-keyed profile storage, not a multi-tenant
  isolation boundary.
- Saving calibration persists Registry values only. Active twin, forecaster, and
  CNN static inputs continue to use process configuration; restart alone does not
  activate Registry values.
- Multi-user pipelines, canonical patient UUIDs, versioned profile activation, and
  per-role access remain gated by the tenancy contract.
- A GET endpoint to pre-fill settings is not implemented.
