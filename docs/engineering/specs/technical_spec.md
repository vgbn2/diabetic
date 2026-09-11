# Technical Specification

> **Diátaxis Type**: Reference & Specification | **Status**: Canonical | **Owner**: Systems Architecture | **Review**: Continuous

---

## 1. Runtime Environment & Toolchain

- **Primary Runtime**: Python 3.11+ (CPython)
- **Deep Learning Framework**: PyTorch 2.2+ (CPU inference optimized with single-thread clamping)
- **Signal Processing**: NumPy 1.26+, SciPy 1.12+
- **Persistence**: Async SQLAlchemy 2.0+ (SQLite 3), Motor / AsyncIOMotorClient (MongoDB 6.0+)
- **API & Web Gateways**: FastAPI 0.110+, Uvicorn 0.28+, WebSockets 12.0+
- **Documentation**: MkDocs Material 9.5+, MathJax 3, Mermaid.js

---

## 2. Resource Clamping & Memory Bounds

To ensure reliable continuous 24/7 operation on constrained host hardware (such as edge servers, Synology NAS, or developer workstations):

```python
# Conftest / Runtime Resource Clamping
import os, torch
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
torch.set_num_threads(1)
```

| Subsystem | Maximum RSS Memory | CPU Budget (Polling Epoch) | P99 Latency SLA |
|---|---|---|---|
| **Coordinator Loop** | 150 MB | < 10% (1 core) | < 50 ms |
| **Neural Inference** | 400 MB | < 25% (1 core) | < 80 ms |
| **FastAPI Bridge** | 80 MB | < 5% (1 core) | < 25 ms |
| **Complete Daemon** | < 600 MB | < 30% (1 core) | < 150 ms |

---

## 3. Data Contracts & State Schemas

### MetabolicSnapshot Data Contract
```python
from pydantic import BaseModel, ConfigDict
from typing import Optional

class MetabolicSnapshot(BaseModel):
    """A unified state representing a person's metabolic condition at a point in time (5-Layer Synthesis)."""
    glucose: GlucoseReading
    cardiac: Optional[CardiacReading] = None
    last_insulin: Optional[InsulinDose] = None
    last_meal: Optional[MealEvent] = None
    last_hydration: Optional[HydrationEvent] = None
    environment: Optional[EnvironmentReading] = None
    feedback: Optional[UserFeedback] = None

    # Layer 2 (Regimes)
    cycle_day: Optional[int] = None
    is_sick: bool = False

    # Layer 4 (The Meta-Correction Layer)
    filtered_value: float = 0.0
    velocity: float = 0.0
    acceleration: float = 0.0
    atr_14: float = 0.0
    predict_30m: float = 0.0
    predicted_hr: float = 0.0
    forecast: Optional[ProbabilisticForecast] = None
    residual_error: float = 0.0
    sensor_health: float = 1.0

    # Tactical Prediction Horizons
    predict_15m: float = 0.0
    predict_60m: float = 0.0
    confidence_index: float = 0.0
    velocity_score: float = 0.0

    # Layer 3 (The Behavioral Engine)
    active_carbs: float = 0.0      # Carbs on Board (COB)
    active_insulin: float = 0.0    # Insulin on Board (IOB)
    activity_label: str = "UNKNOWN"

    model_config = ConfigDict(arbitrary_types_allowed=True)
```

### Ingress Entry Schema (Nightscout Format)
```json
{
  "_id": "65f0a1b2c3d4e5f6a7b8c9d0",
  "sgv": 115,
  "date": 1710288000000,
  "dateString": "2026-03-13T00:00:00.000Z",
  "direction": "Flat",
  "type": "sgv",
  "device": "dexcom_g6_bridge"
}
```
