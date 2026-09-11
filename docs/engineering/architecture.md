# Bio-Quant — Core System Architecture & Engineering Contracts

Updated: 2026-09-11 · Current scope: personal (patient + caregiver), single pipeline.

The selected future target is a shared multi-tenant service. See [tenancy_and_identity.md](specs/tenancy_and_identity.md) for the patient UUID, isolation, process, and scale gates.

---

## 1. System Topology & Module Domains

```
diabetic/                           backend (one Coordinator, one data pipeline)
  ├── coordinator.py                orchestration, state machine, lifecycle management
  ├── config.py                     pydantic settings, environment validation
  ├── registry.py                   domain models (GlucoseReading, MetabolicSnapshot, etc.)
  ├── medical_constants.py          physiological boundaries, risk thresholds, unit conversions
  ├── operations/                   discrete business operations
  │     └── retention.py            bounded, truthful retention cleanup orchestration
  ├── ingestion/                    telemetry ingestion & validation
  │     ├── nightscout.py           Nightscout REST adapter with retry & token fallback
  │     ├── mongo.py                MongoDB client for clinical telemetry
  │     └── event_integrity.py      stream watermark & gap tracking
  ├── dsp/                          digital signal processing
  │     ├── kalman.py               3D kinematic Kalman filter [g, v, a]
  │     ├── signal_quality.py       spike rejection & sensor jitter analysis
  │     └── metabolic_math.py       Kovatchev risk space transforms [HBGI, LBGI, RI]
  ├── ml_engine/                    inference, forecasting & training
  │     ├── twin.py                 physical-chemical digital twin (meal & insulin decay)
  │     ├── inference.py            PyTorch 1D-CNN inference with fail-closed weight verification
  │     ├── forecast.py             4h & 24h trajectory projections
  │     └── training_service.py     atomic candidate promotion & rollback
  ├── storage/                      SQL persistence & vessel registry
  │     ├── engine.py               async SQLAlchemy engine & session factory
  │     ├── models.py               ORM definitions (VesselRegistry, TelemetryAudit)
  │     └── vessel_registry.py      biometric profiles & tenant secret lookups
  ├── telegram_bot/                 alert dispatch & mini app API
  │     ├── decision_matrix.py      safety shield & alert decision rules
  │     ├── notifier.py             Telegram Bot notification manager & feedback loops
  │     └── twa_api.py              FastAPI bridge serving Web HUD & Nightscout compatibility
  ├── auth/                         identity verification & role authorization
  │     ├── telegram_webapp.py      Telegram WebApp initData HMAC-SHA256 validation
  │     ├── dependencies.py         FastAPI dependency require_twa_user
  │     └── authorization.py        patient/caregiver role verification
  ├── ui/                           presentation authority & CLI HUD
  │     ├── glucose_display.py      canonical unit conversions, velocity & range formatting
  │     └── cli_hud.py              terminal dashboard (Rich)
  └── cli/                          operator command-line interface & TUI
        ├── dispatcher.py           POSIX argument parser & command routing
        ├── tui/manifest.py         declarative manifest (6 categories, 12 commands)
        └── commands/               administrative, operational & ML handlers
```

---

## 2. Coordinator Lifecycle & State Machine

The `Coordinator` orchestrates ingestion, signal processing, neural inference, alerting, and persistence under strict lifecycle guarantees.

### Lifecycle States

| State | Description | Invariants & Transitions |
|---|---|---|
| `created` | Instance initialized with dependencies. | `is_running = False`. Can transition to `starting` via `begin_start()`. |
| `starting` | Startup claim established; components initializing. | Cannot start a second time. Transitions to `running` on `start_live_mode()`. |
| `running` | Telemetry loop and background tasks active. | `is_running = True`. Background tasks tracked in `background_tasks` set. |
| `failed` | Runtime encountered fatal error. | Set via `mark_failed()`. Live admission stopped; triggers shutdown. |
| `stopped` | Terminal state; all background tasks drained, connections closed. | `is_running = False`, `_shutdown_complete = True`. Restart prohibited without process replacement. |

```
                     ┌──────────────────┐
                     │     created      │
                     └────────┬─────────┘
                              │ begin_start()
                              ▼
                     ┌──────────────────┐
                     │     starting     │
                     └────────┬─────────┘
                              │ start_live_mode()
                              ▼
  ┌────────────────────────────────────────────────────────┐
  │                        running                         │
  └─────────────┬───────────────────────────┬──────────────┘
                │ mark_failed()             │ shutdown()
                ▼                           ▼
        ┌───────────────┐           ┌───────────────┐
        │    failed     │──────────►│    stopped    │
        └───────────────┘ shutdown()└───────────────┘
                                     (terminal)
```

---

## 3. End-to-End Execution Workflows

