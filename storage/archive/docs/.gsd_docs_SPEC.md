# Bio-Quant Technical Specification (SPEC.md)

This document defines the technical boundaries and mathematical requirements for the Bio-Quant rebuild.

## 1. Type Registry (Pydantic Models)

All incoming data must be validated against these schemas in `src/registry.py`.

```python
class GlucoseTick(BaseModel):
    timestamp: datetime
    value: float  # mg/dL
    trend: str    # Nightscout trend string
    source: str   # 'nightscout', 'dexcom', 'sim'

class HeartRateTick(BaseModel):
    timestamp: datetime
    bpm: int
    hrv: float    # ms (SDNN or RMSSD)

class MetabolicState(BaseModel):
    glucose: GlucoseTick
    filtered_glucose: float
    velocity: float
    acceleration: float
    hrv_baseline: float
    fatigue_index: float
```

## 2. Smoothing: Kalman Filter Parameters

The 1D/2D filter in `src/smoothing.py` will use the following process noise $Q$ and measurement noise $R$:

- **Process Noise ($Q$):** $0.01$ (handles physiological changes)
- **Measurement Noise ($R$):** $1.0$ (typical CGM sensor variance)
- **State Vector ($x$):** $[G, V]^T$ (Glucose, Velocity)

## 3. Forecast Features

The forecasting engine (`src/forecaster.py`) takes a sliding window of 12 ticks (60 minutes) to generate:

1.  **30-min Forecast:** $G_{t+30}$
2.  **Risk Window:** Boolean indicating if $G < 70$ within 60 minutes.

## 4. Alert Thresholds

| Alert Type | Condition 1 | Condition 2 | Severity |
| :--- | :--- | :--- | :--- |
| **CRITICAL_HYPO** | $G < 55$ | - | EMERGENCY |
| **WARNING_HYPO** | $G_{t+30} < 70$ | $V < -1.5$ | HIGH |
| **FAINT_RISK** | $G > 300$ | $HRV < 0.7 \times \text{Baseline}$ | MEDIUM |
| **CRITICAL_HYPER** | $G > 350$ | - | HIGH |
