---
phase: 0.5
plan: 1
wave: 1
depends_on: []
files_modified:
  - diabetic/coordinator.py
  - diabetic/ml_engine/inference.py
autonomous: true
user_setup: []

must_haves:
  truths:
    - "Regime detection persists after 300 readings"
    - "Auto-tune compares actual peak vs predicted peak"
    - "Inference returns results without scalar crash"
  artifacts:
    - "diabetic/coordinator.py utilizes self.regime_step_count"
    - "diabetic/ml_engine/inference.py returns Dict[str, float]"
---

# Plan 0.5.1: Core Logic & Inference Remediation

<objective>
Stabilize the core engine by fixing three critical logic bugs that cause silent degradation [C1, C2] or runtime crashes [C3].
</objective>

<context>
Load for context:
- diabetic/coordinator.py
- diabetic/ml_engine/inference.py
- .gsd/implementation_plan.md
</context>

<tasks>

<task type="auto">
  <name>Fix Regime Freeze [C1] and Peak Tracking [C2]</name>
  <files>diabetic/coordinator.py</files>
  <action>
    1. Initialize `self.regime_step_count = 0` and `self.actual_meal_peak = 0.0` in `Coordinator.__init__`.
    2. In `_process_reading`:
       - Increment `self.regime_step_count`.
       - Change regime trigger to use `self.regime_step_count % regime_trigger == 0`.
       - If a meal window is active (`self.meal_tune_pending`), update `self.actual_meal_peak = max(self.actual_meal_peak, reading.value)`.
       - Update `auto_tune` call to use `self.actual_meal_peak` instead of `reading.value`.
    AVOID: Using `len(self.snapshots)` for modulo checks as it caps at 300.
  </action>
  <verify>Log 300+ dummy readings in a test script and confirm `detect_regime` is called at step 432.</verify>
  <done>Regime detection fires periodically regardless of buffer size; auto-tune uses actual observed peak.</done>
</task>

<task type="auto">
  <name>Fix Multi-Task Inference Crash [C3]</name>
  <files>diabetic/ml_engine/inference.py</files>
  <action>
    1. Update `run_live_inference` to return the multi-task results properly.
    2. Instead of `output.item()`, extract both glucose and heart rate.
    3. Return a dictionary: `{"glucose": float(output[0][0]), "heart_rate": float(output[0][1])}`.
    AVOID: `.item()` on tensors with more than one element.
  </action>
  <verify>Run `python -m diabetic.ml_engine.inference` against a test CSV; confirm no RuntimeError.</verify>
  <done>Live inference returns both predicted signals correctly.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Regime detection trigger is decoupled from buffer length.
- [ ] `actual_meal_peak` is tracked during the 4h window.
- [ ] `.item()` call is removed from `inference.py`.
</verification>

<success_criteria>
- [ ] No more `RuntimeError` during live inference.
- [ ] `auto_tune` adjustment logic is clinically sound (peak vs peak).
</success_criteria>
