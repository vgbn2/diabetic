---
phase: 0.7
plan: 4
wave: 1
depends_on: []
files_modified: ["diabetic/ui/visualizer.py", "diabetic/telegram_bot/handlers.py"]
autonomous: true
must_haves:
  truths:
    - "Telegram /meal commands safely clamp numeric bounds"
    - "Python 3.10+ does not emit DeprecationWarning on async thread executions"
  artifacts: []
---

# Plan 0.7.4: Interface Bounds & Deprecations

<objective>
Fix UI thread deprecation warnings and missing input sanitizations from external requests (H5, H8).

Purpose: Modernize thread bindings and guarantee system reliability against malicious or mistaken inputs.
Output: Rock-solid Telegram input boundaries and headless visualizer execution.
</objective>

<context>
Load for context:
- diabetic/ui/visualizer.py
- diabetic/telegram_bot/handlers.py
</context>

<tasks>

<task type="auto">
  <name>Fix H5: Update Event Loop Semantics</name>
  <files>diabetic/ui/visualizer.py</files>
  <action>
    Switch `asyncio.get_event_loop()` to `asyncio.get_running_loop()`. 
    Wrap it in a Try-Except capturing `RuntimeError` to provide a synchronous rendering fallback when called outside a loop.
  </action>
  <verify>grep get_running_loop diabetic/ui/visualizer.py</verify>
  <done>Code triggers no asyncio deprecation warnings on boot</done>
</task>

<task type="auto">
  <name>Fix H8: Telegram Bot Input Integrity</name>
  <files>diabetic/telegram_bot/handlers.py</files>
  <action>
    Add input bounds to the `/meal` command inside `_meal_cmd`. Ensure `grams` variable is securely clamped `if grams <= 0 or grams > 500`. 
    Send an error response `await update.message.reply_text("...")` and `return` early if out of bounds.
    AVOID: Breaking standard valid parsing.
  </action>
  <verify>grep "> 500" diabetic/telegram_bot/handlers.py</verify>
  <done>Meals logged securely within physiological possibilities.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Extreme meal values cannot bypass into the Digital Twin
- [ ] No `asyncio` loop errors print to terminal
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
