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
@dataclass
class MetabolicSnapshot:
    timestamp: datetime
    glucose: float            # mmol/L
    velocity: float           # mmol/L/min
    acceleration: float       # mmol/L/min^2
    heart_rate: Optional[float] = None
    temperature: Optional[float] = None
    aqi: Optional[float] = None
    carbs_on_board: float = 0.0
    insulin_on_board: float = 0.0
    confidence_index: float = 1.0
    predicted_glucose_30m: Optional[float] = None
    predicted_glucose_4h: Optional[list[float]] = None
    faint_risk_flag: bool = False
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
