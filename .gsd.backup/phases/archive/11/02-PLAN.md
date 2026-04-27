---
phase: 11
plan: 2
wave: 2
depends_on: ["11.1"]
files_modified: ["diabetic/coordinator.py", "diabetic/telegram_bot/handlers.py"]
autonomous: true
---

# Plan 11.2: Agency Hook & Oracle Logic

<objective>
Implement the core active agency loop: recall historical patterns and stateful user feedback.
</objective>

<context>
- .gsd/SPEC.md
- diabetic/coordinator.py
- diabetic/telegram_bot/handlers.py
- diabetic/ml_engine/metabolic_palace.py
</context>

<tasks>

<task type="auto">
  <name>Implement Coordinator Feedback Logic</name>
  <files>diabetic/coordinator.py</files>
  <action>
    Add `receive_feedback(self, alert_id, action, notes=None)` method.
    Link it to `self.audit.log_feedback` and `self.palace.remember_snapshot`.
    Integrate `self.palace.recall_patterns` into `_process_reading` to fetch clinical context before alerting.
    If historical "faint" or "dizzy" events overlap current BG/Velocity, upgrade alert to EMERGENCY.
  </action>
  <verify>Manual recall check</verify>
  <done>Coordinator active recall is operational.</done>
</task>

<task type="auto">
  <name>Implement Telegram Stateful Feedback</name>
  <files>diabetic/telegram_bot/handlers.py</files>
  <action>
    Update `_handle_button` to start a 120s "Listening Window" for the user.
    Add a handler to catch the next text message after an alert confirmation and route it as a "Clinical Note" to the Coordinator.
    Implement "False Alarm" cooldown reset: clicking False Alarm must reset the `CircuitBreaker` for that alert type.
  </action>
  <verify>Bot interaction</verify>
  <done>User can supplement alerts with clinical notes and reset cooldowns.</done>
</task>

</tasks>

<verification>
- [ ] Mock alert followed by text note results in a new record in MemPalace `l5_user_feedback`.
- [ ] Subsequent simulation shows "Historical Context" in alert dispatches.
</verification>
