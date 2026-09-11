# Code Atlas: Digital Twin Impulse Absorption

> **Diátaxis Type**: Code Atlas Record | **ID**: `ATLAS-ALG-003` | **Owner**: `diabetic.ml_engine.twin`

---

## 1. Mathematical Formulation

Models carbohydrate absorption rate via biphasic impulse response:

$$C(t) = \frac{t}{\tau^2} e^{-t/\tau}, \quad t \ge 0$$

$$\Delta g_{carb}(t) = \text{Carbs} \cdot S_{carb} \cdot C(t)$$

### Insulin Action & Decay
$$I(t) = \frac{S_{ins}}{\tau_2 - \tau_1} \left( e^{-t/\tau_2} - e^{-t/\tau_1} \right)$$

---

## 2. Invariants & Guardrails
- Time step integration defends against non-positive durations:
  ```python
  # ponytail: guard zero/negative duration
  if dt <= 0:
      return 0.0
  ```
