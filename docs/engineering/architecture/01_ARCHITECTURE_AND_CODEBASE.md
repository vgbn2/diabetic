# 01. Bio-Quant Architecture & Codebase Organization

> **Diátaxis Type**: Explanation & Reference | **Status**: Canonical | **Review**: Continuous

This document establishes the canonical top-level architecture, subsystem boundaries, directory taxonomy, C4 container & component topologies, and fundamental runtime invariants for the Bio-Quant Metabolic Intelligence Platform.

---

## 1. Architectural Standards & Meta-Framework Synthesis

The Bio-Quant engineering documentation synthesizes four industry architectural standards:

| Framework | Core Focus | Integration Layer | Bio-Quant Platform Mapping |
|---|---|---|---|
| **ISO/IEC/IEEE 42010** | Architecture Description | Meta-Framework | Stakeholders, viewpoints, invariant guarantees |
| **arc42** | Structural Pattern | Document Sections | Context, building blocks, runtime, deployment, risks |
| **C4 Model** | Hierarchical Zoom | Diagrammatic Model | Context (L1), Containers (L2), Components (L3), Code |
| **Diátaxis** | Information Needs | Documentation Type | High-density "Explanation" + "Reference" synthesis |

---

## 2. C4 Architecture Topologies

### C4 Level 1: System Context Diagram

```mermaid
flowchart TD
    subgraph Actors["System Actors & Consumers"]
        PATIENT["Type 1 Diabetes Patient<br/>Continuous Telemetry & HUD Monitoring"]
        CLINICIAN["Clinical / Research Supervisor<br/>Retrospective Analysis & Model Promotion"]
        MCP_CLIENT["AI Agent Clients<br/>Autonomous FastMCP Tool Probing"]
    end

    CGM["Continuous Glucose Monitors<br/>Dexcom / Libre / Nightscout Bridge<br/>Raw Glucose & Treatment Streams"]
    WEATHER["Environmental APIs<br/>OpenWeatherMap REST API<br/>Temp, Humidity, Ambient AQI"]

    BIO["Bio-Quant Metabolic Engine<br/>Real-Time 3D Kalman DSP, Digital Twin Simulation,<br/>1D-CNN Neural Faint Prediction & Decision Shield"]

    TELEGRAM["Telegram Push Gateway<br/>Critical Faint Alerts & Actionable Suggestions"]

    PATIENT -->|Web HUD / Telegram App| BIO
    CLINICIAN -->|CLI Admin & Audit Tools| BIO
    MCP_CLIENT -->|JSON-RPC via FastMCP| BIO
    CGM -->|REST Telemetry / MongoDB Ingress| BIO
    WEATHER -->|Environmental Telemetry| BIO
    BIO -->|Push Alerts & Haptic Triggers| TELEGRAM
```

### C4 Level 2: Container Diagram (Inter-Process Topology)

```mermaid
flowchart TD
    subgraph CoreEngine["Bio-Quant Core Container (Python 3.11 / PyTorch)"]
        COORD["Coordinator Process<br/>diabetic.coordinator<br/>Single-claim PID lock, task draining<br/>[Load: 4/10 | RSS: <150MB]"]
        DSP_C["DSP & Kalman State Filter<br/>diabetic.dsp<br/>State: [g, v, a], spike rejection<br/>[Load: 2/10 | Heap: <30MB]"]
        ML_C["ML Twin & 1D-CNN Engine<br/>diabetic.ml_engine<br/>Inference, twin simulation, forecasts<br/>[Load: 5/10 | RSS: <400MB]"]
        SHIELD["Decision Matrix & Safety Shield<br/>diabetic.telegram_bot.decision_matrix<br/>RLHF dampening, fail-closed rules<br/>[Load: 2/10 | Heap: <40MB]"]
    end

    subgraph DataStorage["Data & Ingress Infrastructure"]
        MONGO["Local MongoDB (mongo:6.0)<br/>Raw entries, treatments, sensor logs<br/>[Port: 27017 | Bounded retention]"]
        SQLITE["Vessel Registry (SQLite 3)<br/>SQLAlchemy async profiles & tenant secrets<br/>[storage/vessel_registry.db]"]
        NS_LOCAL["Local Nightscout Monitor<br/>cgm-remote-monitor:15.0.3<br/>[Port: 1337 | Ingest bridge]"]
    end

    subgraph Presentation["Presentation & API Gateways"]
        FASTAPI["TWA REST & WebSocket Bridge<br/>diabetic.telegram_bot.twa_api<br/>FastAPI Port: 8000 | Nightscout REST comp<br/>[Load: 3/10 | Latency P99: <25ms]"]
        HUD["Web HUD & Telegram Mini App<br/>twa/ (Vanilla JS / CSS)<br/>Real-time Canvas trajectory display"]
        MCP_SRV["FastMCP Diagnostics Server<br/>diabetic.mcp.server<br/>bio_* diagnostic tool registry"]
    end

    NS_LOCAL -->|Telemetry| MONO_INGEST["diabetic.ingestion.nightscout"]
    MONO_INGEST --> COORD
    COORD --> DSP_C --> ML_C --> SHIELD
    SHIELD --> FASTAPI
    FASTAPI --> HUD
    COORD --> MONGO
    COORD --> SQLITE
    COORD --> MCP_SRV
```

