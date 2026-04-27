---
phase: 0.5
plan: 2
wave: 1
depends_on: []
files_modified: ["diabetic/ml_engine/metabolic_dataset.py", "diabetic/ml_engine/train.py", "diabetic/ingestion/mongo.py"]
autonomous: true
---

# Plan 0.5.2: Data & Training Logic Hardening

<objective>
Remediate numerical unit mismatches, fix temporal data leakage in training, and repair a critical import error in the MongoDB ingestor.

Purpose: Ensure the CNN is trained on accurate units without future-knowledge leakage.
Output: Patched dataset.py, train.py, and mongo.py.
</objective>

<context>
Load for context:
- diabetic/ml_engine/metabolic_dataset.py
- diabetic/ml_engine/train.py
- diabetic/ingestion/mongo.py
</context>

<tasks>

<task type="auto">
  <name>Normalize Velocity Units</name>
  <files>diabetic/ml_engine/metabolic_dataset.py</files>
  <action>
    Update the velocity calculation in '_preprocess' to divide by 'dt'. Current logic computes per-5min delta, while the multi-task targets expect per-minute velocity.
    Also, update the hardcoded year '2024' to 'datetime.now().year'.
  </action>
  <verify>python -c "from diabetic.ml_engine.metabolic_dataset import MetabolicDataset; ds=MetabolicDataset('storage/data/processed/mar23-apr07.csv'); print(ds[0][0][1, -1])"</verify>
  <done>Velocity units reflect mmol/L per minute.</done>
</task>

<task type="auto">
  <name>Repair MongoDB & Training Leakage</name>
  <files>diabetic/ingestion/mongo.py, diabetic/ml_engine/train.py</files>
  <action>
    1. In mongo.py, fix line 1: change 'matplotlib.path.Path' to 'pathlib.Path'.
    2. In train.py, replace 'random_split' with manual sequential slicing (Subset) to preserve temporal order.
  </action>
  <verify>grep "Subset" diabetic/ml_engine/train.py</verify>
  <done>Mongo imports are safe; training is temporally valid.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] 'mongo.py' no longer imports matplotlib for paths.
- [ ] 'train.py' uses a sequential split (no future leakage).
- [ ] 'metabolic_dataset.py' produces per-minute velocity values.
</verification>

<success_criteria>
- [ ] Data integrity restored
- [ ] Training logic validated
</success_criteria>
