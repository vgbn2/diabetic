# Capability Manifest

> **Diátaxis Type**: Reference & Specification | **Status**: Canonical | **Owner**: Systems Architecture | **Review**: Continuous

This manifest defines the operational capabilities, maturity ratings, and verification gates across all Bio-Quant subsystems.

---

## Subsystem Capability Matrix

| Subsystem | Capability Area | Status | Maturity | Primary Contract / Gate |
|---|---|---|---|---|
| **Ingestion** | Nightscout REST Ingress | Implemented | Production | `ops/lab/test_nightscout_auth.py` |
| **Ingestion** | MongoDB Historical Storage | Implemented | Production | `ops/lab/test_historical_data.py` |
| **Ingestion** | Event Deduplication & Gap Tracking | Implemented | Production | `ops/lab/test_event_integrity.py` |
| **Ingestion** | Weather & Environmental API | Implemented | Beta | `ops/lab/test_stub_sweep_integrity.py` |
| **DSP** | 3D Kalman State Filter ($g, v, a$) | Implemented | Production | `ops/lab/test_clinical_contracts.py` |
| **DSP** | Non-Biological Spike Rejection | Implemented | Production | `ops/lab/test_operational_contracts.py` |
| **DSP** | Kovatchev Risk-Space Transform | Implemented | Production | `ops/lab/test_clinical_contracts.py` |
| **ML Engine** | Biphasic Meal & Insulin Twin | Implemented | Production | `ops/lab/test_clinical_contracts.py` |
| **ML Engine** | 1D-CNN Multi-Horizon Forecaster | Implemented | Production | `ops/lab/test_forecast.py` |
| **ML Engine** | Basal Drift Oracle | Implemented | Production | `ops/lab/test_stub_sweep_integrity.py` |
| **ML Engine** | Atomic Candidate Promotion | Implemented | Production | `ops/lab/test_runtime_lifecycle.py` |
| **Decision** | Critical Faint Risk Detection | Implemented | Production | `ops/lab/test_alert_delivery.py` |
| **Decision** | RLHF Alert Fatigue Dampening | Implemented | Beta | `ops/lab/test_operational_contracts.py` |
| **Decision** | Telegram Notifier Task Draining | Implemented | Production | `ops/lab/test_runtime_lifecycle.py` |
| **Presentation** | Strict Unit Authority Formatting | Implemented | Production | `ops/lab/test_operational_contracts.py` |
| **Presentation** | Real-Time TWA Canvas HUD | Implemented | Production | `ops/lab/test_twa_calibration.py` |
| **Operations** | Bounded Retention Cleanup | Implemented | Production | `ops/lab/test_retention_cleanup.py` |
| **Operations** | Cleanliness Evaluator (`check_repo_cleanliness.py`) | Implemented | Production | `scripts/check_repo_cleanliness.py` |

---

## Maturity Definitions
- **Production**: Feature-complete, verified under 100% contract test coverage, fail-closed safety verified.
- **Beta**: Functional and covered by unit tests, undergoing real-world soak tuning.
- **Gated**: Implemented behind explicit configuration or environment flags.
