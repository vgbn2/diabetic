# Bio-Quant: The Comprehensive Metabolic Roadmap

This document serves as the granular engineering blueprint for the transformation of the Diabetic Engine into a multi-tenant, neural-first **Telegram Web App (TWA)**.

---

## 🟠 PHASE 0.5: AUDIT REMEDIATION (Bio-Quant v16)
**Goal**: Resolve 16 critical bugs and architectural gaps identified in the v16 audit.

### Task 0.5.1: Core Engine Safety
- Fix `main.py` startup crash (sync `validate_config`).
- Replace hardcoded 2.5/5.0 intervals in `inference.py` with dynamic config.
- Implement prediction clamping for glucose (2.2–30.0) and HR.
- Fix background task references in `audit_logger.py` to prevent GC.

### Task 0.5.2: Data & Training Integrity
- Normalize velocity units in `metabolic_dataset.py` (per-minute vs per-5min).
- Fix `train.py` temporal leakage (sequential split instead of `random_split`).
- Implement EMA decay in `DigitalTwin.auto_tune` to prevent parameter drift.
- Fix `ingestion/mongo.py` path import error.

### Task 0.5.3: Architectural Coupling
- Integrate `BasalOracle` harmonic models into the 4h trajectory pipeline.
- Wire `GlucoseForecaster` (XGBoost) into the `Coordinator` voting logic.
- Implement `SignalQuality.check_data_gap` to pause smoothing during long outages.
- Resolve alert type collisions in `DecisionMatrix` (STRESS_ANOMALY vs FAINT_RISK).

---

## 🔴 PHASE 1: THE DATA FACTORY (Ingestion & Stability)
**Goal**: Establish a zero-loss, 5-layer state assembly pipeline.

### Task 1.1: Multi-Tenant SQL Registry (The Vessel Layer)
- **Deployment**: `diabetic/storage/vessel_registry.db` (SQLite/PostgreSQL).
- **Schema Design**:
    - `users`: Telegram ID (PK), Name, CreatedAt.
    - `bio_traits`: Age, Height, Weight, BMI, DiabetesType, DiagnosisYear.
    - `cultural_markers`: Nationality (ISO), Religion, FastingProtocols (Bool).
    - `medical_states`: SickMode (Active/Expiry), DawnPhenomenon (Active).
- **Logic**: Migration of hardcoded `.env` settings into persistent, per-user records.

### Task 1.2: The "Big JSON" State Synthesizer (The Audit Layer)
- **Service**: `diabetic/utils/data_factory.py`.
- **Function**: `assemble_snapshot(user_id) -> MetabolicSnapshot`.
- **Logic**: 
    - Poll **Atmospheric Data**: Merge OpenWeather (Temp/Humidity) and OpenAQ (PM2.5).
    - Poll **Biometric Data**: Fetch latest Nightscout `entries` (Glucose) and `treatments` (Insulin/Carbs).
    - Integrated **Audit Log**: Every snapshot is saved as a JSON blob in `storage/audit/` for extreme transparency.

### Task 1.3: BSON-to-JSON Forensic Transformer
- **Tool**: `scripts/utils/transform_bson_history.py`.
- **Action**: Bulk convert historical MongoDB collections (Clinical Ottai logs) into the "Big JSON" format.
- **Goal**: Ensure the CNN training set exactly matches the live inference data structure.

---

## 🟡 PHASE 2: THE COMMAND CENTER (TWA Platform)
**Goal**: Transition from CLI to a premium, user-controlled interface.

### Task 2.1: FastAPI Backend & Telegram Auth
- **Infrastructure**: `diabetic/api/main.py`.
- **Auth**: Implement `initData` validation using the Telegram Bot Token.
- **Endpoints**:
    - `GET /api/v1/snapshot`: Return the current 5-layer state.
    - `POST /api/v1/config`: Update Bio-Cultural traits.
    - `POST /api/v1/log`: Manual entry for insulin/hydration/exercise.

### Task 2.2: Premium TWA Frontend (The User Experience)
- **Stack**: Vanilla JS / HTML / CSS (Glassmorphism design).
- **Components**:
    - **Vessel Setup**: Interactive sliders for Bio-traits.
    - **Cultural Selector**: Searchable flag picker for Nationality; Radio buttons for Religion.
    - **Health Dashboard**: Real-time status indicators for "Sick Mode" and "Sensor Health."

### Task 2.3: Heart Rate (HR/HRV) Webhook Bridge
- **Action**: Expose a secure endpoint `/api/v1/telemetry/hr` to receive data from external sensors (e.g., Apple Health, Garmin).
- **Layer 1 Sync**: Integrate real-time HR/HRV into the Big JSON assembly loop.

---

## 🟢 PHASE 3: NEURAL-FIRST EXECUTION (The Predictive Brain)
**Goal**: Deploy $P > \alpha$ predictive logic.

### Task 3.1: CNN Inference Integration (Tier 4)
- **Engine**: `diabetic/ml_engine/predictor_cnn.py`.
- **Model**: Personalized 1D-CNN + LSTM (v14 architecture).
- **Execution**: Run inference every 5 minutes on the last 30 readings (1.25 hours of data).

### Task 3.2: Alpha-Gating & Decision Matrix
- **Logic**: Implement `alpha_threshold` check in the `DecisionMatrix`.
- **Rule**: If `pred_prob < alpha`, suppress the alert (Low Certainty).
- **Visuals**: Show the **Probabilistic Range (P5–P95)** on the TWA chart.

### Task 3.3: Reliability & Confidence Index
- **Metric**: Calculate $R_{score}$ based on data density (missing readings reduce reliability).
- **Visual**: A 0–100% "Health Meter" in the TWA HUD.

---

## 🟣 PHASE 4: REINFORCED FEEDBACK (The RLHF Loop)
**Goal**: Use interaction to minimize alert fatigue.

### Task 4.1: 30m Post-Alert Binary Verification
- **Bot Logic**: After a risk alert, set a 30m `asyncio` callback.
- **Interaction**: Send a message: *"Was that prediction correct?"* with `[CORRECT]` and `[FALSE ALARM]` buttons.

### Task 4.2: Dynamic Alpha Calibration (Tier 5)
- **Reinforcement**: If a user marks an alert as "False Alarm," increase the $\alpha$ threshold (becoming more conservative).
- **Audit**: Log all feedback into the SQL Registry to audit model drift over months.

---

## 🔵 PHASE 5: NIGHTSCOUT-LITE (Portability & Scale)
**Goal**: Decoupling from active sensors.

### Task 5.1: Heuristic "Lite" Mode
- **Action**: Enable the system to run on **Regime & Vessel** data only (simulated glucose based on known insulin/carbs).
- **Constraint**: Reliability score is capped at 35%; alerts are informative only.

### Task 5.2: Dockerized Multi-Tenant Deployment
- **Packaging**: Containerize the FastAPI + TWA + Worker loops.
- **Scale**: Ready for production deployment on Cloud Run or VPS with multiple users.
