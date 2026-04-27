---
phase: 0.7
plan: 5
wave: 1
depends_on: []
files_modified: ["diabetic/coordinator.py"]
autonomous: true
must_haves:
  truths:
    - "Insulin on board scales correctly over 4 hours mimicking bi-exponential curves"
  artifacts: []
---

# Plan 0.7.5: Physiological Modeling Decay

<objective>
Refactor pharmacodynamics. Shift the coordinator's flat approximations to the Twin's native exponential functions (C2).

Purpose: Increase prediction fidelity for IOB (Insulin on Board) and COB (Carbs on Board) estimation inside the live loop.
Output: Real-time loop using medically-aligned temporal curves.
</objective>

<context>
Load for context:
- diabetic/coordinator.py
</context>

<tasks>

<task type="auto">
  <name>Fix C2: Active Carb/Insulin Bi-Exponential Sourcing</name>
  <files>diabetic/coordinator.py</files>
  <action>
    Modify `_process_reading` Section 3b ("Estimate Active Carbs..."). Remove the simplistic flat calculations `(1.0 - dt_m / 240.0)`.
    Compute the time index slice (`int(dt_m / SAMPLING_INTERVAL_MINS)`) and map it against the `self.twin` simulator outputs or expose explicit exponential tracker methods directly in `DigitalTwin`.
    AVOID: Reintroducing flat fallbacks. It should reflect actual pharmacokinetic tau/decay profiles already existing in the twin.
  </action>
  <verify>grep "1.0 - dt_m / 240.0" diabetic/coordinator.py -c should return 0</verify>
  <done>IOB and COB variables correctly decay nonlinearly representing physical absorption properties.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Pharmacokinetics reflect complex absorption logic.
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
