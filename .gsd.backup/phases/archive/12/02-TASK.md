# Phase 12.2 Execution: Ghost Hunter

- `[x]` Implement Strict Area Filtering in `orchestrator.py`
    - Filter words/lines/curves to visible segment before shifting.
    - Inclusive `min_y` calculation (words + curves + lines).
- `[x]` Dynamic Overhang Correction
    - Clamp `min_floor` to `page.height`.
- `[/]` Batch Verification
    - Re-run `extract_historical.py`.
    - Confirm yield returns to >70% per day.
