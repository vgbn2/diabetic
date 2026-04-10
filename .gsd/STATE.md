## Current Position
- **Phase**: Stabilization & Precision Refinement
- **Task**: Historical Batch Extraction
- **Status**: Paused at 2026-04-10 22:07

## Last Session Summary
Solved the critical 15-day extraction gap and implemented "Crystal Precision" grid-snapping. Achieve sub-0.5% error margin for the primary 16-day metabolic report. Successfully reorganized the codebase into the "Three-Zone" architecture.

## In-Progress Work
- Refactoring `normalize_ottai_share.py` to handle 2025/2026 historical variants.
- Files modified: `calibrator.py`, `orchestrator.py`, `plot_glucose.py`.
- Tests status: Main report passing 100%. Historical batch failing due to normalization layout shifts.

## Blockers
- **Share Normalization:** June 2025 reports have a different chart height than 2026 reports, causing the fixed-height slicer to fail.

## Context Dump
- **Decisions Made**: 
    - Moved from visual labels to vector-grid snapping for calibration (4.05px offset found).
    - Adopted a 421px slicer height for 2026 Share reports.
- **Approaches Tried**:
    - Keyword-based header detection (Failed for June 2025 due to language variations).
    - Fixed-height geometry splitting (Partially successful for 2026, fails for 2025).
- **Current Hypothesis**: 
    - The June 2025 report uses a "Short Chart" format (~380px vs 421px).

## Next Steps
1. Implement a **"Flexible Geometry Slicer"** in `normalize_ottai_share.py` using horizontal line detection to find chart boundaries instead of fixed heights.
2. Complete the extraction for June 2025 and Feb 2026 historical periods.
3. Establish the unified long-term metabolic baseline (2025-2026).
