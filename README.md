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
3.  **Intelligence (Future)**: Hybrid 1D-CNN + XGBoost forecasting to proactively prevent faint-risk events.

---

## 🛠️ Module Architecture

- **`diabetic/ingestion/`**: Live and Offline data synchronization (Nightscout, high-res PDF).
- **`diabetic/dsp/`**: Signal hardening via Kalman filtering and noise rejection.
- **`diabetic/ml_engine/`**: The brain — containing the Digital Twin, XGBoost, and the 1D-CNN signal signatures.
- **`diabetic/telegram_bot/`**: Interaction layer and decision matrix for conservative alerting.

---

## 🚀 Quick Start (One-Click Pipeline)

*Currently in development (Phase 1.1: The SQL Core)*

```powershell
# Ingest historical data
python -m diabetic.ingestion.offline.master_ingest

# Train the hybrid ensemble
python -m diabetic.ml_engine.retrain_all

# Run the live monitor
python -m diabetic.main live
```

---

## 📑 Specialized Documentation

- 📐 **[ARCHITECTURE.md](file:///c:/Users/Lenovo/Desktop/VGBN/.vscode/CODEPTIT/hyperglycemia-faint-predictor/architecture.md)**: Deep-dive into modules and clinical math.
- 🧠 **[ML_SPEC.md](file:///c:/Users/Lenovo/Desktop/VGBN/.vscode/CODEPTIT/hyperglycemia-faint-predictor/ML_SPEC.md)**: Theoretical specification for the 5 tiers.
- 🗺️ **[ROADMAP.md](file:///c:/Users/Lenovo/Desktop/VGBN/.vscode/CODEPTIT/hyperglycemia-faint-predictor/ROADMAP.md)**: Current development status and upcoming milestones.
