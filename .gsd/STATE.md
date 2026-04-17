## Current Position
- **Phase**: 0 - Stability Hardening (Metabolic Remediation)
- **Task**: Addressing critical resource leaks and systemic failures identified in the v14 audit.
- **Status**: Paused at 2026-04-17 15:28 (Hanoi Time)

## Last Session Summary
- **Vision Maturation**: Fully detailed the **Telegram Web App (TWA)** multi-tenant roadmap.
- **Unified 5-Layer Spec**: Locked the **"Big JSON"** state architecture.
- **Deep Audit Verification**: Verified 7 critical bugs identified in the user-led audit:
    - aiohttp/httpx socket leaks in WeatherIngestor and StatelessPush.
    - Missing shutdown hooks for Nightscout/HR clients.
    - Null-pointer risk in MetabolicPalace background threads.
    - Silent weather mock defaults.
- **Baseline Integrity**: Confirmed clinical extraction (1,364 readings) and CNN inference (Glu: 9.95, HR: 82.1) are operational.

## In-Progress Work
- Implementation Plan updated with **Phase 0: Stability Partition**.
- Files modified (this turn): `ROADMAP.md`, `VISION.md`, `SPEC.md`.

## Blockers
- None.

## Context Dump
### Decisions Made
- **Shared Persistent HTTP**: Transition all ingestors to a class-level or coordinator-managed `httpx.AsyncClient` to end the file descriptor leaks.
- **Physiological Shift**: Tentative plan to move from linear IOB decay to biexponential curves for clinical parity.
- **Warning Infrastructure**: Implement proactive warnings for 'Weather Mock' and 'Neural Warmup' states.

### Approaches Tried
- **Relational Frames**: Decided to use pointers for static layers in the Big JSON to prevent database bloat.

### Current Hypothesis
- Remediation of the socket leaks and null-checks in Phase 0 will resolve the 'silent instability' observed in the background telemetry loops.

### Files of Interest
- `diabetic/ingestion/weather.py`: aiohttp leak point.
- `diabetic/utils/stateless_push.py`: httpx leak point.
- `diabetic/coordinator.py`: Shutdown and Palace logic.

## Next Steps
1. **Task 0.1**: Refactor `WeatherIngestor` and `StatelessPush` to use persistent clients.
2. **Task 0.2**: Implement graceful `aclose()` in `Coordinator.stop()`.
3. **Task 1.1**: Proceed to Multi-Tenant SQL Registry.
