# Bio-Quant: Implementation Roadmap

## Milestone 0: Data Enrichment (Day 0 - Optional)
- [ ] **Phase 0.1**: PDF Data Extraction (Historical Labs)
- [ ] **Phase 0.2**: Personal Model Pre-training (Transfer Learning)

## Milestone 1: Backend Foundation (Days 1-2)
- [ ] **Phase 1.1**: Directory structure & `src/registry.py`
- [ ] **Phase 1.2**: `NightscoutClient` with Rate-Likiting
- [ ] **Phase 1.3**: `SignalSmoothing` Implementation & Simulation Test

## Milestone 2: Intelligence & Forecasting (Days 3-4)
- [ ] **Phase 2.1**: Metabolic Feature Pipeline (`src/features.py`)
- [ ] **Phase 2.2**: Training Pipeline for `y = future_glucose_30m`
- [ ] **Phase 2.3**: Reference Dataset (OhioT1DM) Integration

## Milestone 3: The Safety Shield & Orchestration (Days 5-6)
- [ ] **Phase 3.1**: Bimodal Alert Guard (`src/alert_engine.py`)
- [ ] **Phase 3.2**: Central `Coordinator` Implementation
- [ ] **Phase 3.3**: Circuit Breaker & State Recovery

## Milestone 4: Communication & Dashboard (Days 7-8)
- [ ] **Phase 4.1**: Telegram Notifier (User/Caregiver)
- [ ] **Phase 4.2**: Rich CLI Real-Time HUD

## Milestone 5: Certification & Local Deployment (Days 9-10)
- [ ] **Phase 5.1**: 30-Day Historical Replay Test
- [ ] **Phase 5.2**: Chaos Resilience Audit
- [ ] **Phase 5.3**: Native Start Scripts & MongoDB Cloud Audit Logs
