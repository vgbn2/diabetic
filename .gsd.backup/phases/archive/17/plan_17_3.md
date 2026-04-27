---
phase: 17
plan: 3
wave: 2
depends_on: [plan_17_1, plan_17_2]
files_modified: ["diabetic/telegram_bot/handlers.py", "diabetic/config.py"]
autonomous: false
user_setup:
  - service: telegram
    why: "Personalized sender IDs"
    env_vars:
      - name: TELEGRAM_AUTHORIZED_IDS
        source: "CSV of user/caregiver Telegram IDs"
---

# Plan 17.3: Security Shield & Callback Sanitization

<objective>
Lock down medical commands and sanitize user callbacks.
Purpose: Prevent unauthorized intervention and injection.
Output: Identity-aware bot handlers.
</objective>

<context>
- diabetic/telegram_bot/handlers.py
- diabetic/config.py
</context>

<tasks>

<task type="auto">
  <name>Implement Multi-ID Authorization</name>
  <files>diabetic/config.py, diabetic/telegram_bot/handlers.py</files>
  <action>
    Update `config.py` to parse `TELEGRAM_AUTHORIZED_IDS` as a set of ints.
    Create an `authorized_only` decorator that checks `update.effective_user.id`.
  </action>
  <verify>Call `/meal` from a non-authorized ID; verify 403 response.</verify>
  <done>Commands restricted to Patient and Caregiver.</done>
</task>

<task type="auto">
  <name>Implement Callback Allowlist</name>
  <files>diabetic/telegram_bot/handlers.py</files>
  <action>
    Define `VALID_ALERT_ACTIONS` and sanitize `alert_type` before database logging.
    AVOID: bare string interpolation into logs without allowlist check.
  </action>
  <verify>Send malformed callback data; verify rejection in logs.</verify>
  <done>User feedback sanitized.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Unauthorized users cannot execute commands.
- [ ] Malformed callbacks do not cause database integrity issues.
</verification>
