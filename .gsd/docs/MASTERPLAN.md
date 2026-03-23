# Bio-Quant: AI Glucose Crash & Faint Predictor Masterplan

This document outlines the linear roadmap for building the Bio-Quant system from the ground up, using a modular, medical-grade architecture.

---

---
## 🏗️ THE SPLIT ARCHITECTURE
The system is divided into two distinct components:
- **Backend (Metabolic Engine)**: Ingestion, Smoothing, Feature Math, and Forecasting.
- **Frontend (Interactive Hub)**: Telegram Bot, Real-time Dashboard, and Feedback Collection.

---

## ⚙️ PHASE 1: Backend Foundation (The Engine)
**Goal**: Build the core medical-grade processing pipeline.
- Plan 1.1: Multi-repo setup (Backend/Frontend) & Registry.
- Plan 1.2: Ingestion & Signal Smoother.

## 🤖 PHASE 2: Frontend Interactive Hub (The UI)
**Goal**: Implement the Telegram interaction layer.
- Plan 2.1: Interactive Telegram Bot (Prediction Alerts + Inline Buttons).
- Plan 2.2: Real-time Feedback Collector (Storing user verification).

## 📈 PHASE 3: Feature & ML Suite
- Plan 3.1: Metabolic Physics (Velocity/Accel).
- Plan 3.2: 30-min Forecaster (ML).

## 🛡️ PHASE 4: Safety & Orchestration
- Plan 4.1: Bimodal Safeguards & Coordinator.

## 📊 PHASE 5: The Audit Loop
**Goal**: Weekly performance review.
- Plan 5.1: Automated Weekly Auditor (Reporting accuracy from feedback).
- Plan 5.2: Stress Testing.

---

## 📢 PHASE 4: Communication & User Interface
**Goal**: Translate technical alerts into human-actionable notifications.

### Plan 4.1: Telegram Notifier
- **Bot**: Implement `src/comms/telegram_notifier.py` using asynchronous requests.
- **Dual Recipients**: Support for distinct User and Caregiver alert channels.

### Plan 4.2: Local CLI Dashboard
- **HUD**: A simple richness-focused terminal UI (Rich/Textual) to see real-time glucose graphs and model confidence.

---

## 🧪 PHASE 5: Validation & Stress Testing
**Goal**: Empirical proof of safety using historical replays.

### Plan 5.1: Historical Replay Engine
- **Validation**: Build a script to pipe 30 days of historical data through the entire system in "fast-forward" mode.
- **Metrics**: Measure Sensitivity (alerting on real events) and Specificity (preventing false alarms).

### Plan 5.2: Chaos Hardening
- **Resilience**: Script to kill processes and verify 100% state recovery from `data/state.json`.

---

## ☁️ PHASE 6: Local Deployment & Long-Term Monitoring
**Goal**: Stability in a production environment via native execution.

### Plan 6.1: Native Start & Cloud Logging
- **Launcher**: Create a robust `start.ps1` (Windows) and `start.sh` (Linux) to manage the Python process.
- **Monitoring**: Integration with MongoDB for persistent audit logs of every alert ever sent.
