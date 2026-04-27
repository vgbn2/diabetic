---
phase: 0.5
plan: 3
wave: 2
depends_on: ["0.5.1"]
files_modified:
  - diabetic/utils/scaling_engine.py
  - diabetic/telegram_bot/handlers.py
  - diabetic/ml_engine/twin.py
  - diabetic/telegram_bot/decision_matrix.py
autonomous: true
user_setup: []

must_haves:
  truths:
    - "Activity levels are dynamic (not hardcoded 0.5)"
    - "IOB follows S-curve PK model"
    - "Async feedback tasks are tracked"
  artifacts:
    - "scaling_engine.py utilizes config.PATIENT_ACTIVITY_LEVEL"
    - "DecisionMatrix correctly throttles EMERGENCY alerts"
---

# Plan 0.5.3: Behavioral & Context Layer

<objective>
Harden the behavioral modeling and interface logic to eliminate mismatches between training and inference [H1, H2, H4, M3, M5].
</objective>

<context>
Load for context:
- diabetic/utils/scaling_engine.py
- diabetic/telegram_bot/handlers.py
- diabetic/ml_engine/twin.py
- diabetic/telegram_bot/decision_matrix.py
</context>

<tasks>

<task type="auto">
  <name>Implement Activity Mapping & Twin Consistency [H1, H2, M3, M4]</name>
  <files>
    - diabetic/utils/scaling_engine.py
    - diabetic/ml_engine/twin.py
    - diabetic/coordinator.py
  </files>
  <action>
    1. In `scaling_engine.py`, add `ACTIVITY_MAP` (e.g., SEDENTARY: 0.3, MODERATE: 0.5, ATHLETE: 0.8) and use `PATIENT_ACTIVITY_LEVEL`.
    2. Fix `ScalingEngine` to use `datetime.now(timezone.utc)` for diagnosis age.
    3. Refactor IOB/COB calculation in `coordinator.py` to use `self.twin.simulate_insulin_impact` instead of linear approximation.
    4. Unify additive/multiplicative resistance in `twin.py`.
    AVOID: Unbalanced resistance math that creates extreme ISF sensitivity.
  </action>
  <verify>Inspect the static vector returned by `assemble_static_vector`; verify IOB curve is non-linear.</verify>
  <done>Inference feature vectors match training; pharmacodynamics are consistent across engine layers.</done>
</task>

<task type="auto">
  <name>Harden Alerting & Callback Safety [H4, M5]</name>
  <files>
    - diabetic/telegram_bot/handlers.py
    - diabetic/telegram_bot/decision_matrix.py
  </files>
  <action>
    1. In `handlers.py`, register the `log_feedback` task with the coordinator's tracker.
    2. In `decision_matrix.py`, update `CircuitBreaker.can_alert` to record the timestamp even for `EMERGENCY` severity.
    AVOID: Silently dropping async tasks.
  </action>
  <verify>Trigger feedback and check audit logs; verify no alert spam after emergency resolution.</verify>
  <done>Feedback is reliably logged; alert fatigue is minimized post-emergency.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Patient activity level is correctly mapped in feature vectors.
- [ ] IOB decay follows the PK model.
- [ ] Feedback logs are persistent.
</verification>

<success_criteria>
- [ ] Neural inference matches training distribution.
- [ ] Zero silent failures in Telegram callback handlers.
</success_criteria>
