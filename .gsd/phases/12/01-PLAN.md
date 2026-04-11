---
phase: 12
plan: 1
wave: 1
---

# Plan 12.1: Historical Precision Recovery

## Objective
Recover the missing ~30% of data from historical Ottai PDF reports by resolving vertical overlap cutoffs and zero-shifting negative coordinates on deep scroll segments.

## Context
- .gsd/SPEC.md
- diabetic/ingestion/offline/parsers/high_res/orchestrator.py

## Tasks

<task type="auto">
  <name>Implement Overhang Geometry and Zero-Shifting</name>
  <files>diabetic/ingestion/offline/parsers/high_res/orchestrator.py</files>
  <action>
    - In `_process_page`, update the Coordinate Origin Flattening logic. Ensure `min_y` shifting logic runs even if `min_y <= 0` (currently it only shifts if `min_y > 500`).
    - In `_process_page`, relax the `first_header_y > 50` check for orphaned curves to simply verify if there is *any* space ABOVE the first header allowing curves to continue from the previous page.
    - In `_compute_y_end`, ensure charts have a minimum extraction region height (e.g. `max(next_y, y_start + 400)`). If the next header is only 72 pixels away, we must allow the extraction region to "overhang" over the next header so we don't truncate the current chart.
  </action>
  <verify>python -c "import diabetic.ingestion.offline.parsers.high_res.orchestrator as o; print('Syntax OK')"</verify>
  <done>
    - `_process_page` negative `min_y` are properly shifted.
    - Cross-page continuation has relaxed vertical limits.
    - `_compute_y_end` enforces a larger minimum chart height.
  </done>
</task>

## Success Criteria
- [ ] Overlapping charts are extracted successfully.
- [ ] Orphan data on deep scroll pages is recovered.
