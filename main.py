import asyncio
import sys
from datetime import datetime, timedelta
import numpy as np
import threading
from src.coordinator import AsyncInferenceEngine
from src.data_models import GlucoseReading, BiometricReading
from src.api import start_api, shared_engine as api_engine
from src.logger import logger

async def run_simulation_stress_test(engine: AsyncInferenceEngine):
    """
    Asynchronous simulation of a complex metabolic event:
    1. Steady State.
    2. Sudden Stress (Emotional) -> HRV Drops immediately.
    3. Delayed Glucose Spike (Interstitial Lag) -> CGM rises 15m later.
    """
    logger.info("Starting Asynchronous Metabolic Stress Test...")
    
    now = datetime.now()
    
    # 1. Inject Immediate Stress Event (HRV drops from 50 to 15)
    logger.info("SIMULATION: Acute Emotional Event Detected (Immediate HRV Drop)")
    for i in range(5):
        stress_event = BiometricReading(
            timestamp=now - timedelta(seconds=(5-i)*2), 
            rmssd=15.0, 
            source="Radar_UWB"
        )
        await engine.event_bus.put(stress_event)
        await asyncio.sleep(0.1)

    # 2. Inject Lagged Glucose Response (The "Interstitial Lag Fallacy" Fix)
    # The CGM only starts showing the spike 15 minutes 'later' in its timestamp
    logger.info("SIMULATION: Injecting Lagged CGM Data (15-minute physiological offset)")
    for i in range(3):
        lagged_glucose = GlucoseReading(
            timestamp=now - timedelta(minutes=(2-i)*5), 
            sgv=110 + (i * 20),
            direction="RapidRise",
            lag_minutes=15
        )
        await engine.event_bus.put(lagged_glucose)
        await asyncio.sleep(0.5)

    logger.info("Simulation events injected. Awaiting engine processing...")
    await asyncio.sleep(2) # Give the inference worker time to process the queue

async def run_simulation_crash_test(engine: AsyncInferenceEngine):
    """Simulates a hypoglycemic crash — should trigger CRITICAL_HYPO."""
    logger.info("Starting Crash Scenario Test...")
    now = datetime.now()

    # Step 1: Inject stress (HRV drops — reduces insulin sensitivity)
    for i in range(3):
        await engine.event_bus.put(BiometricReading(
            timestamp=now - timedelta(seconds=(3-i)*2),
            rmssd=12.0,  # critically low HRV
            source="Simulation"
        ))
        await asyncio.sleep(0.1)

    # Step 2: Inject falling glucose (Aggressive crash)
    for i, sgv in enumerate([65, 52, 41, 34]):
        await engine.event_bus.put(GlucoseReading(
            timestamp=now - timedelta(minutes=(3-i)*5),
            sgv=sgv,
            direction="DoubleDown",
            lag_minutes=15
        ))
        await asyncio.sleep(0.5)

    await asyncio.sleep(2)

async def run_simulation_faint_test(engine: AsyncInferenceEngine):
    """Simulates hyperglycemic faint risk — should trigger FAINT_RISK."""
    logger.info("Starting Faint Risk Scenario Test...")
    now = datetime.now()

    # High stress
    for i in range(5):
        await engine.event_bus.put(BiometricReading(
            timestamp=now - timedelta(seconds=(5-i)*2),
            rmssd=8.0,  # extreme stress
            source="Simulation"
        ))

    # Critically high glucose
    for i, sgv in enumerate([280, 310, 340, 370]):
        await engine.event_bus.put(GlucoseReading(
            timestamp=now - timedelta(minutes=(3-i)*5),
            sgv=sgv,
            direction="SingleUp",
            lag_minutes=15
        ))
        await asyncio.sleep(0.5)

    await asyncio.sleep(2)

async def main():
    """
    Main entry point for the Async Metabolic Inference Engine.
    """
    mode = sys.argv[1] if len(sys.argv) > 1 else "simulation"
    
    print("="*60)
    print(f"  SYSTEM RUNTIME: ASYNCHRONOUS INFERENCE (MODE: {mode.upper()})  ")
    print("="*60)
    
    engine = AsyncInferenceEngine()

    # Start API Dashboard thread (Phase 4)
    import src.api as api_module
    api_module.shared_engine = engine
    api_thread = threading.Thread(target=start_api, daemon=True)
    api_thread.start()
    logger.info("API Dashboard Server started on port 5000")

    if mode == "simulation":
        # Run the simulation and cancel the worker when done
        worker_task = asyncio.create_task(engine.inference_worker())
        await run_simulation_stress_test(engine)
        worker_task.cancel()
        logger.info("Simulation Task Complete.")
    elif mode == "crash":
        worker_task = asyncio.create_task(engine.inference_worker())
        await run_simulation_crash_test(engine)
        worker_task.cancel()
        logger.info("Crash Simulation Task Complete.")
    elif mode == "faint":
        worker_task = asyncio.create_task(engine.inference_worker())
        await run_simulation_faint_test(engine)
        worker_task.cancel()
        logger.info("Faint Simulation Task Complete.")
    elif mode == "live":
        # Run all production workers (Nightscout, Radar/Wearable, Inference)
        await engine.run()
    else:
        logger.error(f"Unknown execution mode: {mode}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("System shutdown complete.")