---

## 3. Subsystem Boundaries & Directory Taxonomy

| Directory | Subsystem Role | Invariants & Constraints | Primary Entrypoint |
|---|---|---|---|
| `diabetic/` | Core Engine Package | Pure Python 3.11+, typed, zero-stub contracts | `diabetic/main.py` |
| `diabetic/coordinator.py` | Central Orchestration | Single-claim startup, background task draining | `Coordinator.start()` |
| `diabetic/ingestion/` | Multi-Source Ingress | Idempotent deduplication, watermarking | `EventIntegrity` |
| `diabetic/dsp/` | Signal Processing & Math | 3D Kalman $[g, v, a]$, Kovatchev Risk | `Kalman3DFilter` |
| `diabetic/ml_engine/` | Twin & Neural Forecaster | Fail-closed weight verification, atomic journal | `NeuralInferenceRunner` |
| `diabetic/telegram_bot/` | API, Alerting & Bot | Conservative safety shield, RLHF dampening | `twa_api.py`, `handlers.py` |
| `diabetic/ui/` | Presentation Layer | Strict unit authority (`glucose_display.py`) | `format_glucose()` |
| `diabetic/storage/` | Persistence & Tenancy | Async SQLAlchemy engine, clean shutdown | `DatabaseEngine` |
| `diabetic/operations/` | Data Hygiene & Retention | Pre/post audit validation, bounded batch delete | `cleanup_historical_retention` |
| `ops/lab/` | Contract Test Suite | Fast, zero-sleep unit and contract gates | `pytest ops/lab/` |
| `twa/` | Frontend Web App | Zero-build Vanilla JS, WebSocket auto-reconnect | `twa/index.html` |

---

## 4. Fundamental Runtime Invariants

```mermaid
flowchart LR
    INV1["1. Fail-Closed Safety<br/>Kinematic fallback on divergence"]
    INV2["2. Single-Claim PID<br/>Atomic POSIX lock authority"]
    INV3["3. Strict Unit Authority<br/>mmol/L domain, UI conversion"]
    INV4["4. Pre-Alpha Ordering<br/>Confidence computed pre-gate"]
    INV5["5. Zero Stub Contracts<br/>Declarative schema verification"]

    INV1 --- INV2 --- INV3 --- INV4 --- INV5
```

1. **Fail-Closed Safety Invariant**: If neural inference diverges from physical-chemical digital twin kinematics by more than the threshold or if weights are corrupted, the engine immediately fails closed to the linear-quadratic kinematic projection.
2. **Single-Claim Startup Authority**: The coordinator acquires an exclusive file lock (`diabetic.lock`) and validates active PID status. If a duplicate process attempts startup, it terminates with POSIX exit code 1.
3. **Strict Presentation Unit Authority**: Internal state and calculations operate solely in **mmol/L**. The `diabetic.ui.glucose_display` module is the single presentation authority for formatting values into mg/dL or mmol/L for user interfaces.
4. **Alpha Gate Confidence Pre-Conditioning**: Historical confidence ($C_k$) is smoothed and evaluated *before* Alpha Gate checks, eliminating uninitialized confidence index anomalies.
5. **Zero-Stub Engineering**: All registered CLI commands, MCP tools, and REST endpoints route to fully realized operational handlers.
