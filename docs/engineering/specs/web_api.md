# Web REST & WebSocket API Specification

> **Diátaxis Type**: Reference & Specification | **Status**: Canonical | **Owner**: Platform Engineering | **Review**: Continuous

The Bio-Quant TWA Gateway (`diabetic.telegram_bot.twa_api`) exposes REST endpoints and real-time WebSocket channels on Port 8000.

---

## 1. Authentication Protocols

The gateway supports three authentication mechanisms:

1. **SHA-1 API Secret (`api-secret`)**: Header-based SHA-1 hash matching `NIGHTSCOUT_API_SECRET` for Nightscout compatibility.
2. **Bearer Token (`Authorization: Bearer <token>`)**: JWT/Session token for web client and Telegram Mini App sessions.
3. **Tenant Device Secret (`X-Device-Key`)**: Per-device secret resolved dynamically via `VesselRegistry`.

---

## 2. REST Endpoints

### `GET /api/v1/entries`
Retrieves historical CGM readings or browser inspection data.

- **Query Parameters**:
  - `count` (*int*, default 10): Number of entries to retrieve.
  - `find[date][$gte]` (*int*, optional): Millisecond timestamp lower bound.
- **Response `200 OK`**:
```json
[
  {
    "_id": "65f0a1b2c3d4e5f6a7b8c9d0",
    "sgv": 112,
    "date": 1710288000000,
    "dateString": "2026-03-13T00:00:00.000Z",
    "direction": "Flat",
    "type": "sgv"
  }
]
```

### `POST /api/v1/entries`
Ingests continuous glucose readings.

- **Request Body**:
```json
[
  {
    "sgv": 118,
    "date": 1710288300000,
    "direction": "Flat",
    "type": "sgv"
  }
]
```
- **Response `200 OK`**: `{"status": "ok", "inserted": 1}`

### `GET /api/v1/hud/live`
Retrieves instantaneous HUD state formatted by `diabetic.ui.glucose_display`.

- **Response `200 OK`**:
```json
{
  "timestamp": "2026-03-13T00:05:00Z",
  "glucose": 6.2,
  "unit": "mmol/L",
  "velocity": 0.02,
  "range_state": "in_range",
  "confidence_index": 0.94,
  "forecast_30m": 6.3,
  "haptic_warning": false
}
```

### `GET /healthz`
Health check for Docker Compose and Kubernetes readiness probes.

- **Response `200 OK`**: `{"status": "healthy", "uptime_sec": 3600}`

---

## 3. WebSocket Real-Time Stream

### `WS /api/v1/ws/live`
Streams live `MetabolicSnapshot` updates every polling epoch.

- **Client Message (Ping)**: `{"action": "ping"}`
- **Server Message (Telemetry)**:
```json
{
  "event": "snapshot",
  "data": {
    "glucose": 6.2,
    "velocity": 0.02,
    "predicted_30m": 6.3,
    "predicted_4h": [6.3, 6.4, 6.2, 5.9],
    "risk_level": "NOMINAL"
  }
}
```
