---
phase: 9
plan: 02
wave: 1
depends_on: [9.01]
files_modified: [diabetic/coordinator.py, diabetic/ml_engine/twin.py]
autonomous: true

must_haves:
  truths:
    - "Telegram-logged meals override concurrent Nightscout treatments in prediction logic"
    - "auto_tune adjusts CSF based on meal-absorption residuals, not short-term drift"
  artifacts:
    - "Coordinator track 'pending_meal_forecast' for feedback comparison"
---

# Plan 9.02: Predictive Loop & Arbitration (C2, L1)

<objective>
Fix the broken Digital Twin personalization loop by correctly arbitrating meal sources and using non-kinematic residuals for auto-tuning.

Purpose: Currently, `auto_tune` personalizes the user's metabolism based on 30-minute kinematic drift, which is useless for multi-hour meal sensitivity tuning. Additionally, manually logged meals (Telegram) are ignored in favor of stale Nightscout treatment data.
Output: A personalization loop that correctly adapts Carbohydrate Sensitivity Factor (CSF) based on how the body actually handled a specific meal.
</objective>

<context>
Load for context:
- diabetic/coordinator.py
- diabetic/ml_engine/twin.py
</context>

<tasks>

<task type="auto">
  <name>Wire _active_meal Arbitration (C2 Fix)</name>
  <files>diabetic/coordinator.py</files>
  <action>
    In `_process_reading`, replace the simple `last_meal` inheritance from the previous snapshot with a call to `self._active_meal()`.
    This ensures that `new_snapshot.last_meal` always honors the Telegram priority logic (meals within 4h).
    AVOID: Breaking the fallback to Nightscout treatments if no Telegram meal is fresh.
  </action>
  <verify>Simulation logs should show Telegram carbs in snapshot even if NS treatment exists.</verify>
  <done>Telegram meals are successfully injected into the metabolic pipeline.</done>
</task>

<task type="auto">
  <name>Implement Meal-Residual Auto-Tuning (L1 Fix)</name>
  <files>diabetic/coordinator.py</files>
  <action>
    1. Update `Coordinator` to store the predicted final glucose value from the 4-hour meal forecast when a meal is logged.
    2. When the 230-minute `meal_tune_pending` window closes, compare the *actual* glucose against this *stored prediction*.
    3. Feed this long-horizon residual into `twin.auto_tune` instead of the 30m kinematic residual.
    AVOID: Triggering `auto_tune` if the meal was too small to provide a clean signal (<15g).
  </action>
  <verify>Check logs for "Auto-tuning Digital Twin via Meal Residual: {X}" after 3.8 hours.</verify>
  <done>CSF personalization is driven by physiological meal response.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] No `NoneType` errors when accessing `pending_meal_forecast`
- [ ] `auto_tune` logs show non-zero adjustments after a simulated meal
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
