---
phase: 4
plan: 1
wave: 1
depends_on: ["Plan 3.2"]
files_modified:
  - src/comms/telegram_notifier.py
autonomous: true
user_setup:
  - service: Telegram Bot
    why: "Primary alert delivery"
    env_vars:
      - name: TELEGRAM_TOKEN
      - name: USER_TELEGRAM_ID
---

# Plan 4.1: Telegram Notifier (User/Caregiver)

<objective>
Implement the mission-critical notification bridge to the outside world.

Output: Telegram bot integration.
</objective>

<context>
Load for context:
- .gsd/docs/SAFETY_MANIFEST.md
- src/config.py
</context>

<tasks>

<task type="auto">
  <name>Build Async Telegram Client</name>
  <files>src/comms/telegram_notifier.py</files>
  <action>
    Implement `TelegramNotifier` using `httpx` for lightweight async calls.
    - Function: `send_alert(message, severity)`.
    - Logic: if severity == CRITICAL, message BOTH User and Caregiver.
    - Logic: if severity == WARNING, message User only.
  </action>
  <verify>python src/comms/telegram_notifier.py --test "Test Alert"</verify>
  <done>Notifications are delivered with appropriate prioritization</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Alerts arrive within 2 seconds of the guard triggering.
- [ ] Emergency messages are distinct from status updates.
</verification>

<success_criteria>
- [ ] Telegram bridge is resilient to intermittent network failures.
</success_criteria>