### 3.1 Live Ingestion, Processing & Alert Dispatch Sequence

```
Nightscout / Mongo      Coordinator           DSP (Kalman)          ML Engine (Twin/CNN)     Decision Matrix      Telegram Notifier / TWA
       │                     │                     │                        │                       │                        │
       │  Poll Telemetry     │                     │                        │                       │                        │
       ├────────────────────►│                     │                        │                       │                        │
       │                     │ _stage_signal_quality                       │                       │                        │
       │                     ├────────────────────►│                        │                       │                        │
       │                     │◄────────────────────┤ (Quality OK)           │                       │                        │
       │                     │                     │                        │                       │                        │
       │                     │ Filter & Kinematics │                        │                       │                        │
       │                     ├────────────────────►│                        │                       │                        │
       │                     │◄────────────────────┤ MetabolicSnapshot [g,v,a]                      │                        │
       │                     │                     │                        │                       │                        │
       │                     │ Compute Predictions │                        │                       │                        │
       │                     ├─────────────────────────────────────────────►│                       │                        │
       │                     │◄─────────────────────────────────────────────┤ 30m / 4h / 24h Proj   │                        │
       │                     │                     │                        │                       │                        │
       │                     │ Evaluate Safety     │                        │                       │                        │
       │                     ├─────────────────────────────────────────────────────────────────────►│                        │
       │                     │◄─────────────────────────────────────────────────────────────────────┤ Alert Decision         │
       │                     │                     │                        │                       │                        │
       │                     │ Dispatch Updates & Background Tasks          │                       │                        │
       │                     ├──────────────────────────────────────────────────────────────────────────────────────────────►│ (HUD / Alert Push)
       │                     │                                                                                               │
```

### 3.2 Single-Claim Startup & TWA Thread Supervision

```
  main.py (Supervisor)            Coordinator                 TWA API Thread (Uvicorn)
         │                             │                                 │
         │ Coordinator.create()        │                                 │
         ├────────────────────────────►│ (state: created)                │
         │                             │                                 │
         │ begin_start()               │                                 │
         ├────────────────────────────►│ (state: starting)               │
         │                             │                                 │
         │ _start_twa_thread()         │                                 │
         ├─────────────────────────────┼────────────────────────────────►│ Start Uvicorn Server
         │ (stores _twa_failure future)│                                 │
         │                             │                                 │
         │ _run_live_with_twa_supervision()                              │
         ├────────────────────────────►│ start_live_mode() (running)     │
         │                             │                                 │
         │ ◄═══ asyncio.wait([live_task, twa_failure]) ════════════════► │ (Supervision Barrier)
         │                             │                                 │
         │ [If TWA crashes]            │                                 │
         │ ◄───────────────────────────┼─────────────────────────────────┤ sets exception on future
         │ Cancel live_task            │                                 │
         ├────────────────────────────►│ mark_failed()                   │
         │ coordinator.shutdown()      │                                 │
         ├────────────────────────────►│ drain & close all resources     │
```

### 3.3 Background Task Tracking & Graceful Draining

All async tasks created outside the primary event loop step are registered with `track_background_task()` to prevent GC deallocation and ensure bounded draining during shutdown.

```
Caller Coroutine                 Coordinator.track_background_task()        Coordinator.shutdown()
       │                                         │                                      │
       │ coro_or_task                            │                                      │
       ├────────────────────────────────────────►│                                      │
       │                                         │ task = asyncio.create_task()         │
       │                                         │ background_tasks.add(task)           │
       │                                         │ task.add_done_callback(discard)      │
       │                                         │                                      │
       │                                         │                   Shutdown Initiated │
       │                                         │                   ──────────────────►│
       │                                         │                                      │ drain_background_tasks(timeout=5.0)
       │                                         │                                      │ await asyncio.wait_for(gather)
       │                                         │◄─────────────────────────────────────┤
       │                                         │ [If timeout]: cancel pending tasks   │
       │                                         │ background_tasks.clear()             │
```

---

## 4. Web Authentication & Tenant Ingress

```
Telegram Client               TWA Frontend (HTML/JS)              FastAPI (twa_api.py)             Auth Dependency
      │                                 │                                  │                              │
      │ Open WebApp                     │                                  │                              │
      ├────────────────────────────────►│ window.Telegram.WebApp.initData  │                              │
      │                                 │                                  │                              │
      │                                 │ GET /api/v1/hud                  │                              │
      │                                 │ Authorization: tma <initData>    │                              │
      │                                 ├─────────────────────────────────►│                              │
      │                                 │                                  │ Depends(require_twa_user)    │
      │                                 │                                  ├─────────────────────────────►│
      │                                 │                                  │                              │ Validate HMAC-SHA256
      │                                 │                                  │                              │ Check auth_date max_age
      │                                 │                                  │                              │ Check authorized ID
      │                                 │                                  │◄─────────────────────────────┤ (200 User / 401 / 403)
      │                                 │◄─────────────────────────────────┤ Return HUD Snapshot          │
```

