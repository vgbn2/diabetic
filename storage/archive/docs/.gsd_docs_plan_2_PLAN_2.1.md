---
phase: 2
plan: 1
wave: 1
depends_on: ["Plan 1.1"]
files_modified:
  - frontend/src/telegram_hub.py
  - frontend/src/keyboard_builder.py
autonomous: true
---

# Plan 2.1: Interactive Telegram Bot

<objective>
Implement the interactive front-end that allows the user to verify predictions via inline buttons.

Output: Telegram client with prediction + feedback UI.
</objective>

<tasks>

<task type="auto">
  <name>Build Interactive Prediction Message</name>
  <files>frontend/src/telegram_hub.py</files>
  <action>
    Implement an alert message that includes:
    1. The Prediction (e.g., "Predicted 65 mg/dL in 30m").
    2. Inline Buttons: [✅ Correct] [❌ Incorrect] [⏳ Too Early].
  </action>
  <verify>python frontend/src/telegram_hub.py --test-alert</verify>
  <done>User can interact with predictions in real-time</done>
</task>

<task type="auto">
  <name>Implement Feedback Callback Handler</name>
  <files>frontend/src/keyboard_builder.py</files>
  <action>
    Handle incoming `callback_query`.
    - Function: save the user's choice (Correct/Incorrect) to a local `feedback.json`.
  </action>
  <verify>Click button in Telegram and check feedback.json</verify>
  <done>Feedback is captured for the weekly audit loop</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Tapping a button triggers a 'Feedback Received' notification in Telegram.
- [ ] Every prediction alert has an associated ID for tracking.
</verification>
