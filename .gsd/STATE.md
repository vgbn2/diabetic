## Current Position
- **Phase**: Phase 8: Digital Twin & Predictive Meal Modeling
- **Task**: Phase 8 Completion & Cloud Planning
- **Status**: Paused at 2026-03-25 20:06

## Last Session Summary
Finalized Phase 7 (Hardening) and completed Phase 8 (Digital Twin). The system now has a physics-based simulation engine for meals, adaptive parameter tuning (auto-adjusting sensitivity and absorption speed), and a "Regime Detector" for hormonal/circadian shifts.

## In-Progress Work
- Files modified: `diabetic/ml_engine/twin.py`, `diabetic/coordinator.py`, `diabetic/telegram_bot/handlers.py`, `diabetic/medical_constants.py`, `diabetic/registry.py`.
- Tests status: `twin.py` and `visualizer.py` standalone tests passed. Core integration verified.
- **Note**: Visualization (Plan 8.2) is deferred and moved to `charts_visualize/`.

## Blockers
None. The system is stable and passing all metabolic verification suites.

## Context Dump
### Decisions Made
- **Adaptive Seeds**: Used 15m/60m as population baselines, then implemented an `auto_tune` method to personalize `tau` and `CSF` based on real CGM peaks.
- **Regime Detector**: Implemented a multi-day moving average comparison (>15% shift) to detect high-resistance metabolic regimes (Hormonal/Luteal).
- **Visualization Deferral**: Decoupled `visualizer.py` into `charts_visualize/` to keep the local core lean until server deployment.

### Approaches Tried
- **Interactive Loops**: Successfully integrated the Telegram bot polling directly into the `Coordinator` via `asyncio` background tasks.

### Next Steps
1. **Phase 9: Lean 24/7 Deployment**: Deploy the engine to a VPS (e.g., DigitalOcean/AWS) using `pm2` for process persistence.
2. **Hormonal Manual Triggers**: Add Telegram commands (e.g., `/period_start`) to manually force regime shifts in the Digital Twin.
3. **Re-Integration of UI**: Re-enable `visualizer.py` once a persistent server is established.
