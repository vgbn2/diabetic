---
phase: 0.7
plan: 3
wave: 1
depends_on: []
files_modified: ["diabetic/registry.py", "diabetic/telegram_bot/decision_matrix.py", "diabetic/config.py"]
autonomous: true
must_haves:
  truths:
    - "CardiacReading object supports 'source' parameter"
    - "Stress anomalies no longer register as Faint Risk alerts to the CircuitBreaker"
  artifacts: []
---

# Plan 0.7.3: Registry Types & Alert Collisions

<objective>
Fix validation gaps and logical overlaps regarding core Pydantic registries and Neural Alert Matrix structures (H1, H4).

Purpose: Prevent runtime validation crashes upon enabling cardiac sensors, and distinguish anomalies in the audit logs.
Output: Safely validated states and explicit alert pipelines.
</objective>

<context>
Load for context:
- diabetic/registry.py
- diabetic/telegram_bot/decision_matrix.py
- diabetic/config.py
</context>

<tasks>

<task type="auto">
  <name>Fix H1: Cardiac Reading Source Registry</name>
  <files>diabetic/registry.py</files>
  <action>
    Add `source: str = "ble"` to the `CardiacReading` Pydantic model. 
    AVOID: Altering the main parameter orders affecting positional init (use kwargs validation where appropriate).
  </action>
  <verify>python -c "from diabetic.registry import CardiacReading; CardiacReading(timestamp='2026-01-01T00:00:00Z', bpm=80, hrv=50.0, source='synthetic_v1')"</verify>
  <done>CardiacReading allows 'source' without throwing ValidationError</done>
</task>

<task type="auto">
  <name>Fix H4: Decision Matrix Collision Resolve</name>
  <files>diabetic/telegram_bot/decision_matrix.py, diabetic/config.py</files>
  <action>
    Modify `DecisionMatrix.evaluate` anomaly clause (Section 2b). Change the `type="FAINT_RISK"` to `type="STRESS_ANOMALY"`.
    Go to `diabetic/config.py` and register the new key `"STRESS_ANOMALY": "🫀 STRESS ANOMALY"` into `UI_SETTINGS` so it logs and renders correctly in Telegram.
  </action>
  <verify>grep "type=\"STRESS_ANOMALY\"" diabetic/telegram_bot/decision_matrix.py</verify>
  <done>Stress anomalies register under their distinct key, preventing cooldown overlap with actual FAINT risks.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Cardiac synthesizer does not crash at runtime.
- [ ] Anomaly events fire distinctly.
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
