---
phase: 0.7
plan: 2
wave: 1
depends_on: []
files_modified: ["diabetic/ml_engine/metabolic_dataset.py", "diabetic/ml_engine/inference.py"]
autonomous: true
must_haves:
  truths:
    - "Dataset extraction dynamic sampling matches prediction inference intervals natively"
    - "Pandas column extraction respects DB exported column names for glucose"
    - "Inference runner handles standard Index or DatetimeIndex identically without crashes"
  artifacts: []
---

# Plan 0.7.2: Dataset & Neural Integrity

<objective>
Resolve structural data mismatches found in v18 Audit causing silent model degradation and potential crashes during inference (C3, H3, H9, M6).

Purpose: Synchronize inference and training tensor shapes/frequencies and ensure bulletproof column parsing. 
Output: Structurally sound CNN data preparation paths.
</objective>

<context>
Load for context:
- diabetic/ml_engine/metabolic_dataset.py
- diabetic/ml_engine/inference.py
</context>

<tasks>

<task type="auto">
  <name>Fix C3, H9 & M6: MetabolicDataset Resampling & Columns</name>
  <files>diabetic/ml_engine/metabolic_dataset.py</files>
  <action>
    Fix C3: Change the hardcoded `.resample('5min')` to dynamically use `config.SAMPLING_INTERVAL_MINS` (e.g. `f'{int(config.SAMPLING_INTERVAL_MINS)}min'`) or equivalent Pandas logic. Update the velocity calculation to divide by the exact interval instead of 5.0.
    Fix H9: Add defensive column detection `g_col = 'glucose_mmol_l' if 'glucose_mmol_l' in df.columns else 'glucose'` before resampling/extraction.
    Fix M6: Deprecate duplicate vector building locally; invoke `scaling_engine.assemble_static_vector(now)` to assemble the vector to prevent drift.
    AVOID: Altering the final tensor shape which must remain compatible with CNN input sizes.
  </action>
  <verify>python -c "from diabetic.ml_engine.metabolic_dataset import MetabolicDataset"</verify>
  <done>MetabolicDataset resamples correctly and safely handles disparate glucose column names</done>
</task>

<task type="auto">
  <name>Fix H3: Inference Loop Datetime Parse</name>
  <files>diabetic/ml_engine/inference.py</files>
  <action>
    Update logic in `_prepare_temporal_tensor`. Eliminate the unsafe usage of pandas iteration index `_` fallback. Safely resolve `ts_dt` by retrieving `row.get('timestamp_utc')`, then checking the index type, and falling back to `datetime.now(timezone.utc)` securely without implicit assumptions.
    AVOID: Crashing if a CSV without timestamps is provided.
  </action>
  <verify>grep "isinstance(_, datetime)" diabetic/ml_engine/inference.py -c should return 0</verify>
  <done>Index fallback handles numeric vs Datetime indices securely</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] No more 5min hardcoded resampling.
- [ ] Pandas row index _ is completely untethered from datetimes.
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
