---
phase: 2.3
plan: 1
wave: 1
---

# Plan 2.3.1: Parser Restoration (Ottai High-Res)

## Objective
Restore clinical data ingestion by fixing 3 blocking bugs in the `HighResGlucoseParser`. This will enable the system to extract valid 5-min resolution data from the daily log sections of Ottai PDF reports, preventing garbage data from the report headers.

## Context
- .gsd/docs/SPEC.md
- diabetic/ingestion/offline/high_res_parser.py
- User Bug Report: Bug 1 (Date Mapping), Bug 2 (Segment Fusion), Bug 3 (Header Overlap)

## Tasks

<task type="auto">
  <name>Fix 1: Position-Aware Date Word Lookup</name>
  <files>diabetic/ingestion/offline/high_res_parser.py</files>
  <action>
    Map the `re.finditer` character `match.start()` to the corresponding `words[]` index by calculating cumulative character lengths.
    - Scan `words[]` to find the one containing the `match.start()` offset.
    - Verify consecutive word text matches the date parts.
    - Avoid re-scanning from index 0 to prevent header collision.
  </action>
  <verify>Run the parser and check that date coordinates match the daily log section (y > 8000), not just the header (y ≈ 30).</verify>
  <done>Date headers for the daily log are correctly localized to their actual y-coordinates.</done>
</task>

<task type="auto">
  <name>Fix 2: Curve Concatenation Before Filtering</name>
  <files>diabetic/ingestion/offline/high_res_parser.py</files>
  <action>
    Group blue glucose curves within a day's cell by spatial contiguity.
    - Sort segments by x0.
    - Connect chains where `segment_N.x1` ≈ `segment_N+1.x0`.
    - Apply the `width > 20` filter to the cumulative width of the concatenated chain.
    - This captures the 3,000+ tiny segments that currently fail the filter.
  </action>
  <verify>Check CSV output count for June 2025 report; it should jump from 0 to ~2,200 points.</verify>
  <done>Daily log glucose traces are successfully extracted as continuous datasets.</done>
</task>

<task type="auto">
  <name>Fix 3: Exclude Report Header Row</name>
  <files>diabetic/ingestion/offline/high_res_parser.py</files>
  <action>
    Implement an explicit exclusion for the report header row.
    - Add a check in the `rows` processing loop: `if (y_end - y_start) > 500: continue`.
    - Alternatively, detect the specific session start/end dates from the header and skip that row.
    - This prevents the AGP percentile curves from being misidentified as glucose data.
  </action>
  <verify>Ensure the first ~2600 pts of the PDF are no longer processed as a "chart row" containing AGP curves.</verify>
  <done>The extracted data contains only daily log values, with no contamination from the AGP section.</done>
</task>

## Success Criteria
- [ ] February 2026 extraction yields approx. 419 points.
- [ ] June 2025 extraction yields approx. 2,201 points.
- [ ] Zero points extracted from the AGP header row (y < 2600).
