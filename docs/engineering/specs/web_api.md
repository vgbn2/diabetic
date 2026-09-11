# Web REST API Specification

> **Diátaxis Type**: Reference & Specification | **Status**: Canonical | **Owner**: Platform Engineering | **Review**: Continuous

The Bio-Quant TWA Gateway (`diabetic.telegram_bot.twa_api`) exposes REST endpoints for Telegram Mini App (TWA) HUD interfaces and Nightscout-compatible CGM ingress on Port 8000.

---

## 1. Authentication Protocols

The gateway supports three fail-closed authentication mechanisms:

1. **Telegram Mini App initData (`Authorization: tma <initData>`)**: Validates Telegram HMAC-SHA256 signatures against `TELEGRAM_BOT_TOKEN`.
2. **Nightscout SHA-1 Secret (`api-secret` header or `?secret=<token>`)**: Header- or query-based raw secret or SHA-1 hash matching `API_SECRET` or the tenant's device secret hash.
3. **Development Token (`Authorization: dev <token>`)**: Optional loopback/browser testing token matching `TWA_DEV_TOKEN`.

---

## 2. Ingress & Telemetry Endpoints

### `POST /api/v1/entries` and `POST /t/{slug}/api/v1/entries`
Ingests continuous glucose readings from xDrip+, Ottai, or Nightscout uploader clients.

- **Authentication**: Required (`api-secret` header, query `?secret=...`, or TMA session).
- **Request Body**: Single object or array of objects:
```json
[
  {
    "sgv": 118,
    "date": 1710288300000,
    "dateString": "2026-03-13T00:05:00.000Z",
    "direction": "Flat",
    "type": "sgv"
  }
]
```
- **Response `200 OK`**: `{"status": "ok", "tenant": "default", "inserted": 1}`

### `GET /api/v1/entries` and `GET /t/{slug}/api/v1/entries`
Retrieves recent readings in reverse chronological order.

- **Authentication**: Required.
- **Query Parameters**:
  - `count` (*int*, default 10): Number of entries to retrieve.
- **Response `200 OK`**: Array of Nightscout SGV entries.

---

## 3. HUD & Configuration Endpoints

### `GET /api/v1/hud` and `GET /t/{slug}/api/v1/hud`
Retrieves instantaneous HUD state and forecast horizons.

- **Response `200 OK`**:
```json
{
  "state": "live",
  "glucose": 6.2,
  "velocity": 0.02,
  "predicted_30m": 6.3,
  "points": [6.0, 6.1, 6.2],
  "horizon": [6.3, 6.4, 6.2],
  "horizon_1d": [6.5, 6.6, 6.4]
}
```

### `GET /api/v1/client/cgm_config` and `GET /t/{slug}/api/v1/client/cgm_config`
Retrieves pre-computed client connection parameters for xDrip+/Nightscout configuration.

- **Authentication**: Required (`require_twa_user`).
- **Response `200 OK`**:
```json
{
  "tenant_slug": "tam",
  "direct_upload_url": "https://bioquant.example.com/t/tam/api/v1/entries?secret=...",
  "instructions": "Enter direct_upload_url in xDrip+ Cloud Upload settings."
}
```

### `GET /healthz` and `GET /readyz`
Health check and readiness probes for container runtime monitoring.

- **Response `200 OK`**: `{"status": "healthy"}` / `{"status": "ready"}`
