---
phase: 0.5
plan: 3
wave: 2
depends_on: ["0.5.1", "0.5.2"]
files_modified: ["diabetic/ml_engine/twin.py", "diabetic/coordinator.py", "diabetic/ml_engine/oracle.py"]
autonomous: true
---

# Plan 0.5.3: Architectural Coupling & Auto-Tune Decay

<objective>
Integrate orphaned predictive models (BasalOracle, XGBoost) and implement exponential decay for physiological tuning to prevent unbounded parameter drift.

Purpose: Harmonize all metabolic models and ensure long-term stability of the Digital Twin.
Output: Integrated coordinator.py, patched twin.py.
</objective>

<context>
Load for context:
- diabetic/ml_engine/twin.py
- diabetic/coordinator.py
- diabetic/ml_engine/oracle.py
- diabetic/ml_engine/predictor.py
</context>

<tasks>

<task type="auto">
  <name>Implement auto_tune EMA Decay</name>
  <files>diabetic/ml_engine/twin.py</files>
  <action>
    Refactor 'auto_tune' to use an EMA update rule: self.csf = ((1 - decay) * self.csf) + (decay * (self.csf * adjustment)).
    Use a decay factor representing a 72-hour half-life.
    Also, ensure 'predict_monte_carlo' passes stochastic=True to sub-calls.
  </action>
  <verify>python scratch/test_ema_decay.py</verify>
  <done>CSF/ISF adjustments decay back to baseline over time.</done>
</task>

<task type="auto">
  <name>Wire Orphans into Coordinator</name>
  <files>diabetic/coordinator.py</files>
  <action>
    1. Instantiate 'BasalOracle' and 'GlucoseForecaster' (XGBoost) in Coordinator.__init__.
    2. Integrate BasalOracle output into the 4h trajectory calculation.
    3. Use GlucoseForecaster as a secondary check in '_process_reading'.
    4. Invoke SignalQuality.check_data_gap() to pause filter updates during long gaps.
  </action>
  <verify>python -c "from diabetic.coordinator import Coordinator; c=Coordinator(); print(c.oracle, c.forecaster)"</verify>
  <done>Orphaned models are active in the live telemetry pipeline.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] 4h trajectories include harmonic basal glide.
- [ ] XGBoost predictions are logged alongside CNN results.
- [ ] Sensor gaps trigger the gap-check logic.
</verification>

<success_criteria>
- [ ] Full architectural coupling achieved
- [ ] Long-term parameter stability (EMA) confirmed
</success_criteria>
