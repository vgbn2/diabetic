# Code Atlas: Kovatchev Risk Transform

> **Diátaxis Type**: Code Atlas Record | **ID**: `ATLAS-ALG-002` | **Owner**: `diabetic.dsp.metabolic_math`

---

## 1. Mathematical Formulation

Transforms blood glucose measurements into a symmetrical risk space:

$$f(g) = 1.509 \cdot \left( \ln(g)^{1.084} - 5.381 \right)$$

$$r(g) = 10 \cdot f(g)^2$$

$$\text{LBGI} = \begin{cases} r(g) & \text{if } f(g) < 0 \\ 0 & \text{otherwise} \end{cases}$$

$$\text{HBGI} = \begin{cases} r(g) & \text{if } f(g) > 0 \\ 0 & \text{otherwise} \end{cases}$$

$$\text{RI} = \text{LBGI} + \text{HBGI}$$

---

## 2. Invariants & Clinical Boundaries

- **Input Bound**: $g \ge 1.0 \text{ mmol/L}$ (defensive clamping prevents negative logarithms).
- **Target Euglycemia**: When $g \approx 6.2 \text{ mmol/L}$, $f(g) = 0$ and $RI = 0$.
