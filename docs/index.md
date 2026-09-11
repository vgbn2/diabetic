# Bio-Quant — Clinical Telemetry & Digital Twin Platform

Welcome to the **Bio-Quant** engineering and clinical documentation. Bio-Quant is a high-reliability, real-time physiological twin and clinical telemetry engine designed for continuous glucose monitoring (CGM), Kovatchev risk modeling, multi-sensor environmental ingestion, and neural faint prediction.

---

## 1. System Topology & Architecture

```
                    [ SENSOR INGRESS & TELEMETRY ]
        ┌───────────────────┬───────────────────┬───────────────────┐
        │  Nightscout REST  │   MongoDB Direct  │  OpenWeather/BLE  │
        └─────────┬─────────┴─────────┬─────────┴─────────┬─────────┘
                  │                   │                   │
                  ▼                   ▼                   ▼
    ┌───────────────────────────────────────────────────────────────────┐
    │                     INGESTION & GAP REPLAY                        │
    │         (Event Integrity, Stream Watermarks, Normalization)       │
    └─────────────────────────────────┬─────────────────────────────────┘
                                      │
                                      ▼
    ┌───────────────────────────────────────────────────────────────────┐
    │                  DIGITAL SIGNAL PROCESSING (DSP)                  │
    │         (3D Kinematic Kalman Filter [g, v, a], Spike Rejection)   │
    └─────────────────────────────────┬─────────────────────────────────┘
                                      │
                                      ▼
    ┌───────────────────────────────────────────────────────────────────┐
    │            CLINICAL DIGITAL TWIN & NEURAL INFERENCE               │
    │     (2-Compartment PK/PD Twin, 1D-CNN Faint Classifier, Oracle)   │
    └─────────────────────────────────┬─────────────────────────────────┘
                                      │
                                      ▼
    ┌───────────────────────────────────────────────────────────────────┐
    │                   SAFETY SHIELD & COORDINATOR                     │
    │  (Kovatchev Risk Indices [LBGI/HBGI], Divergence Gating, Actions) │
    └──────────────┬──────────────────┬──────────────────┬──────────────┘
                   │                  │                  │
                   ▼                  ▼                  ▼
          [ Telegram Bot / TWA ] [ SQLite/PG SQL ] [ Terminal TUI/CLI ]
```

---

## 2. Core Architectural Principles

1. **Deterministic Unit Authority**:
   - All internal clinical modeling, DSP filtering, forecasting, and storage strictly operate in **`mmol/L`**.
   - Unit transformations (`mg/dL` vs `mmol/L`) only happen at presentation boundaries via `diabetic.ui.glucose_display`.

2. **Single-Claim Lifecycle & State Machine**:
   - Coordinator lifecycle transitions strictly: `created` → `starting` → `running` → `stopped` / `failed`.
   - Process replacement invariant: restarting a stopped instance is prohibited.

3. **Fail-Closed Clinical Safety**:
   - Neural models are gated against 3D kinematic Kalman baselines (`Alpha Gate`).
   - If model divergence exceeds 2.5 mmol/L or model confidence falls below threshold, the system fails closed to physical ODE predictions.

4. **Zero-Tolerance Stub Policy**:
   - 100% of CLI manifest commands, MCP tools, and API endpoints map to live, tested coroutines.
   - Verified by automated regression suites and contract characterization tests.

---

## 3. Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/vgbn2/diabetic.git
cd diabetic

# Install dependencies (Python 3.11+)
pip install -r requirements.txt
```

### Running Operational TUI

```bash
# Launch interactive terminal UI
python -m diabetic.cli.tui

# One-shot operational health check
python -m diabetic.cli op health
```

### Running the Live Supervisor Service

```bash
python -m diabetic.main live
```

### Running Verification Suites

```bash
# Run all contract tests
pytest -q ops/lab/

# Run repository hygiene and cleanliness evaluator
python scripts/check_repo_cleanliness.py
```

---

## 4. Documentation Index

- **[System Architecture](architecture.md)** — Core components and mathematical foundations.
- **[Engineering Contracts](engineering/architecture.md)** — Lifecycle state machines, ASCII sequence diagrams, and error matrices.
- **[Tenancy & Identity Roadmap](engineering/tenancy-and-identity.md)** — Multi-tenant migration roadmap and UUID identity contracts.
- **[TUI Feature Map](engineering/tui_feature_map.md)** — Complete 6-category, 12-command operational console reference.
- **[Machine Learning Specification](ML_SPEC.md)** — Digital Twin pharmacokinetics and 1D-CNN neural classifier details.
- **[Data Provenance & Privacy](data-provenance.md)** — PII scrubbing and dual-write audit durability.
