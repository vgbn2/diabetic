---
phase: 1.5
plan: 1
wave: 1..3
completed: true
---

# Phase 1.5 Summary: Modular Crystal Ingestion

## What Was Built

| Module | File | Purpose |
|--------|------|---------|
| Data Structures | `models.py` | Typed `DayCell`, `GlucoseCurve`, `EventMarker`, `ScaleAnchor`, `TemporalAnchor` |
| Crystal Calibrator | `calibrator.py` | 3-strategy Y/X scale cascade fixing timestamp collapse |
| Vector Engine | `vector_engine.py` | pdfplumber object classification + segment concatenation |
| Vision Engine | `vision_engine.py` | Lazy-loading OpenCV icon detection at 400 DPI |
| Orchestrator | `orchestrator.py` | Slim entrypoint wiring all modules |
| Gauge | `gauge_accuracy.py` | Visual projection validator with PASS/FAIL verdict |

## Metrics (Normal Report)

| Metric | Before (v1) | After (v2) |
|--------|-------------|------------|
| Rows extracted | 9 | **149** |
| Duplicate timestamps | N/A | **0** |
| Coverage (5-min slots) | ~0% | **77.4%** |
| Temporal jitter | N/A | **8.62 min** |
| Gauge verdict | — | **PASS** |

## Key Fixes

1. **Timestamp Collapse** — Fixed via `DayCell.to_records()` 0.5-min bucket dedup.
2. **Data Loss** — Fixed via `vector_engine` including `page.lines` alongside `page.curves`.
3. **System Lag** — Fixed via lazy vision rendering + 400 DPI (vs 576).
4. **Coordinate Errors** — Fixed via `_localize()` using `page.cropbox`.
