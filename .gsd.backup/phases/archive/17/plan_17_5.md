---
phase: 17
plan: 5
wave: 3
depends_on: [plan_17_1, plan_17_4]
files_modified: ["diabetic/coordinator.py", "diabetic/main.py", "diabetic/ml_engine/inference.py"]
autonomous: true
---

# Plan 17.5: Runtime Resilience & Log Hygiene

<objective>
Stabilize the event loop and clean up developer telemetry.
Purpose: Prevent silent task failures and ensure production-grade logging.
Output: Resilient coordinator and sterile stdout.
</objective>

<context>
- diabetic/coordinator.py
- diabetic/ml_engine/inference.py
</context>

<tasks>

<task type="auto">
  <name>Implement Global Exception Hygiene</name>
  <files>diabetic/coordinator.py, diabetic/ingestion/mongo.py</files>
  <action>
    Replace bare `except Exception` with specific handlers.
    Ensure `SystemExit` and `KeyboardInterrupt` are re-raised to allow clean shutdown.
    Store Task references in `self.background_tasks` to prevent GC.
  </action>
  <verify>Force a network error; verify system logs it but keeps running (for retriable errors) or exits cleanly (for fatal errors).</verify>
  <done>Zero bare exceptions remained.</done>
</task>

<task type="auto">
  <name>Productionize Inference Telemetry</name>
  <files>diabetic/ml_engine/inference.py</files>
  <action>
    Replace raw `print()` calls with `logging.getLogger("Bio-Quant.ML").info/debug`.
  </action>
  <verify>Run inference; verify log format is consistent with CLI HUD.</verify>
  <done>Stdout sterile of dev noise.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] System runs for 60 mins without "unawaited task" warnings.
- [ ] Log files contain all critical telemetry without polluting HUD.
</verification>
