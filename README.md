# Bio-Quant Metabolic Intelligence Engine

The **Bio-Quant Metabolic Intelligence Engine** is a physiological monitoring, glucose trend forecasting, and faint-risk detection system built for Type 1 Diabetes (T1D) management. It integrates real-time Continuous Glucose Monitor (CGM) telemetry, digital twin simulation, and multi-layer neural inference to project metabolic trajectories and issue early warnings for impending glycemic emergencies.

---

## 🧬 Multi-Layer Architecture

The system uses a 5-layer biological and environmental model hierarchy to isolate physiological factors, environmental drivers, human agency, model residuals, and user feedback.

| Layer | Domain | Responsibility | Key Input Signals |
| :--- | :--- | :--- | :--- |
| **Layer 1** | **Bio-Basal Vessel** | Baseline physiological state and telemetry | Glucose ($g$), Rate of Change ($v$), Acceleration ($a$), Heart Rate (BPM), Age, Gender |
| **Layer 2** | **Adaptive Regimes** | Forced environmental and biological oscillations | Ambient Temperature, Humidity, AQI, Circadian & Hormonal Cycles |
| **Layer 3** | **Behavioral Engine** | User-initiated metabolic interventions | Dietary Carbohydrates (GI/GL), Active Insulin (IOB), Sleep Duration, Physical Exercise |
| **Layer 4** | **Meta-Correction** | Systemic error tracking and sensor health | Model Residuals, Sensor Jitter, Metabolic Inertia, Confidence Score Index |
| **Layer 5** | **Interaction & RLHF** | Subjective feedback and sensitivity tuning | User Alarm Feedback (RLHF), Symptom Logs, Alert Threshold Customization |

---

## 🏗️ System Execution Pipeline

The processing pipeline transforms raw sensor inputs into actionable physiological forecasts:

```mermaid
sequenceDiagram
    participant NS as Nightscout API
    participant C as Coordinator Engine
    participant DSP as Signal Processing (Kalman)
    participant ML as ML Inference & Digital Twin
    participant DM as Decision Matrix Shield
    participant TWA as Telegram App / HUD

    loop Every 2.5–5 Minutes
        C->>NS: Ingest Glucose Telemetry & Treatment Records
        NS-->>C: Raw Glucose & Insulin/Carb Data
        C->>DSP: Apply Kalman 3D Filtering & Kinematics
        DSP-->>C: Hardened MetabolicSnapshot [g, v, a]
        C->>ML: Evaluate Digital Twin & Neural CNN Inference
        ML-->>C: 30-min & 4-hour Glycemic Trajectories
        C->>DM: Check Safety Shield & Alert Thresholds
        DM-->>C: Evaluate Severity & Conservative Constraints
        C->>TWA: Dispatch Real-Time HUD Update & Alerts
    end
```

---

## 📂 Repository Structure

```text
├── diabetic/                 # Core Python backend engine
│   ├── auth/                 # Telegram WebApp initData HMAC authentication
│   ├── cli/                  # Command-line interface and TUI dispatchers
│   ├── dsp/                  # Kalman filtering, signal quality, metabolic math
│   ├── ingestion/            # Data source adapters (Nightscout, MongoDB, Weather)
│   ├── mcp/                  # FastMCP server exposing bio-quant diagnostic tools
│   ├── ml_engine/            # PyTorch 1D-CNN, Digital Twin, Basal Oracle, Training
│   ├── storage/              # VesselRegistry (SQLAlchemy async) and MongoDB clients
│   ├── telegram_bot/         # Decision matrix, alert dispatching, TWA API bridge
│   └── utils/                # Health readiness probes, audit logging, data factory
├── docs/                     # Technical specifications and operational runbooks
│   ├── architecture.md       # Detailed system architecture specification
│   ├── data-provenance.md    # Historical data archives, CSV roles, and verification
│   ├── history.md            # Legacy documentation archive and Git history
│   ├── local-nightscout.md   # Deployment runbook for local Nightscout & MongoDB
│   ├── ML_SPEC.md            # Multi-layer metabolic model theoretical specification
│   └── engineering/          # Web app authentication, API specs, TUI feature maps
├── ops/lab/                  # Unit and contract test suite
├── scripts/                  # Operations, migrations, and offline verification tools
└── twa/                      # Telegram Mini App frontend (HTML/CSS/JS)
```

---

## 🚀 Quick Start & Environment Setup

### Prerequisites
- **Python**: Python 3.12 (CPython 3.12.13 verified)
- **Database**: MongoDB (optional local or Atlas connection) and SQLite (async)

### Local Virtual Environment

```bash
# Initialize Python 3.12 virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Upgrade pip and install production & development dependencies
pip install --upgrade pip
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

### Running Verification & Tests

```bash
# Execute full contract test suite
python -m pytest ops/lab -v

# Run local simulation mode
python -m diabetic.main simulation

# Check system health status
python -m diabetic.main health
```

---

## 🐳 Container Deployment

The application provides a containerized setup comprising MongoDB, local Nightscout, and the Bio-Quant Core engine.

```bash
# Copy example environment configuration
cp .env.example .env

# Build and start services in background
docker compose up -d --build

# Verify container status
docker compose ps
```

Refer to the [Local Nightscout Runbook](docs/local-nightscout.md) for LAN binding details, database migration workflows, and operator backup procedures.

---

## 📑 Technical Documentation Map

- 📐 **[System Architecture](docs/architecture.md)**: Deep dive into module wiring, sequence diagrams, and mathematical formulas.
- 🧠 **[Metabolic ML Specification](docs/ML_SPEC.md)**: Theoretical foundation for the 5-layer metabolic model.
- 🔐 **[Web Auth & API Specification](docs/engineering/architecture.md)**: HMAC authentication flow, endpoint maps, and security contracts.
- 🧾 **[Data Provenance & Verification](docs/data-provenance.md)**: Provenance contracts, historical archives, and privacy guidelines.
- 🐳 **[Local Nightscout Runbook](docs/local-nightscout.md)**: Step-by-step operator guide for local container deployments.
- 🗺️ **[Workspace Handoff & State](workspace/HANDOFF.md)**: Current system verification state and remaining deployment gates.

---

## 🔒 Security & Medical Disclaimers

- **Security Policy**: All web API endpoints (`/api/v1/*`) are protected by Telegram WebApp `initData` HMAC validation with fail-closed authorization.
- **Medical Disclaimer**: The Bio-Quant engine is designed as an analytical decision-support tool. It does not issue direct insulin dosing commands to automated pumps or replace clinical medical advice.
