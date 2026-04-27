---
phase: 17
plan: 2
wave: 1
depends_on: []
files_modified: ["diabetic/utils/scaling_engine.py", "diabetic/config.py", "diabetic/ml_engine/inference.py"]
autonomous: true
---

# Plan 17.2: Scaling Engine & PII Lockdown

<objective>
Synchronize training/inference scaling and purge PII from source code.
Purpose: Ensure medical prediction accuracy and security compliance.
Output: Centralized `ScalingEngine` utility and sterile `config.py`.
</objective>

<context>
- diabetic/ml_engine/metabolic_dataset.py
- diabetic/ml_engine/inference.py
- diabetic/config.py
</context>

<tasks>

<task type="auto">
  <name>Implement Centralized Scaling Engine</name>
  <files>diabetic/utils/scaling_engine.py</files>
  <action>
    Create a shared `ScalingEngine` that maps traits exactly as `MetabolicDataset` does:
    - Weight / 150.0
    - Height / 250.0
    - Year Delta / 50.0
    - Ethnicity/Type discrete mappings.
  </action>
  <verify>Compare output with `metabolic_dataset.py` for same input.</verify>
  <done>Ground truth scaling engine implemented.</done>
</task>

<task type="auto">
  <name>Purge PII from config.py</name>
  <files>diabetic/config.py</files>
  <action>
    Remove hardcoded defaults for Fructosamin, Microalbuminuria, Ethnicity, Nationality, Religion.
    Set them as required environment variables or `None` with `Field(..., validation_alias)`.
  </action>
  <verify>Try starting with empty .env; it should fail on validation.</verify>
  <done>Source code sterile of Clinical PII.</done>
</task>

<task type="auto">
  <name>Refactor Inference to use Scaling Engine</name>
  <files>diabetic/ml_engine/inference.py</files>
  <action>
    Replace local `_assemble_static_vector` logic with calls to `ScalingEngine`.
  </action>
  <done>Inference uses synchronized scaling.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Inference output is stable and matches training distribution.
- [ ] `.env` is the only source of truth for patient metadata.
</verification>
