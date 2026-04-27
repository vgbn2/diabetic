---
phase: 0.5
plan: 4
wave: 2
depends_on: ["0.5.1"]
files_modified: ["diabetic/telegram_bot/decision_matrix.py", "diabetic/utils/temporal.py", "diabetic/utils/scaling_engine.py", "diabetic/utils/schedule.py"]
autonomous: true
---

# Plan 0.5.4: Interface Cleanup & User Enhancements

<objective>
Resolve alert type collisions, handle Pydantic validation for schedules, and implement requested placeholders for cultural/scaling logic.

Purpose: Harmonize alert logs and prepare for multi-tenant regional scaling.
Output: Patched decision_matrix.py, temporal.py, scaling_engine.py, and schedule.py.
</objective>

<context>
Load for context:
- diabetic/telegram_bot/decision_matrix.py
- diabetic/utils/temporal.py
- diabetic/utils/scaling_engine.py
- diabetic/utils/schedule.py
</context>

<tasks>

<task type="auto">
  <name>Rename Alert Collisions & Fix Schedule Validation</name>
  <files>diabetic/telegram_bot/decision_matrix.py, diabetic/utils/schedule.py</files>
  <action>
    1. In decision_matrix.py, rename the alert type in the 'STRESS_ANOMALY' block from 'FAINT_RISK' to 'BIOLOGICAL_DECOUPLING'.
    2. In schedule.py, filter the 'entry' dictionary keys to only include those defined in 'ScheduleEvent' before instantiation.
  </action>
  <verify>python -c "from diabetic.registry import ScheduleEvent; d={'name':'test', 'type':'WORK', 'extra':1}; print(ScheduleEvent(**{k:v for k,v in d.items() if k in ScheduleEvent.__fields__}))"</verify>
  <done>Alert types are unique; Schedule validation is robust.</done>
</task>

<task type="auto">
  <name>Implement Scaling & Temporal Placeholders</name>
  <files>diabetic/utils/temporal.py, diabetic/utils/scaling_engine.py</files>
  <action>
    1. In temporal.py, add the requested documentation and placeholders for festival/holiday integration.
    2. In scaling_engine.py, fix the hardcoded year and implement the gender-specific weight/height scaling logic discussed in developer comments.
  </action>
  <verify>grep "gender" diabetic/utils/scaling_engine.py</verify>
  <done>User-requested logic hooks are implemented.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] 'STRESS_ANOMALY' alerts log as 'BIOLOGICAL_DECOUPLING'.
- [ ] Schedule overrides with extra keys do not crash.
- [ ] Scaling engine uses current year and gender-aware logic.
</verification>

<success_criteria>
- [ ] UX/UI consistency restored
- [ ] Regional scaling foundations laid
</success_criteria>
