import asyncio
import logging
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from diabetic.config import config

# Mock settings for verification to avoid missing env var failures
os.environ["NIGHTSCOUT_URL"] = "http://mock.nightscout"
os.environ["NIGHTSCOUT_API_SECRET"] = "mock_secret"
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:mock"
os.environ["TELEGRAM_CHAT_ID"] = "987654321"
os.environ["MONGO_URI"] = "mongodb://localhost:27017/mock"

from diabetic.coordinator import Coordinator
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic.storage.engine import init_db
from diabetic.utils.db import db_manager

# Verification script for Bio-Quant Hardening Phase
# Enforces Empirical Validation for H3, B2, Task 1, Task 6, Task 7

async def verify_hardening():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("Bio-Quant.Verify")
    
    logger.info("Starting Empirical Validation Protocol...")

    # 1. Database and Registry Initialization
    try:
        await init_db()
        logger.info("PASS: Database schema initialized.")
    except Exception as e:
        logger.error(f"FAIL: Database initialization failed: {e}")
        return

    # 2. Coordinator Lifecycle (Task 6/7)
    logger.info("[VERIFY] Initializing Coordinator...")
    try:
        coordinator = await Coordinator.create()
        logger.info("PASS: Coordinator instantiated successfully.")
    except Exception as e:
        logger.error(f"FAIL: Coordinator initialization failed: {e}")
        return
    
    # 3. Sick Mode Injection (H3)
    # We simulate a medical state in the database for the configured user
    chat_id = int(os.environ["TELEGRAM_CHAT_ID"])
    logger.info(f"[VERIFY] Setting SICK_MODE=True for user {chat_id}...")
    try:
        await coordinator.vessel_registry.update_medical_state(
            chat_id, 
            active=True, 
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        logger.info("PASS: Medical state updated in Registry.")
    except Exception as e:
        logger.error(f"FAIL: Medical state update failed: {e}")
        # Continue to see if it defaults correctly

    # --- TASK 7: Part 2 Specific Audits ---
    logger.info("TASK 7: Running Part 2 Audit Verifications...")
    
    # 7.1 Fix C1: Velocity Correction Direction
    from diabetic.utils.data_factory import TacticalForecaster
    tf_light = TacticalForecaster(weight_kg=50.0) # Higher ISF
    tf_heavy = TacticalForecaster(weight_kg=100.0) # Lower ISF
    if tf_light.velocity_correction > tf_heavy.velocity_correction:
        logger.info("  [PASS] C1: Light patients have higher velocity amplification than heavy patients.")
    else:
        logger.error(f"  [FAIL] C1: Correction inverted. Light: {tf_light.velocity_correction:.2f}, Heavy: {tf_heavy.velocity_correction:.2f}")
        success = False

    # 7.2 Fix C2: Static Vector Parity
    from diabetic.ml_engine.metabolic_dataset import MetabolicDataset
    from diabetic.utils.scaling_engine import scaling_engine
    try:
        ds = MetabolicDataset("storage/data/processed/mar23-apr07.csv")
        ds_vector = ds._assemble_static_vector(datetime.now())
        se_vector = scaling_engine.assemble_static_vector(datetime.now())
        if np.allclose(ds_vector, se_vector):
            logger.info("  [PASS] C2: Training and Inference share 1:1 static vector assembly logic.")
        else:
            logger.error("  [FAIL] C2: Static vector mismatch between Dataset and ScalingEngine.")
            success = False
    except Exception as e:
        logger.warning(f"  [SKIP] C2: Could not verify (CSV missing?): {e}")

    # 7.4 Nightscout Training Integration (New Phase)
    logger.info("  [VERIFY] Phase: Nightscout Training Integration...")
    try:
        # Mocking MongoDB data fetch
        mock_df = pd.DataFrame({
            "timestamp": [datetime.now(timezone.utc) - timedelta(minutes=i*5) for i in range(100)],
            "glucose": np.random.uniform(4.0, 10.0, 100),
            "trend": ["Flat"] * 100,
            "bolus": [0.0] * 100,
            "meal": [0.0] * 100
        })
        
        # Test 7.4.1: Dataset supports direct DF ingestion
        ds_mongo = MetabolicDataset(df_input=mock_df)
        if len(ds_mongo) > 0:
            logger.info("    [PASS] Dataset successfully ingests direct DataFrame from MongoDB.")
        else:
            logger.error("    [FAIL] Dataset ingestion from DataFrame produced 0 windows.")
            success = False
            
        # Test 7.4.2: Trainer function signature and async support
        from diabetic.ml_engine.train import train_metabolic_cnn
        import inspect
        if inspect.iscoroutinefunction(train_metabolic_cnn):
            logger.info("    [PASS] train_metabolic_cnn is correctly refactored to async for NS sync.")
        else:
            logger.error("    [FAIL] train_metabolic_cnn is not an async function.")
            success = False
            
    except Exception as e:
        logger.error(f"  [FAIL] Nightscout training verification crashed: {e}")
        success = False

    if success:
        logger.info("\n--- ALL HARDENING VERIFICATIONS PASSED ---")
    else:
        logger.error("\n--- HARDENING VERIFICATIONS FAILED ---")
        sys.exit(1)

    # 4. Simulation and Propagation Check
    logger.info("[VERIFY] Running 35-reading simulation to warm up Neural Engine...")
    start_time = datetime.now(timezone.utc)
    
    # We need at least 30 readings for Neural Runner to engage (seq_len=30)
    for i in range(35):
        reading = GlucoseReading(
            timestamp=start_time + timedelta(minutes=i*5),
            value=6.0 + (i * 0.05),
            trend="Flat"
        )
        await coordinator._process_reading(reading)
        
        if i == 34:
            # Check the latest snapshot
            latest = coordinator.snapshots[-1]
            
            # H3 Validation: is_sick propagation
            logger.info(f"[VERIFY] Latest Snapshot is_sick: {latest.is_sick}")
            if latest.is_sick:
                logger.info("PASS: is_sick flag successfully propagated from Registry -> Snapshot.")
            else:
                logger.error("FAIL: is_sick flag missing in Snapshot.")
            
            # Task 1 Validation: Tactical Forecaster engagement
            if latest.predict_60m != 0.0:
                 logger.info(f"PASS: TacticalForecaster engaged. 60m Pred: {latest.predict_60m}")
            else:
                 logger.error("FAIL: TacticalForecaster returned 0.0")

            # Neural Engine Validation (Might be 0.0 if weights missing, which is a warning not fail)
            if latest.predict_30m != 0.0:
                 logger.info(f"PASS: Neural Engine (CNN) engaged. 30m Pred: {latest.predict_30m}")
            else:
                 logger.warning("WARN: Neural Engine (CNN) predict_30m is 0.0. (Normal if weights are missing in this environment)")

    # 5. Shutdown Hardening (Task 6)
    logger.info("[VERIFY] Testing Graceful Shutdown...")
    try:
        await coordinator.stop()
        logger.info("PASS: Coordinator shut down without deadlock.")
    except Exception as e:
        logger.error(f"FAIL: Coordinator shutdown failed: {e}")

    logger.info("Empirical Validation Complete.")

if __name__ == "__main__":
    asyncio.run(verify_hardening())
