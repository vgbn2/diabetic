---
phase: 12
plan: 3
wave: 1
depends_on: ["12.2"]
files_modified: ["diabetic/ingestion/offline/parsers/high_res/orchestrator.py"]
autonomous: true

must_haves:
  truths:
    - "Internal days on a page respect the next day's header boundary, preventing label confusion."
    - "Only the last day on a page uses the aggressive 400px overhang floor."
---

# Plan 12.3: Overhang Precision

<objective>
Fix the 'Top Day' yield failure on multi-day pages by preventing vertical window overlap. Ensure each day only sees its own calibration labels.
</objective>

<tasks>

<task type="auto">
  <name>Refine compute_y_end Logic</name>
  <files>diabetic/ingestion/offline/parsers/high_res/orchestrator.py</files>
  <action>
    Modify `_compute_y_end` to differentiate between internal and trailing days.
    - If a next row exists: `y_end = min(next_y + 15, page.height)`.
    - If no next row (last day): use the 400px overhang floor logic.
  </action>
  <verify>python -c "import diabetic.ingestion.offline.parsers.high_res.orchestrator"</verify>
</task>

<task type="auto">
  <name>Batch Verification</name>
  <files>storage/data/processed/mar23-apr07-2026.csv</files>
  <action>Re-run extraction and check yield for 03-23, 03-24 (overlapping days).</action>
</task>

</tasks>
