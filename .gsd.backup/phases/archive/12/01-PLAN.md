---
phase: 12
plan: 1
wave: 1
depends_on: []
files_modified: ["diabetic/ingestion/offline/parsers/high_res/orchestrator.py"]
autonomous: true

must_haves:
  truths:
    - "Negative coordinates from long-scrolls are perfectly shifted to zero"
    - "Orphaned curves above the first header on a page are successfully extracted for the previous day"
    - "Data underneath subsequent day headers is retrieved via overhang logic"
  artifacts:
    - "diabetic/ingestion/offline/parsers/high_res/orchestrator.py is updated"
---

# Plan 12.1: Historical Precision Recovery

<objective>
Recover the missing ~30% of data from historical Ottai PDF reports by resolving vertical overlap cutoffs and zero-shifting negative coordinates on deep scroll segments.

Purpose: To push the coverage from 65% to a clinical-grade 95%+ standard across unpredictable historical pdf variants.
Output: An updated `orchestrator.py` allowing "overhanging" searches and relaxed continuation boundaries.
</objective>

<context>
Load for context:
- .gsd/SPEC.md
- diabetic/ingestion/offline/parsers/high_res/orchestrator.py
</context>

<tasks>

<task type="auto">
  <name>Zero-Shift Deep Scroll Coordinates</name>
  <files>diabetic/ingestion/offline/parsers/high_res/orchestrator.py</files>
  <action>
    Modify `_process_page` Coordinate Origin Flattening logic.
    Instead of only running `if min_y > 500:`, we must ensure logic runs for negative `min_y` as well because normalized long-scrolls can have items starting at `y < 0`.
    Change to `if min_y != 0:` (or similar absolute-value check) so all words, lines, and curves shift down/up exactly to a 0 origin based on the minimum y reading.
    AVOID: Skipping coordinate normalization for negatively shifted normalized pages.
  </action>
  <verify>python -c "import diabetic.ingestion.offline.parsers.high_res.orchestrator"</verify>
  <done>Zero-shifting is active for all non-zero `min_y` scenarios.</done>
</task>

<task type="auto">
  <name>Relax Cross-Page Continuation Threshold</name>
  <files>diabetic/ingestion/offline/parsers/high_res/orchestrator.py</files>
  <action>
    In `_process_page`, find the cross-page continuation `if self._prev_date and first_header_y > 50:` block.
    Relax this logic to allow recovering orphans even if there are only 5-10 pixels above the first header. 
    Use `if self._prev_date and first_header_y > 10:` or check for intersection with the curve array directly.
    AVOID: Strict absolute pixel thresholds which break on differently normalized documents.
  </action>
  <verify>python -c "import diabetic.ingestion.offline.parsers.high_res.orchestrator"</verify>
  <done>Orphan data is recovered without being constrained by a 50px gap boundary.</done>
</task>

<task type="auto">
  <name>Implement Y-Overhang Geometry</name>
  <files>diabetic/ingestion/offline/parsers/high_res/orchestrator.py</files>
  <action>
    In `_compute_y_end`, enforce a minimum chart search window.
    Currently: `next_y = (rows[row_idx + 1]...`
    Update the minimum bounds from `y_start + 100` to `y_start + 400` so the extractor captures curves that physically "overhang" beneath the subsequent header text.
    The time-calibration step natively filters overlapping X-ranges, making this Y-overhang completely safe.
    AVOID: Truncating multi-day charts exclusively at `next_y` when `next_y` is unusually small (e.g. 72px).
  </action>
  <verify>python -c "import diabetic.ingestion.offline.parsers.high_res.orchestrator"</verify>
  <done>Vertical extraction windows extend far enough to capture all data points for a given day.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Deep scroll components shift to exactly Y_0 properly.
- [ ] No strict pixel gaps block chart continuations.
- [ ] `_compute_y_end` enforces Y-overhang.
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
