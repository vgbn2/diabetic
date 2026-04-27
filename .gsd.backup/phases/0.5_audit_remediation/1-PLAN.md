---
phase: 0.5
plan: 1
wave: 1
depends_on: []
files_modified: ["diabetic/main.py", "diabetic/ml_engine/inference.py", "diabetic/utils/audit_logger.py"]
autonomous: true
---

# Plan 0.5.1: Critical Engine Safety Fixes

<objective>
Resolve the immediate startup crash and implement safety-critical hardcoded interval and clamping fixes.

Purpose: Prevent boot failure and ensure neural inference obeys physiological bounds.
Output: Patched main.py, inference.py, and audit_logger.py.
</objective>

<context>
Load for context:
- .gsd/SPEC.md
- diabetic/main.py
- diabetic/ml_engine/inference.py
- diabetic/utils/audit_logger.py
</context>

<tasks>

<task type="auto">
  <name>Fix main.py Startup Crash</name>
  <files>diabetic/main.py</files>
  <action>
    Remove 'await' from the call to 'config.validate_config()'. 
    The method in config.py is synchronous, and awaiting it causes a TypeError on boot.
  </action>
  <verify>python -c "from diabetic.config import config; config.validate_config()"</verify>
  <done>Coordinator starts without TypeError.</done>
</task>

<task type="auto">
  <name>Replace Hardcoded Intervals in Inference</name>
  <files>diabetic/ml_engine/inference.py</files>
  <action>
    Replace '2.5' and '5.0' with 'config.SAMPLING_INTERVAL_MINS' in '_prepare_temporal_tensor' and 'run_inference_on_snapshots'.
    AVOID: Keeping any literal 2.5 or 5.0 as they lead to scale mismatch if config changes.
  </action>
  <verify>grep "config.SAMPLING_INTERVAL_MINS" diabetic/ml_engine/inference.py</verify>
  <done>Intervals are dynamic and config-driven.</done>
</task>

<task type="auto">
  <name>Implement Output Clamping & GC Protection</name>
  <files>diabetic/ml_engine/inference.py, diabetic/utils/audit_logger.py</files>
  <action>
    1. In inference.py, clamp the glucose prediction to [PHYSIO_FLOOR, FAINT_GLUCOSE + 5.0].
    2. In audit_logger.py, store the background logging task in 'self.background_tasks' to prevent immediate garbage collection.
  </action>
  <verify>python scratch/verify_clamping.py</verify>
  <done>Predictions are safe; background tasks are persistent.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] 'main.py' no longer crashes on boot.
- [ ] 'inference.py' uses config-driven intervals.
- [ ] Background logging tasks are not garbage collected.
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] System stability confirmed
</success_criteria>
