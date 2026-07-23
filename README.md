# Diabetic: Metabolic Intelligence Engine

> **Mission**: Eliminate metabolic unpredictability through high-fidelity digital twin simulation and 5-layer predictive intelligence.

---

## 🧬 Core Intelligence: The 5-Layer Model

The system operates on an tiered hierarchy designed to isolate variables by their source and predictability.

| Layer | Type | Focus | Primary Signals |
| :--- | :--- | :--- | :--- |
| **L1: The Vessel** | Basal / Static | Who you are | BG, HR-BPM, Age, Gender, Ethnicity |
| **L2: The Conditions** | Environment | What happens *to* you | Weather (Temp/Hum), AQI, Hormones, Seasonality |
| **L3: The Choices** | Behavioral | What you *do* | Diet, Drinks, Insulin, Sleep, Exercise |
| **L4: The Audit** | Self-Correction | Model performance | Residual Error, Sensor Health, Metabolic Inertia |
| **L5: The Feedback** | Interaction | Subjective Truth | RLHF, Symptom Mapping, Threshold Bias |

---

## 🏗️ Architectural Flow

The engine moves through three temporal phases:

1.  **Forensic (Past)**: High-resolution PDF parsing (Libre/Ottai) to build historical metabolic baselines.
2.  **Live (Present)**: Real-time synchronization with Nightscout/CGM for active Digital Twin simulation.
3.  **Intelligence (Future)**: Digital-twin and validated 1D-CNN forecasting to support conservative faint-risk alerts.

---

## 🛠️ Module Architecture

- **`diabetic/ingestion/`**: Live and Offline data synchronization (Nightscout, high-res PDF).
- **`diabetic/dsp/`**: Signal hardening via Kalman filtering and noise rejection.
- **`diabetic/ml_engine/`**: The brain — containing the Digital Twin and 1D-CNN signal signatures.
- **`diabetic/telegram_bot/`**: Interaction layer and decision matrix for conservative alerting.

---

## 🚀 Quick Start

Python 3.12 is the verified local and container runtime.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  -r requirements-dev.lock

# Verify the repository contract and runtime behavior
.venv/bin/python -m pytest ops/lab -q

# Run a local simulation
.venv/bin/python -m diabetic.main simulation

# Start the live monitor after configuring .env
.venv/bin/python -m diabetic.main live
```

For the local container deployment:

```bash
cp .env.example .env
docker compose up -d --build
```

See [the local Nightscout runbook](docs/local-nightscout.md) for safe LAN
binding, migration staging, backup, and health checks.

The selected CNN state dictionary is versioned with the source tree. If it is
missing or cannot be loaded, neural inference is disabled and the coordinator
uses its non-neural fallback instead of running randomly initialized weights.

---

## 📑 Specialized Documentation

- 📐 **[Architecture](docs/architecture.md)**: Deep-dive into modules and clinical math.
- 🧠 **[ML specification](docs/ML_SPEC.md)**: Theoretical specification for the five layers.
- 🗺️ **[Current handoff](workspace/HANDOFF.md)**: Verified state, deployment priorities, and remaining work.
