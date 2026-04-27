---
phase: 11
plan: 1
wave: 1
depends_on: []
files_modified: ["requirements.txt", "entities.json", "diabetic/ml_engine/oracle.py"]
autonomous: true
---

# Plan 11.1: Git Hygiene & Foundations

<objective>
Synchronize the repository and prepare the clinical memory core for Phase 11.
</objective>

<context>
- .gsd/SPEC.md
- requirements.txt
- entities.json
</context>

<tasks>

<task type="auto">
  <name>Resolve Git Divergence</name>
  <files>diabetic/ml_engine/oracle.py</files>
  <action>
    Run `git pull --rebase`.
    Move the incoming `diabetic/ml_engine/oracle.py` (added in remote) to the current local structure.
    Verify that the project structure remains clean (no legacy folders).
  </action>
  <verify>git status</verify>
  <done>Working tree is clean and oracle.py is integrated.</done>
</task>

<task type="auto">
  <name>Standardize Clinical Memory</name>
  <files>entities.json, requirements.txt</files>
  <action>
    Overwrite `entities.json` with clinical entities: Glucose, Insulin, Bolus, Basal, HRV, BPM, Faint, Dizzy.
    Update `requirements.txt` to ensure `chromadb>=0.6.0` is locked.
  </action>
  <verify>cat entities.json</verify>
  <done>Entities are clinical-pure.</done>
</task>

<task type="auto">
  <name>Trigger Re-indexing</name>
  <files>.</files>
  <action>
    Execute `mempalace mine ./` to refresh the semantic memory with the new taxonomy.
  </action>
  <verify>mempalace status (if available) or checking for .mempalace folder updates</verify>
  <done>Project re-indexed.</done>
</task>

</tasks>

<verification>
- [ ] git pull --rebase completed without unresolved conflicts.
- [ ] entities.json matches the clinical spec.
- [ ] mempalace index refreshed.
</verification>
