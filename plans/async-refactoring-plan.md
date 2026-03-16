# Architecture Refactoring Plan: Production-Grade Sensor Fusion

## Objective
To evolve the `MetabolicInferenceEngine` from a rigid, synchronous proof-of-concept into a robust, scalable, and asynchronous production system capable of handling multi-frequency data streams (e.g., 5-min CGM data + 20Hz UWB Radar data) without blocking, while ensuring strict data quality through Circuit Breakers.

## Critical Flaws Addressed
1. **Feature Rigidity**: Hardcoded 6D state vector in the UKF and ML models.
2. **Synchronous Bottleneck**: Blocking `while True: sleep(300)` architecture.
3. **Data Fragility**: Lack of handling for API failures, data gaps, or physiological lag.

---

## Step 1: Dynamic State Management (Pydantic)
*Goal: Decouple the state vector from the UKF and Predictor.*
- **Implementation**: Introduce `pydantic` to define a `MetabolicState` schema.
- **Action**: Create `src/schemas/state.py`.
- **Logic**: The schema will dynamically generate the state array `[G, V, A, ...]` based on active data sources. If Radar is disabled, HR/RR features are cleanly omitted from the tensor.

## Step 2: Asynchronous Event-Driven Core (`asyncio`)
*Goal: Allow high-frequency sensors to run concurrently with low-frequency APIs.*
- **Implementation**: Rewrite `main.py` and `src/coordinator.py` using Python's `asyncio`.
- **Action**:
  - Implement an `EventBus` (`asyncio.Queue`) for inter-module communication.
  - Create separate asynchronous tasks:
    - `cgm_worker`: Polls Nightscout every 5 minutes.
    - `radar_worker`: Processes UWB data at 20Hz.
    - `inference_worker`: Listens to the EventBus, runs the UKF, and triggers ML predictions when sufficient data aligns.

## Step 3: Data Quality Circuit Breakers
*Goal: Prevent "Garbage In, Garbage Out" (GIGO) during API outages or sensor compression.*
- **Implementation**: Build a `CircuitBreaker` class in `src/alerts/breaker.py`.
- **Logic**:
  - **Staleness Check**: If `datetime.now() - last_cgm_timestamp > 15 mins`, trip the breaker. Pause ML predictions and issue a "System Degraded" alert.
  - **Lag Alignment**: Apply a configurable physiological lag (e.g., 10 mins) when fusing real-time HRV with interstitial fluid CGM data.

## Execution Strategy
1. Install `pydantic`.
2. Refactor `src/data_models.py` into robust Pydantic schemas.
3. Overhaul `src/coordinator.py` to use `asyncio.Queue` and async worker methods.
4. Update `main.py` to utilize `asyncio.run()`.
5. Implement the `CircuitBreaker` logic within the `inference_worker`.
