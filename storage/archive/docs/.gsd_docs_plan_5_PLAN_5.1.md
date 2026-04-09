---
phase: 5
plan: 1
wave: 1
depends_on: ["Plan 2.1", "Plan 3.2"]
files_modified:
  - backend/src/audit_engine.py
autonomous: true
---

# Plan 5.1: Automated Weekly Auditor

<objective>
Close the loop by building an automated reporting engine that calculates accuracy based on user feedback.

Output: Weekly Audit Report.
</objective>

<tasks>

<task type="auto">
  <name>Build Accuracy Calculator</name>
  <files>backend/src/audit_engine.py</files>
  <action>
    Parse `feedback.json` and calculate:
    - Precision: % of predictions marked "Correct".
    - False Alarms: % marked "Incorrect".
    - Alert Density: Total alerts per week.
  </action>
  <verify>python backend/src/audit_engine.py --gen-report</verify>
  <done>System can self-assess its predictive power</done>
</task>

<task type="auto">
  <name>Schedule Weekly Report Dispatch</name>
  <files>backend/src/audit_engine.py</files>
  <action>
    Integrate with Telegram to send a "Bio-Quant Weekly Summary" every Sunday at 9 PM.
  </action>
  <verify>Check telegram for summary format</verify>
  <done>User receives a professional audit of their metabolic health</done>
</task>

</tasks>
