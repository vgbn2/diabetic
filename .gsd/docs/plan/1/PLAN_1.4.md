---
phase: 1
plan: 4
wave: 3
depends_on: ["Plan 1.3"]
files_modified:
  - src/smoothing/signal_quality.py
autonomous: true
---

# Plan 1.4: Anomaly Detection Logic (De-risking)

<objective>
Implement specific guards to distinguish between medical emergencies and sensor noise (compression lows).

Output: Enhanced signal quality guard.
</objective>

<tasks>

<task type="auto">
  <name>Implement Compression Low Detector</name>
  <files>src/smoothing/signal_quality.py</files>
  <action>
    Add logic to flag readings with `unphysiological_drop=True`.
    
    ```python
    def detect_compression_low(last_val, current_val, dt=5):
        rate = (current_val - last_val) / dt
        # Humanly impossible to drop 50 points in 5 mins
        if rate < -8.0: 
            return True 
        return False
    ```
  </action>
  <verify>python tests/test_signal_quality.py</verify>
  <done>System ignores sensor artifacts during sleep</done>
</task>

</tasks>
