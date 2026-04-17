# SPEC.md - Bio-Quant TWA [REVISED]

## Goal

Transition from a forensic-only tool into a multi-tenant **Telegram Web App (TWA)** providing real-time metabolic intelligence, personalized biological profiles, and a reinforced feedback loop.

## 🔴 Phase 1: Ingestion & Stability (CURRENT)

- [X] **Forensic PDF Parser**: High-res ingestion from clinical reports.
- [X] **Infrastructure Hardening**: Persistent HTTPX and SQL WAL mode.
- [ ] **Unified 5-Layer Data Factory**: Combine Weather + Air + Regime + Bio into a unified "Big JSON" state frame.
- [ ] **BSON-to-JSON Pipeline**: Transform MongoDB historical data into the new unified frame format.

## 📱 User Interface (The TWA)

- **Biological Profile**: User configures Age, Weight, Height, Gender, and Diabetes Type.
- **Cultural Markers**: Selection of **Nationality** (with flag picker) and **Religion** for environmental/dietary regime modeling.
- **Direct Integration**: TWA allows pasting Nightscout URL, API Secret, and Heart Rate sensor links directly into the secure UI.
- **Reliability Score**: A visual indicator (0-100%) showing model confidence. Runs in "Heuristic Mode" initially, transitioning to "Neural Mode" after X sessions of data feeding.

## 🔮 Predictive Logic

- **CNN-Based Multi-Layer Model**: Use a 1D-CNN + LSTM architecture to process temporal glucose/HR sequences alongside the static 15-trait biological vector.
- **Alpha-Threshold Alerting**: Alarms ONLY fire 30 minutes before a predicted Hypo/Hyper state if the certainty probability $P$ exceeds the user-defined $\alpha$ (default 0.85).
- **Binary Feedback Loop**: 30 minutes after an alert, the system pushes a Telegram message asking: **"Was the prediction right or wrong?"** (Binary Feedback).

## 📊 Data Architecture: The "Big JSON"

- **Unified 5-Layer Assembly**: For every prediction cycle, the system must synthesize a single "State Frame" JSON containing data from all layers:
  - **Vessel**: Bio-traits, Nationality, Religion flags.
  - **Environment**: Weather, Air Quality (AQI/PM2.5), Location.
  - **Regime**: Meals, Insulin, Activity (from TWA or Nightscout).
  - **Agent**: Direct sensor values (Glu/HR) and model confidence scores.
  - **Audit**: Binary feedback history and sensor reliability metrics.
- **BSON to JSON Extraction**: All clinical historical data (BSON from MongoDB) must be transformed into this unified JSON format for training parity.

## 🏗️ Backend Requirements

- **Multi-Tenant SQL Registry**: Transition settings from `.env` to a secure SQL schema supporting multiple users.
- **FastAPI Core**: Serve the TWA frontend and handle authenticated API calls via Telegram `initData` validation.
- **RLHF Module**: Capture binary feedback to adjust Tier 5 (Interaction) weights and minimize false-positive fatigue.

## ⚖️ Constraints

- **Zero-Trust Input**: All user-provided API keys and URLs must be validated before the ingestion loop starts.
- **Privacy-First**: PII (Nationality/Religion) is used solely for metabolic regime multipliers (e.g., fasting cycles, regional diets).
- **Graceful Degradation**: If Nightscout is absent, fallback to manual entry and "Model-Only" simulation with reduced reliability score.
