import asyncio
import logging
import sys
import os
import atexit
import psutil
from datetime import datetime, timedelta, timezone
from diabetic.config import config
from diabetic.coordinator import Coordinator
from diabetic.registry import GlucoseReading
from diabetic.ingestion.mongo import MongoDBClient
from diabetic.utils.audit_logger import AuditLogger
from diabetic.utils.db import db_manager

# Core orchestration logic relocated to diabetic/main.py

logger = logging.getLogger("Bio-Quant.Main")

# =============================================================================
# 🧪 [METABOLIC SIMULATION]
# =Focus: Synthetic Stress Scenarios and Trajectory Validation
# =============================================================================

async def run_simulation(scenario: str):
    """
    Runs a metabolic simulation scenario.
    Scenarios: 'crash', 'faint', 'simulation' (stress)
    """
    coordinator = await Coordinator.create()
    logger.info(f"{'='*60}")
    logger.info(f"  SYSTEM RUNTIME: BIO-QUANT (MODE: SIMULATION - {scenario.upper()})  ")
    logger.info(f"{'='*60}")

    # Simulation data generation
    readings = []
    start_time = datetime.now(timezone.utc)
    
    if scenario == "crash":
        # Rapid drop from normal to hypoglycemia
        logger.info("SIMULATION: Initiating Rapid Hypoglycemic Crash...")
        for i in range(10):
            val_mmol = 6.1 - (i * 0.5) 
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="DoubleDown"))
    elif scenario == "faint":
        # High hyperglycemia with suspected faint risk factors (Rapid climb)
        logger.info("SIMULATION: Initiating Hyperglycemic Faint Risk (High + Rapid Rise)...")
        for i in range(10):
            val_mmol = 15.0 + (i * 0.8) # starting high and rising fast
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="FortyFiveUp"))
    else:
        # 'simulation' or 'normal' stress test
        logger.info("SIMULATION: Normal Metabolic Stress Test...")
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
        logger.info("[ADMIN] Initiating 15-day sensor period export...")
        await audit.log_admin_action("EXPORT_START", {"scope": "all_sensor_periods"})
        await mongo.export_sensor_periods()
        logger.info("[ADMIN] Export complete. files saved to storage/exports/")
        await audit.log_admin_action("EXPORT_COMPLETE", {"scope": "all_sensor_periods"})
        
    elif cmd == "cleanup":
        logger.info(f"[ADMIN] Enforcing {config.RETENTION_DAYS}-day retention policy cleanup...")
        await audit.log_admin_action("CLEANUP_START", {"retention_days": config.RETENTION_DAYS})
        await mongo.run_retention_cleanup(days=config.RETENTION_DAYS)
        logger.info("[ADMIN] Cleanup complete.")
        await audit.log_admin_action("CLEANUP_COMPLETE", {"retention_days": config.RETENTION_DAYS})

# =============================================================================
# 🚀 [SERVICE ORCHESTRATION]
# =Focus: CLI Argument Parsing and Live/Offline Mode Bootstrapping, change it to telegram command
# =============================================================================
async def _run_command_loop():
    while True:
        try:
            if len(sys.argv) > 1:
                cmd = sys.argv[1]
                if cmd in ["crash", "faint", "simulation", "normal"]:
                    scenario = cmd
                    await run_simulation(scenario)
                    break
                elif cmd == "live":
                    from diabetic.ml_engine.scheduler import MetabolicScheduler
                    coordinator = await Coordinator.create()
                    
                    # Start Background Training Scheduler
                    scheduler = MetabolicScheduler()
                    scheduler_task = asyncio.create_task(scheduler.run_forever())
                    coordinator._scheduler_task = scheduler_task
                    
                    await coordinator.start_live_mode()
                elif cmd in ["export", "cleanup"]:
                    await handle_admin_commands(cmd)
                    break
                elif cmd == "health":
                    import json
                    from diabetic.utils.health import get_system_health
                    snapshot = await get_system_health()
                    print(json.dumps(snapshot, indent=2))
                    break
                else:
                    logger.error(f"Unknown command: {cmd}")
                    logger.error("Usage: python -m diabetic.main [crash|faint|simulation|live|export|cleanup|health|tui]")
                    break
            else:
                # Default to regular simulation
                await run_simulation("simulation")
                break
        except KeyboardInterrupt:
            raise
        except ValueError as e:
            logging.error(f"FATAL CONFIGURATION ERROR: {e}")
            logging.error("Check your .env file or Heroku Config Vars. System exiting.")
            sys.exit(1)
        except Exception as e:
            logging.error(f"FATAL SYSTEM CRASH: {e}. Attempting automated recovery in 30s...")
            await asyncio.sleep(30) # Cool-down for recoverable network or transient errors

async def main():
    # 0. Global Hygiene & Bootstrapping (Wave 1/3)
    logging.basicConfig(
        level=config.LOG_LEVEL,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    # Structured CLI/TUI surface — handled before the service singleton lock and
    # strict boot validation so read-only commands (settings show, status) work
    # without full env, and so the `live` it launches doesn't self-conflict on the lock.
    if len(sys.argv) > 1 and sys.argv[1] == "tui":
        from diabetic.cli.tui.engine import run as run_tui
        await run_tui()
        return

    # Process Isolation (Singleton Check)
    LOCK_FILE = ".bot.lock"
    
    def cleanup_lock():
        if os.path.exists(LOCK_FILE):
            try:
                os.remove(LOCK_FILE)
            except OSError:
                pass

    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            
            # Check if process is still running
            if psutil.pid_exists(old_pid):
                logging.fatal(f"CONFLICT: Another instance of Bio-Quant is already running (PID: {old_pid}). Exiting to prevent Split-Brain.")
                sys.exit(1)
            else:
                logging.warning(f"Found stale lock file for PID {old_pid}. Cleaning up.")
        except (ValueError, OSError):
            logging.warning("Found corrupted lock file. Cleaning up.")
            
    try:
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        atexit.register(cleanup_lock)
    except OSError as e:
        logging.error(f"Failed to create lock file: {e}")

    config.validate_config()
    await db_manager.ensure_indices()
    try:
        await _run_command_loop()
    except KeyboardInterrupt:
        logger.info("Interrupted.")
    finally:
        # Retrieve singleton and shut down cleanly
        coordinator = Coordinator._instance
        if coordinator:
            await coordinator.shutdown()
        cleanup_lock()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
