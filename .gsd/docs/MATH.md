# Bio-Quant Metabolic Math & DSP Logic

## 1. Digital Signal Processing (DSP)

The system smoothing logic in `src/smoothing.py` utilizes a **Discrete Linear Kalman Filter**.

### State Equation
$$x_k = F x_{k-1} + B u_k + w_k$$
Where the state vector $x = [G, V]^T$ representing Glucose level and Velocity.

### Transition Matrix (F)
Assuming 5-minute intervals between CGM readings:
$$F = \begin{bmatrix} 1 & 5 \\ 0 & 1 \end{bmatrix}$$

## 2. Metabolic Indices

### Low Blood Glucose Index (LBGI)
Used to quantify the risk of a hypoglycemic crash.
$$f(g) = 1.509 \times [\ln(g)^{1.084} - 5.381]$$
$$risk(g) = 10 \times f(g)^2 \text{ if } f(g) < 0 \text{ else } 0$$

### High Blood Glucose Index (HBGI)
Used to quantify the risk of hyperglycemia-induced syncope.
$$risk(g) = 10 \times f(g)^2 \text{ if } f(g) > 0 \text{ else } 0$$

## 3. Faint Risk (Dehydration Proxy)

The faint risk alert is triggered by the intersection of high glucose and low heart rate variability (HRV).

**Detection Logic:**
$$Alert_{Faint} = (G > 300) \land (HRV < 0.7 \times HRV_{Baseline})$$
Where $HRV$ is calculated using the RMSSD (Root Mean Square of Successive Differences) of the R-R intervals.
