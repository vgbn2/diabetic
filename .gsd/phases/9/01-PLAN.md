---
phase: 9
plan: 01
wave: 1
depends_on: []
files_modified: [requirements.txt, diabetic/coordinator.py, diabetic/main.py, diabetic/telegram_bot/decision_matrix.py, diabetic/telegram_bot/handlers.py, diabetic/utils/audit_logger.py]
autonomous: true

must_haves:
  truths:
    - "No TypeError occurs when combining internal meal timestamps with Nightscout timestamps"
    - "Project installs successfully with all necessary packages"
  artifacts:
    - "requirements.txt matches what is actually imported"
---

# Plan 9.01: Environment & Timezone Fixes

<objective>
Fix the critical C1 crash (Timezone offset mismatch) and S1 error (broken requirements.txt) identified in the comprehensive audit.

Purpose: Nightscout sends timezone-aware datetimes (+00:00). Local `datetime.now()` returns naive datetimes. This mismatch crashes the python process instantly upon subtraction in `_process_reading`. The requirements file prevents a clean deployment.
Output: A stable live-mode foundation that won't crash on user meal input, and a deployable package state.
</objective>

<context>
Load for context:
- .gsd/STATE.md
- diabetic/coordinator.py
- requirements.txt
</context>

<tasks>

<task type="auto">
  <name>Synchronize requirements.txt</name>
  <files>requirements.txt</files>
  <action>
    Add missing required packages: `httpx`, `motor`, `rich`, `pydantic-settings`.
    Remove unused packages: `groq`, `flask`, `flask-cors`, `scikit-learn`.
    Keep existing core dependencies (xgboost, pydantic, telegram-bot, etc.).
    AVOID: Altering the versions of core packages (pandas, numpy) unecessarily.
  </action>
  <verify>pip install -r requirements.txt</verify>
  <done>All imports can be resolved without ModuleNotFoundError.</done>
</task>

<task type="auto">
  <name>Unify Timezones (C1 Fix)</name>
  <files>
    diabetic/coordinator.py
    diabetic/telegram_bot/decision_matrix.py
    diabetic/telegram_bot/handlers.py
    diabetic/utils/audit_logger.py
    diabetic/main.py
  </files>
  <action>
    Find every instance of `datetime.now()` that generates a timestamp for domain events or logs.
    Convert to `datetime.now(timezone.utc)`.
    Ensure `from datetime import timezone` is imported in each file.
    AVOID: Leaving any local `datetime.now()` that might be compared to a Nightscout timestamp later.
  </action>
  <verify>python -c "from diabetic.coordinator import Coordinator"</verify>
  <done>No `TypeError` regarding offset-naive vs offset-aware datetimes can trigger.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Requirements install clean
- [ ] No syntax errors introduced during timezone replacements
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
