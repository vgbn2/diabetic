# Diabetic: Project Roadmap

This roadmap tracks the evolution from forensic data parsing to an integrated, 5-layer artificial intelligence suite.

## 🔴 Phase 1: Automation & Integration (The "Perfect Core")
- [ ] **One-Click Pipeline**: Create a master runner that automates Ingestion -> Cleaning -> Training -> Analysis.
- [ ] **5-Layer SQL Registry**: Multi-tenant schema supporting Vessel, Regime, Agency, Audit, and RLHF layers.
- [ ] **Data Factory (Perfect CSV)**: Export 5-layer training sets for the CNN.
- [ ] **PDF Parser Persistence**: Refactor using JSON templates for 100% stability.

## 🟡 Phase 2: Multi-Layer ML (Hybrid Ensemble)
- [ ] **Signal Layer (CNN)**: 1D-CNN + LSTM for Tier 1 & 2 patterns.
- [ ] **Behavioral Layer (XGBoost)**: Personalized Tier 3 modeling.
- [ ] **Correction Module (Tier 4)**: Systemic residual audit and sensor health.
- [ ] **Reinforcement Feed (Tier 5)**: Interactive user-feedback loop implementation.

## 🔵 Phase 3: Platform & Environment (Cloud API)
- [ ] **Cloud API Deployment**: Docker-based scalable service.
- [ ] **Platform Deployment**: Cross-device Dashboards.
- [ ] **Nightscout Sync**: Real-time API integration.

---

## 🏗️ Technical Clarifications (DECISIONS MADE)
*   **Intelligence Model**: [x] **5-Layer Hierarchical (Vessel, Environment, Agency, Audit, RLHF)**
*   **ML Framework**: [x] **PyTorch**
*   **Target Device**: [x] **Cloud API**
*   **Alert Sensitivity**: [x] **Conservative (Noise-Resistant)**
*   **Data Structure**: [x] **Multi-Tenant SQL Database**
