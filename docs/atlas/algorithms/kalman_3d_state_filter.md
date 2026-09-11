# Code Atlas: 3D Kalman State Filter

> **Diátaxis Type**: Code Atlas Record | **ID**: `ATLAS-ALG-001` | **Owner**: `diabetic.dsp.kalman`

---

## 1. Mathematical Formulation

Tracks physiological continuous kinematic state $\mathbf{x} = [g, v, a]^T$:

$$\mathbf{x}_k = \mathbf{F} \mathbf{x}_{k-1} + \mathbf{w}_{k-1}, \quad \mathbf{w} \sim \mathcal{N}(0, \mathbf{Q})$$

$$z_k = \mathbf{H} \mathbf{x}_k + v_k, \quad v \sim \mathcal{N}(0, R)$$

### State Transition Matrix ($\mathbf{F}$)
$$\mathbf{F} = \begin{bmatrix} 1 & \Delta t & \frac{1}{2}\Delta t^2 \\ 0 & 1 & \Delta t \\ 0 & 0 & 1 \end{bmatrix}$$

---

## 2. Complexity & Numerical Invariants

- **Computational Complexity**: $O(1)$ constant time per update cycle.
- **Space Complexity**: $O(1)$ fixed matrix storage ($3 \times 3$).
- **Degenerate Covariance Guard**:
  ```python
  # ponytail: pinv fallback for degenerate covariance
  try:
      S_inv = np.linalg.inv(S)
  except np.linalg.LinAlgError:
      S_inv = np.linalg.pinv(S)
  ```
