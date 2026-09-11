# Code Atlas: Alpha Gate Confidence Ordering

> **Diátaxis Type**: Code Atlas Record | **ID**: `ATLAS-PROTO-001` | **Owner**: `diabetic.coordinator`

---

## 1. Protocol Objective

Guarantees that the historical confidence index ($C_k$) is completely calculated, decayed, and smoothed *before* evaluating neural vs. physical-chemical divergence.

---

## 2. Sequence Invariant

```mermaid
sequenceDiagram
    participant SNAP as Raw Telemetry Snapshot
    participant HIST as 90-min History Buffer
    participant CONF as Confidence Smoother
    participant GATE as Alpha Gate Divergence Check
    participant OUT as MetabolicSnapshot

    SNAP->>HIST: Append to Deque (maxlen=288)
    HIST->>CONF: Compute Raw Confidence Index
    CONF->>CONF: C_k = 0.8 * C_{k-1} + 0.2 * C_{raw}
    CONF->>OUT: Assign snapshot.confidence_index = C_k
    OUT->>GATE: Evaluate Neural vs Kinematic Divergence (using C_k)
```
