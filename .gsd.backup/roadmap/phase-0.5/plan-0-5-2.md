---
phase: 0.5
plan: 2
wave: 1
depends_on: []
files_modified:
  - diabetic/dsp/kalman.py
  - diabetic/dsp/metabolic_math.py
  - diabetic/medical_constants.py
autonomous: true
user_setup: []

must_haves:
  truths:
    - "Kalman state transition is physically consistent"
    - "Medical comments match klinical SI factors"
  artifacts:
    - "diabetic/dsp/kalman.py uses damped velocity increment"
    - "diabetic/medical_constants.py contains corrected comments"
---

# Plan 0.5.2: Signal Processing & Physical Math

<objective>
Refine the signal processing layer and mathematical constants to ensure high-fidelity tracking during data gaps and clinical transparency [H3, M1, M2].
</objective>

<context>
Load for context:
- diabetic/dsp/kalman.py
- diabetic/dsp/metabolic_math.py
- diabetic/medical_constants.py
</context>

<tasks>

<task type="auto">
  <name>Correct Kalman F-Matrix [H3]</name>
  <files>diabetic/dsp/kalman.py</files>
  <action>
    Update `_update_matrices` to apply `damping` to the velocity increment from acceleration.
    `F[1,2]` should be `dt * damping` (or the appropriate damped discrete-time transition).
    AVOID: Leaving the velocity increment undamped, which leads to "acceleration overshoot" during outages.
  </action>
  <verify>Compare velocity decay during a 30-min data gap before and after the fix.</verify>
  <done>Velocity correctly tapers towards zero during data loss.</done>
</task>

<task type="auto">
  <name>Cleanup Medical Constants & Kinematics [M1, M2]</name>
  <files>
    - diabetic/medical_constants.py
    - diabetic/dsp/metabolic_math.py
  </files>
  <action>
    1. Correct the `mg/dL` comments in `medical_constants.py`:
       - `HYPER_CRITICAL (16.0)` -> `~288 mg/dL`
       - `FAINT_GLUCOSE (22.0)` -> `~396 mg/dL`
    2. Deprecate or remove the no-op logic in `MetabolicMath.extract_kinematics`. Use the Kalman-smoothed values directly in the coordinator if possible.
    AVOID: Maintaining redundant "extraction" logic that simply re-reads existing fields.
  </action>
  <verify>Grep check for updated comments; ensure coordinator still runs without `extract_kinematics` overhead.</verify>
  <done>Clinical documentation is accurate; codebase is free of no-op mathematical calls.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Kalman Filter state transition `F` is physically consistent.
- [ ] Medical constants comments are correct.
- [ ] Redundant `extract_kinematics` logic is removed.
</verification>

<success_criteria>
- [ ] No "kinematic explosion" during 30-minute sensor gaps.
- [ ] Codebase aligns with clinical SI standards.
</success_criteria>
