---
phase: 0.5
plan: 4
wave: 3
depends_on: ["0.5.3"]
files_modified:
  - diabetic/ml_engine/train.py
  - diabetic/ml_engine/context_classifier.py
  - diabetic/utils/schedule.py
  - diabetic/ml_engine/predictor.py
autonomous: true
user_setup: []

must_haves:
  truths:
    - "Training is deterministic/seeded"
    - "Codebase is professional (no profanity)"
    - "XGBoost logic is either integrated or purged"
  artifacts:
    - "train.py contains random seed initialization"
    - "predictor.py is integrated into the ensemble if active"
---

# Plan 0.5.4: Hygiene & Final Purge

<objective>
Finalize the audit remediation by addressing low-priority hygiene findings and resolving the status of the "silent" XGBoost forecaster [L1, L3, L4, M7].
</objective>

<context>
Load for context:
- diabetic/ml_engine/train.py
- diabetic/ml_engine/context_classifier.py
- diabetic/utils/schedule.py
- diabetic/ml_engine/predictor.py
</context>

<tasks>

<task type="auto">
  <name>Deterministic Training & Profanity Purge [L3, L4]</name>
  <files>
    - diabetic/ml_engine/train.py
    - diabetic/ml_engine/context_classifier.py
    - diabetic/utils/schedule.py
  </files>
  <action>
    1. In `train.py`, add global seeding: `torch.manual_seed(42)`, `np.random.seed(42)`, etc.
    2. Search and replace inappropriate comments in `context_classifier.py` and `schedule.py` with professional documentation.
    AVOID: Modifying production logic during style cleanup.
  </action>
  <verify>Run `cat` or `grep` on files to confirm removal of flagged strings.</verify>
  <done>Training is reproducible; comments are professional.</done>
</task>

<task type="auto">
  <name>XGBoost Dead-Code Resolution [M7]</name>
  <files>diabetic/ml_engine/predictor.py</files>
  <action>
    - Analyze `predictor.py` (GlucoseForecaster).
    - If it provides value, instantiate it in `Coordinator` as a lightweight ensemble member.
    - If it is non-functional or redundant, delete the file to reduce maintenance surface.
    AVOID: Keeping "ghost" logic that isn't actively predicting.
  </action>
  <verify>Check for file existence or successful instantiation in `Coordinator`.</verify>
  <done>Predictive surface is 100% intentional and active.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] No profane comments remain in the repository.
- [ ] Seeding is active in the training pipeline.
- [ ] XGBoost status is resolved.
</verification>

<success_criteria>
- [ ] Repository is clean andAudit-ready for production.
- [ ] Training parity is guaranteed across runs.
</success_criteria>
