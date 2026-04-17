## Current Position
- **Phase**: 20 - Neural-First Execution (Transitioning to TWA Vision)
- **Task**: Finalizing Vision and Implementation Plan for Phase 1.
- **Status**: Paused at 2026-04-17 15:04 (Hanoi Time)

## Last Session Summary
- **Infrastructure Hardening**: Committed Tier 1 stability patches (Neural Security, Boot Integrity, Persistent Clients).
- **Vision Pivot**: Re-calibrated the project as a multi-tenant **Telegram Web App (TWA)**.
- **Data Architecture**: Defined the **Unified 5-Layer "Big JSON"** State Frame for CNN consistency.
- **Medical Depth**: Re-integrated forgotten Layer 2/3 traits (Hydration, Bio-Cycles, Sick Mode, HRV).
- **Phase 1 Planning**: mapped the SQL Vessel Registry and Data Factory synthesizer.

## In-Progress Work
- Ready for Phase 1 (Bio-Quant Edition): Database Migration.
- Files modified: `SPEC.md`, `ROADMAP.md`, `VISION.md`.
- Tests status: ✅ Infrastructure baseline verified.

## Blockers
- None.

## Context Dump
### Decisions Made
- **TWA Host**: Use FastAPI to serve both the bot webhooks and the TWA dashboard.
- **Relational Frames**: "Big JSON" will store references to static layers (Vessel/Environment) to manage density.
- **Alpha-Gating**: Alerts only trigger on 30m CNN prediction with $P > \alpha$.
- **Binary RLHF**: 30m post-alert feedback loop for dynamic sensitivity calibration.

### Approaches Tried
- **CLI-Only**: Deprecated in favor of the TWA vision for better user agency.

### Current Hypothesis
- A unified "Big JSON" Audit Frame will bridge the gap between historical training data and live sensor results, significantly reducing neural drift.

### Files of Interest
- `VISION.md`: The "semantic soul" of the new TWA architecture.
- `SPEC.md`: Technical constraints for the 30m feedback loop.
- `diabetic/medical_constants.py`: Source of clinical truth for the 5 layers.

## Next Steps
1. **Task 1.1**: Implement the `VesselRegistry` (SQL multi-tenant profile storage).
2. **Task 1.2**: Build the `StateSynthesizer` (The Big JSON Data Factory).
3. **Phase 2**: Launch the FastAPI TWA backend.
