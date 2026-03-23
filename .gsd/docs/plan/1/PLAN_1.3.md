---
phase: 1
plan: 3
wave: 2
depends_on: ["Plan 1.1", "Plan 1.2"]
files_modified:
  - src/smoothing/kalman_filter.py
  - src/smoothing/signal_quality.py
autonomous: true
type: tdd
must_haves:
  truths:
    - "Kalman Filter correctly smooths noisy CGM data"
    - "System detects and flags sensor dropouts"
---

# Plan 1.3: Signal Smoother (Kalman Filter)

<objective>
Implement the core DSP layer to clean noisy CGM data and derive reliable velocity.

Output: Kalman Filter implementation.
</objective>

<context>
Load for context:
- .gsd/docs/MATH.md
- src/registry.py
</context>

<tasks>

<task type="auto">
  <name>Implement Discrete Kalman Filter</name>
  <files>src/smoothing/kalman_filter.py</files>
  <action>
    Implement a `GlucoseKalmanFilter` class using `filterpy`.

    ```python
    from filterpy.kalman import KalmanFilter
    import numpy as np

    class GlucoseKalmanFilter:
        def __init__(self, dt=5.0):
            self.kf = KalmanFilter(dim_x=2, dim_z=1)
            self.kf.x = np.array([[100.], [0.]]) # G, V
            self.kf.F = np.array([[1., dt], [0., 1.]]) # State transition
            self.kf.H = np.array([[1., 0.]]) # Measurement function
            self.kf.P *= 10.
            self.kf.R = 1.0 # Measurement noise
            self.kf.Q = np.array([[0.01, 0.01], [0.01, 0.01]]) # Process noise
            
        def update(self, glucose_val):
            self.kf.predict()
            self.kf.update(glucose_val)
            return self.kf.x[0][0], self.kf.x[1][0] # Current G, V
    ```
  </action>
  <verify>python tests/test_kalman.py</verify>
  <done>Kalman filter provides smoothed value and derived velocity</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] A noise spike of +5 mg/dL is dampened by the filter.
- [ ] Velocity correctly reflects the trend over 3 measurements.
</verification>

<success_criteria>
- [ ] Noisy data is transformed into a clean metabolic trend.
</success_criteria>
