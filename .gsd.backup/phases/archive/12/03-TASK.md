# Phase 12.3 Execution: Overhang Precision

- `[/]` Implement Header-Aware `_compute_y_end` in `orchestrator.py`
    - Differentiate between internal and trailing days.
    - Set internal window to `next_y + 15`.
    - Preserve 400px floor for the LAST day on the page.
- `[ ]` Batch Verification
    - Re-run `extract_historical.py`.
    - Verify 95%+ recovery.
