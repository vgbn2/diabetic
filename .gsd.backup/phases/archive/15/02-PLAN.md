---
phase: 15
plan: 2
wave: 2
depends_on: ["15.1"]
files_modified:
  - diabetic/coordinator.py
autonomous: true
user_setup: []

must_haves:
  truths:
    - "Coordinator uses MetabolicInferenceRunner as its primary forecaster"
    - "HUD displays 'Pred GLU' and 'Pred HR' from the neural engine"
  artifacts:
    - "Coordinator updated to pass last 30 snapshots to Neural Engine"
---

# Plan 15.2: Production Switchover

<objective>
Replace the legacy XGBoost math with the Multi-Task Neural Engine in the live polling coordinator.

Purpose: Upgrades real-time alerts to 1.22 RMSE precision.
Output: Live-responsive neural alerts.
</objective>

<context>
- diabetic/coordinator.py
- diabetic/ml_engine/inference.py
</context>

<tasks>

<task type="auto">
  <name>Integrate Neural Engine in Coordinator</name>
  <files>
    - diabetic/coordinator.py
  </files>
  <action>
    Initialize 'self.neural_runner = MetabolicInferenceRunner()' in __init__.
    In '_process_reading', if self.snapshots has >= 30 entries, call 'neural_runner.run_inference_on_snapshots'.
    Update 'snapshot.predict_30m' and a new 'snapshot.predicted_hr' field.
    AVOID: Breaking the fallback to kinematic prediction if snapshots < 30.
  </action>
  <verify>Check logs: Ensure 'Pred: {val} | Pred HR: {val}' appears in live output.</verify>
  <done>Neural engine is the primary source of 'predict_30m'.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Run 'python diabetic/main.py' and verify log output reflects dual-channel v14 predictions.
</verification>

<success_criteria>
- [ ] All tasks verified
</success_criteria>

---
phase: 15
plan: 3
wave: 2
depends_on: ["15.1"]
files_modified:
  - diabetic/telegram_bot/decision_matrix.py
autonomous: true
user_setup: []

must_haves:
  truths:
    - "Alerts are suppressed when predicted heart rate > 120 (Exercise Context)"
    - "Hypo alerts are prioritised regardless of cardiac status"
---

# Plan 15.3: Cardiac-Aware Safeguards

<objective>
Harden the alert logic by using predicted heart rate as a context filter.

Purpose: Reduces false positives caused by physical activity mimicking metabolic crashes.
Output: Intelligent, cardiac-filtered alert logic.
</objective>

<context>
- diabetic/telegram_bot/decision_matrix.py
</context>

<tasks>

<task type="auto">
  <name>Implement Cardiac Alert Filtering</name>
  <files>
    - diabetic/telegram_bot/decision_matrix.py
  </files>
  <action>
    Update 'evaluate(snapshot, prediction_30m)' to accept 'predicted_hr'.
    Add logic: If predicted_hr > 120, decrease alert severity for 'RAPID_DROP' unless glucose < 5.0.
    Rationale: High HR during a drop often signifies healthy exercise, not a metabolic faint risk.
  </action>
  <verify>Unit test with mock snapshot: HR 140, Drop -0.2 -> Severity 'INFO' instead of 'WARNING'</verify>
  <done>Decision Matrix correctly handles HR buffer.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] All DecisionMatrix tests pass.
</verification>

<success_criteria>
- [ ] All tasks verified
</success_criteria>
