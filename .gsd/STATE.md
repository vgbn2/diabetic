## Current Position
- **Phase**: Phase 3 (Metabolic Data Recovery & Pipeline Stabilization)
- **Task**: Refining High-Resolution Glucose Extraction (Value Smearing & Gaps)
- **Status**: Active (resumed 2026-04-12 14:46)

## Last Session Summary
Resolved critical blockers in Nightscout integration and historical data extraction.
1.  **Nightscout Auth**: Switched to Query Token (?token=...) authentication, successfully pulling real-time glucose (6.88 mmol/L).
2.  **Historical Extraction**: Implemented Geometric Grid-Snapping, recovering 1,791 rows from Feb/Mar-Apr 2026.
3.  **Bug Identification**: Discovered 'Value Smearing' in the extraction engine—glucose values are repeating (e.g., 8.6065) instead of following the raw PDF trace.

## In-Progress Work
- Refinement of `vector_engine.py` to prevent grid-snapping interference.
- Files modified: `diabetic/ingestion/nightscout.py`, `diabetic/config.py`, `diabetic/ingestion/offline/parsers/high_res/calibrator.py`.
- Tests status: Extraction runs, but data quality is not yet 'clinical-grade'.

## Blockers
- **Data Smearing**: The vector engine is picking up horizontal grid lines or background noise as glucose values, leading to constant segments.

## Context Dump
### Decisions Made
- **Auth Strategy**: Universal Query Token is the most robust for this specific Nightscout instance.
- **Geometric Fallback**: OCR is strictly a fallback for axis labels; geometric lines determine the time-grid.

### Current Hypothesis
The `vector_engine` is "losing the scent" of the trace when pixels overlap with the chart grid. Applying a morphological grid-removal mask should isolate the glucose signal.

### Files of Interest
- `diabetic/ingestion/offline/parsers/high_res/vector_engine.py`: Core logic for trace extraction.
- `diabetic/ingestion/offline/parsers/high_res/calibrator.py`: Geometric axis mapping.
- `storage/data/processed/feb12-feb27-2026.csv`: Result of the latest (smudged) extraction.

## Next Steps
1.  Apply grid-line subtraction to the high-res binary image in `vector_engine.py`.
2.  Implement Akima Spline interpolation for gap filling.
3.  Re-run batch extraction and verify standard deviation of results.
