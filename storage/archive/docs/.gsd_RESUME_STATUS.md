# Resume Session - Hyperglycemia Faint Predictor

## Status
- **Phase**: Infrastructure & Simulation Verification
- **Current Task**: Confirming base engine functionality
- **Last Action**: Ran `python main.py simulation`
- **Next Step**: Verify output and address any immediate errors

## Findings
- Project structure is well-organized with `backend/src` and `scripts`.
- `main.py` contains testing scenarios: `simulation`, `crash`, `faint`.
- `coordinator.py` is the main orchestrator, but `main.py` seems to use `AsyncInferenceEngine` from `src.coordinator` while `coordinator.py` defines `Coordinator`. This implies a potential mismatch or multiple versions.
- `LIVE_SETUP_GUIDE.md` is the primary roadmap.

## Blockers
- None identified yet.
