---
phase: 15
plan: 1
wave: 1
depends_on: []
files_modified:
  - diabetic/ml_engine/inference.py
autonomous: true
user_setup: []

must_haves:
  truths:
    - "MetabolicInferenceRunner accepts List[MetabolicSnapshot]"
    - "Snapshot-to-DataFrame conversion preserves temporal alignment"
  artifacts:
    - "diabetic/ml_engine/inference.py implementation of run_inference_on_snapshots"
---

# Plan 15.1: Inference Snapshot Bridge

<objective>
Refactor the inference engine to accept live data snapshots from the Coordinator.

Purpose: Bridges the gap between live 'MetabolicSnapshot' objects and the 'DataFrame' expected by the CNN.
Output: Integrated snapshot-to-tensor conversion method.
</objective>

<context>
- diabetic/ml_engine/inference.py
- diabetic/registry.py
</context>

<tasks>

<task type="auto">
  <name>Implement Snapshot Bridge</name>
  <files>
    - diabetic/ml_engine/inference.py
  </files>
  <action>
    Implement 'run_inference_on_snapshots(self, snapshots: List[MetabolicSnapshot])'.
    Convert the list of objects into a 30-row DataFrame with columns ['glucose', 'heart_rate'].
    AVOID: Re-synthesizing HR if it already exists in the snapshot.
  </action>
  <verify>python -c "from diabetic.ml_engine.inference import MetabolicInferenceRunner; print('Snapshot Bridge Ready')"</verify>
  <done>Method exists and correctly formats tensors from objects.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Passing a list of 30 mock snapshots to the runner returns the [Glucose, HR] dict without errors.
</verification>

<success_criteria>
- [ ] All tasks verified
</success_criteria>
