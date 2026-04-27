## Current Position
- **Phase**: Phase 1.1 — Multi-Tenant Data Factory
- **Task**: v20 Audit Remediations (C1-C3)
- **Status**: Active (resumed 2026-04-27 15:49)

## Last Session Summary
Successfully implemented and verified the **Data Factory Bootstrap (Plan 1.0)**:
- **Async SQL Registry**: Replaced .env config with a multi-tenant SQLAlchemy persistence layer.
- **Kinematic Forecasting**: Implemented `TacticalForecaster` for 15/30/60m glucose horizons with confidence scoring.
- **Forensic Tools**: Developed a BSON-to-JSON transformer for clinical history porting.
- **v20 Audit**: Verified all 11 findings; created high-fidelity remediation roadmap in `v20_remediation_todo.md`.

## In-Progress Work
- **Remediation Planning**: C1 (Data Loss), C2 (BasalOracle), and C3 (RLHF) are mapped.
- Files modified: `diabetic/coordinator.py`, `diabetic/registry.py`, `diabetic/utils/data_factory.py`, `diabetic/storage/*`, `scripts/utils/transform_bson_history.py`.
- Tests status: Passing (Verified SQL CRUD, Regression Math, and UI Formatting).

## Blockers
- None.

## Context Dump
### Decisions Made
- **UI Exposure**: Decision to explicitly render all horizons in Telegram to address user requests for 15m/60m visibility.
- **Feedback Engine**: Decided to build a dedicated `FeedbackEngine` logic instead of just logging button clicks to close the RLHF gap.

### Key Takeaways (v20 Audit)
- **Connectivity vs Correctness**: The dominant problem is not code quality (which is high) but wiring. `storage/` and `oracle.py` are complete but orphaned.
- **Hygiene**: Pervasive `print()` usage (40+ instances) needs migration to structured logging for cloud stability.
- **Standalone Design**: `ingestion/offline/` (PDF parsers) are disconnected by design; not a bug.

### Current Hypothesis
- The `BasalOracle` is permanently dead because it lacks an ingestion bridge; fixing this will solve the "long-term drift" accuracy problem.
- Connectivity is the dominant problem; code quality is high, but components are currently orphaned.

### Files of Interest
- `diabetic/ml_engine/metabolic_dataset.py`: Source of the C1 silent-drop bug.
- `diabetic/ml_engine/twin.py`: Physiological curves (L1/L2).
- `v20_remediation_todo.md`: The remediation roadmap.

## Next Steps
1. **Remediate C1**: Fix the non-numeric column drop in `MetabolicDataset`.
2. **Execute G1/G3 Wiring**: Connect `VesselRegistry` to `Coordinator` and authorized bot handlers.
3. **Refactor L1**: Update IOB decay to pharmacological biexponential model.
4. **Execute L5**: Migrate all `print()` statements to structured logging.
