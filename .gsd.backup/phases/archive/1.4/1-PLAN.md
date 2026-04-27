---
phase: 1.4
plan: 1
wave: 1
---

# Plan 1.4.1: Strict Coordinate Repair & Scale Calibration

## Objective
Repair the parser's extraction logic by implementing strict bounding-box filtering and a multi-layer scale detection fallback. This will eliminate duplicated data and ensure glucose curves are correctly captured even in sparse "Normal" reports.

## Context
- .gsd/SPEC.md
- .gsd/phases/1.4/RESEARCH.md
- diabetic/ingestion/offline/high_res_parser.py

## Tasks

<task type="auto">
  <name>Implement Strict BBox Extraction</name>
  <files>diabetic/ingestion/offline/high_res_parser.py</files>
  <action>
    Update `_process_page` to use `self.page = self.page.within_bbox(self.page.cropbox)` immediately after initialization. 
    - Remove the manual `y_start <= c_top < y_end` filter from the curves loop as it will be redundant.
    - Update `_get_daily_rows` to use local coordinates relative to the cropped page.
  </action>
  <verify>python -c "import pdfplumber; p=pdfplumber.open('data/test/ottai_data/OttaiShare_Report_23Mar-7Apr2026_normalized.pdf').pages[1]; print(p.within_bbox(p.cropbox).extract_words()[:2])"</verify>
  <done>PDF objects in normalized pages are extracted with local (0-842) coordinates instead of global (-7000) coordinates.</done>
</task>

<task type="auto">
  <name>Global Scale Scanner Fallback</name>
  <files>diabetic/ingestion/offline/high_res_parser.py</files>
  <action>
    Enhance the `y_scale` detection logic.
    - If a chart row has only 0 or 1 labels, perform a `page.extract_words()` on the ENTIRE page to find '10' or '30' labels.
    - Calculate `pts_per_mmol` using these global labels if they share the same X-margin as the chart.
  </action>
  <verify>Run parser on Ottai_Report_07-04-2026_9954.pdf</verify>
  <done>Normal_Report.csv contains non-zero glucose values mapped to the Blue curves.</done>
</task>

<task type="auto">
  <name>Verify and Replot</name>
  <files>storage/data/processed/*.csv</files>
  <action>
    - Re-run the batch extraction on all 4 reports.
    - Check for duplicates (should be 0 because of within_bbox).
    - Regenerate plots.
  </action>
  <verify>python -c "import pandas as pd; print(pd.read_csv('storage/data/processed/Share_Mar_Apr_2026.csv').duplicated().sum())"</verify>
  <done>All CSVs have 0 duplicate rows and realistic glucose curves (4.0-25.0 mmol/L).</done>
</task>

## Success Criteria
- [ ] `Normal_Report.csv` has valid glucose data points.
- [ ] `Share` CSVs have 0 duplicates without manual `drop_duplicates()` hacking.
- [ ] Final plots show aligned curves and markers.