### Ingress Validation Rules
- **TMA Scheme**: `Authorization: tma <raw_init_data>` validates cryptographic signature using HMAC-SHA256 with key `HMAC_SHA256("WebAppData", bot_token)`.
- **Dev Bypass**: `Authorization: dev <token>` allowed only if `config.TWA_DEV_TOKEN` is configured on the server.
- **Constant-Time Verification**: `hmac.compare_digest` used for all token and signature checks.
- **Projection Release**: `clear_api_coordinator(owner)` ensures `COORDINATOR_REF` is set to `None` on shutdown if the caller owns the reference.

---

## 5. Persistence, Audit Durability & Retention

### 5.1 Typed Audit Logging (`AuditWriteResult`)

The `AuditLogger` dual-writes to local SQLite (WAL mode) and MongoDB. All audit write operations return a structured `AuditWriteResult`:

```python
@dataclass(frozen=True)
class AuditWriteResult:
    local_persisted: bool = False
    mongo_persisted: bool = False

    @property
    def durable(self) -> bool:
        """Returns True if persisted to at least one reliable store."""
        return self.local_persisted or self.mongo_persisted
```

### 5.2 Truthful Bounded Retention Operations

Data retention is orchestrated through `execute_retention_cleanup()`:
- **Bound Enforcement**: Validates `1 <= days <= 3650`.
- **Pre-Audit Verification**: Pre-audit event must achieve `result.durable == True`.
- **Phased Execution**: Mongo entries deleted first, followed by treatments. Partial failures report `RetentionCleanupResult(state="partial")`.
- **Post-Audit Completion**: Audit event logs complete statistics upon completion.

```
CLI / Coordinator                 execute_retention_cleanup()               AuditLogger                 MongoDBClient
       │                                       │                                 │                            │
       │ days = 180                            │                                 │                            │
       ├──────────────────────────────────────►│                                 │                            │
       │                                       │ Validate 1 <= days <= 3650      │                            │
       │                                       │                                 │                            │
       │                                       │ Log Pre-Audit Action            │                            │
       │                                       ├────────────────────────────────►│                            │
       │                                       │◄────────────────────────────────┤ AuditWriteResult (durable) │
       │                                       │                                 │                            │
       │                                       │ run_retention_cleanup(days)     │                            │
       │                                       ├─────────────────────────────────────────────────────────────►│
       │                                       │                                                              │ Delete entries & treatments
       │                                       │◄─────────────────────────────────────────────────────────────┤ RetentionCleanupResult
       │                                       │                                 │                            │
       │                                       │ Log Post-Audit Action           │                            │
       │                                       ├────────────────────────────────►│                            │
       │                                       │◄────────────────────────────────┤ AuditWriteResult           │
       │                                       │                                 │                            │
       │◄──────────────────────────────────────┤ Return RetentionCleanupResult   │                            │
```

---

## 6. Presentation Unit Authority

The `diabetic.ui.glucose_display` module is the single authoritative source for UI unit conversions, velocity display, range mapping, and haptic warnings:

- **Canonical Internal Unit**: All internal calculations, models, and filters operate exclusively in **mmol/L**.
- **Unit Conversions**: Converted at the presentation edge (`format_glucose`, `format_velocity`, `unit_label`) based on `config.PREFER_MMOL`.
- **Range & Haptic State**: Calculated from `medical_constants` and consumed by CLI HUD and Web UI.

---

## 7. HTTP API Endpoint Catalog & Error Matrix

| Endpoint | Method | Auth Required | Description | Error Responses |
|---|---|---|---|---|
| `/healthz` | GET | No | Process liveness probe. | — |
| `/readyz` | GET | No | Ingestion and snapshot readiness probe. | `503 Service Unavailable` |
| `/api/v1/hud` | GET | `tma` / `dev` | Current metabolic snapshot and HUD telemetry. | `401 Unauthorized`, `403 Forbidden` |
| `/api/v1/forecast` | GET | `tma` / `dev` | 4-hour and 24-hour glycemic forecast points. | `401 Unauthorized`, `403 Forbidden` |
| `/api/v1/calibration` | POST | `tma` / `dev` | Update biometric traits (gated whitelist). | `400 Bad Request`, `401 Unauthorized`, `403 Forbidden` |
| `/api/v1/entries` | GET | Device HMAC | Nightscout REST sensor readings poll. | `401 Unauthorized` |
| `/api/v1/entries` | POST | Device HMAC | Nightscout REST sensor ingestion. | `400 Bad Request`, `401 Unauthorized` |
