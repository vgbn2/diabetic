import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from diabetic.config import config
from diabetic.coordinator import Coordinator
from diabetic.registry import GlucoseReading
from diabetic.ingestion.mongo import MongoDBClient
from diabetic.utils.audit_logger import AuditLogger
from diabetic.utils.db import db_manager

# Core orchestration logic relocated to diabetic/main.py

# =============================================================================
# 🧪 [METABOLIC SIMULATION]
# =Focus: Synthetic Stress Scenarios and Trajectory Validation
# =============================================================================

async def run_simulation(scenario: str):
    """
    Runs a metabolic simulation scenario.
    Scenarios: 'crash', 'faint', 'simulation' (stress)
    """
    coordinator = Coordinator()
    print(f"\n{'='*60}")
    print(f"  SYSTEM RUNTIME: BIO-QUANT (MODE: SIMULATION - {scenario.upper()})  ")
    print(f"{'='*60}\n")

    # Simulation data generation
    readings = []
    start_time = datetime.now(timezone.utc)
    
    if scenario == "crash":
        # Rapid drop from normal to hypoglycemia
        print("SIMULATION: Initiating Rapid Hypoglycemic Crash...")
        for i in range(10):
            val = 110 - (i * 10) # dropping fast (mg/dL internally for logic? No, registry says mmol/L)
            val_mmol = 6.1 - (i * 0.5) 
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="DoubleDown"))
    elif scenario == "faint":
        # High hyperglycemia with suspected faint risk factors (Rapid climb)
        print("SIMULATION: Initiating Hyperglycemic Faint Risk (High + Rapid Rise)...")
        for i in range(10):
            val_mmol = 15.0 + (i * 0.8) # starting high and rising fast
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="FortyFiveUp"))
    else:
        # 'simulation' or 'normal' stress test
        print("SIMULATION: Normal Metabolic Stress Test...")
        for i in range(10):
            val_mmol = 8.0 + (i * 0.1)
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="Flat"))

    for r in readings:
        await coordinator._process_reading(r)
        await asyncio.sleep(0.05) # Speed up simulation

async def handle_admin_commands(cmd: str):
# =============================================================================
# 🛠️ [ADMINISTRATIVE OVERRIDES]
# =Focus: Secure CLI Data Management, Exports, and Retention Policy
# =============================================================================
    """
    Handles secure administrative and data management commands.
    Task III Implementation.
    """
    audit = AuditLogger()
    mongo = MongoDBClient()
    
    if cmd == "export":
        print(f"\n[ADMIN] Initiating 15-day sensor period export...")
        await audit.log_admin_action("EXPORT_START", {"scope": "all_sensor_periods"})
        await mongo.export_sensor_periods()
        print("[ADMIN] Export complete. files saved to storage/exports/")
        await audit.log_admin_action("EXPORT_COMPLETE", {"scope": "all_sensor_periods"})
        
    elif cmd == "cleanup":
        print(f"\n[ADMIN] Enforcing 180-day retention policy cleanup...")
        await audit.log_admin_action("CLEANUP_START", {"retention_days": 180})
        await mongo.run_retention_cleanup(days=180)
        print("[ADMIN] Cleanup complete.")
        await audit.log_admin_action("CLEANUP_COMPLETE", {"retention_days": 180})

# =============================================================================
# 🚀 [SERVICE ORCHESTRATION]
# =Focus: CLI Argument Parsing and Live/Offline Mode Bootstrapping
# =============================================================================
async def main():
    # 0. Global Hygiene & Bootstrapping (Wave 1/3)
    logging.basicConfig(
        level=config.LOG_LEVEL,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    
    config.validate_config()
    await db_manager.ensure_indices()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd in ["crash", "faint", "simulation", "normal"]:
            scenario = cmd
            await run_simulation(scenario)
        elif cmd == "live":
            coordinator = Coordinator()
            await coordinator.start_live_mode()
        elif cmd in ["export", "cleanup"]:
            await handle_admin_commands(cmd)
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python -m diabetic.main [crash|faint|simulation|live|export|cleanup]")
    else:
        # Default to regular simulation
        await run_simulation("simulation")

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\nSystem stopped by user.")
            break
        except Exception as e:
            logging.error(f"FATAL SYSTEM CRASH: {e}. Attempting automated recovery in 30s...")
            import time
            time.sleep(30) # Cool-down to prevent rapid looping on fatal config errors
