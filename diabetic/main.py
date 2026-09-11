import asyncio
import logging
import os
import sys
import threading
import atexit
import psutil
from datetime import datetime, timedelta, timezone
from diabetic.config import config
from diabetic.coordinator import Coordinator
from diabetic.registry import GlucoseReading
from diabetic.ingestion.mongo import MongoDBClient
from diabetic.utils.audit_logger import AuditLogger
from diabetic.utils.db import db_manager

logger = logging.getLogger("Bio-Quant.Main")


def _start_twa_thread(coordinator, target):
    """Starts the TWA API server thread with an async error propagation future."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    coordinator._twa_failure = future

    def _thread_target():
        try:
            target()
            if not future.done():
                loop.call_soon_threadsafe(
                    future.set_exception,
                    RuntimeError("TWA API server stopped unexpectedly"),
                )
        except Exception as exc:
            if not future.done():
                loop.call_soon_threadsafe(future.set_exception, exc)

    thread = threading.Thread(target=_thread_target, daemon=True)
    thread.start()
    coordinator._twa_thread = thread
    return thread


async def _run_live_with_twa_supervision(coordinator):
    """Supervises the live monitoring loop and background TWA thread concurrently."""
    live_task = asyncio.create_task(coordinator.start_live_mode())
    twa_future = coordinator._twa_failure

    try:
        done, pending = await asyncio.wait(
            [live_task, twa_future],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for task in (live_task, twa_future):
            if not task.done():
                task.cancel()
        await asyncio.gather(live_task, twa_future, return_exceptions=True)

    for task in done:
        if task.cancelled():
            raise asyncio.CancelledError()
        exc = task.exception()
        if exc is not None:
            raise exc

# =============================================================================
# 🧪 [METABOLIC SIMULATION]
# =Focus: Synthetic Stress Scenarios and Trajectory Validation
# =============================================================================

async def run_simulation(scenario: str):
    """
    Runs a metabolic simulation scenario.
    Scenarios: 'crash', 'faint', 'simulation' (stress)
    """
    coordinator = await Coordinator.create(allow_synthetic=True)
    logger.info(f"{'='*60}")
    logger.info(f"  SYSTEM RUNTIME: BIO-QUANT (MODE: SIMULATION - {scenario.upper()})  ")
    logger.info(f"{'='*60}")

    # Simulation data generation
    readings = []
    start_time = datetime.now(timezone.utc)
    
    if scenario == "crash":
        # Rapid drop from normal to hypoglycemia
        logger.info("SIMULATION: Initiating Rapid Hypoglycemic Crash...")
        for i in range(35):
            val_mmol = max(2.5, 8.5 - (i * 0.18))
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="DoubleDown"))
    elif scenario == "faint":
        # High hyperglycemia with suspected faint risk factors (Rapid climb)
        logger.info("SIMULATION: Initiating Hyperglycemic Faint Risk (High + Rapid Rise)...")
        for i in range(35):
            val_mmol = min(25.0, 8.0 + (i * 0.46))
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="FortyFiveUp"))
    else:
        # 'simulation' or 'normal' stress test
        logger.info("SIMULATION: Normal Metabolic Stress Test...")
        for i in range(35):
            val_mmol = 8.0 + (i * 0.05)
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="Flat"))

    for r in readings:
        await coordinator._process_reading(r)
        await asyncio.sleep(0.05) # Speed up simulation

async def handle_admin_commands(cmd: str) -> int:
# =============================================================================
# 🛠️ [ADMINISTRATIVE OVERRIDES]
# =Focus: Secure CLI Data Management, Exports, and Retention Policy
# =============================================================================
    """
    Handles secure administrative and data management commands.
    Task III Implementation.
    """
    if cmd == "export":
        from diabetic.utils.audit_logger import AuditLogger
        from diabetic.ingestion.mongo import MongoDBClient
        audit = AuditLogger()
        mongo = MongoDBClient()
        logger.info("[ADMIN] Initiating 15-day sensor period export...")
        await audit.log_admin_action("EXPORT_START", {"scope": "all_sensor_periods"})
        await mongo.export_sensor_periods()
        logger.info("[ADMIN] Export complete. files saved to storage/exports/")
        await audit.log_admin_action("EXPORT_COMPLETE", {"scope": "all_sensor_periods"})
        return 0

    elif cmd == "cleanup":
        from diabetic.operations.retention import execute_retention_cleanup
        logger.info(f"[ADMIN] Enforcing {config.RETENTION_DAYS}-day retention policy cleanup...")
        outcome = await execute_retention_cleanup(config.RETENTION_DAYS)
        if outcome.successful:
            logger.info("[ADMIN] Cleanup complete.")
            return 0
        logger.error("[ADMIN] Cleanup failed or incomplete: %s", outcome.state)
        return 1
    return 0

# =============================================================================
# 🚀 [SERVICE ORCHESTRATION]
# =Focus: CLI Argument Parsing and Live/Offline Mode Bootstrapping, change it to telegram command
# =============================================================================
async def _run_command_loop():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd in ["crash", "faint", "simulation", "normal"]:
            scenario = cmd
            await run_simulation(scenario)
        elif cmd == "live":
            from diabetic.ml_engine.scheduler import MetabolicScheduler
            from diabetic.telegram_bot.twa_api import start_api

            coordinator = await Coordinator.create(allow_synthetic=False)
            await coordinator.begin_start()

            _start_twa_thread(coordinator, lambda: start_api(coordinator))

            if config.AUTO_TRAIN_ENABLED:
                scheduler = MetabolicScheduler()
                scheduler_task = asyncio.create_task(scheduler.run_forever())
                coordinator._scheduler_task = scheduler_task
            else:
                logger.info("Automated model training is disabled.")

            try:
                await _run_live_with_twa_supervision(coordinator)
            except Exception:
                if hasattr(coordinator, "mark_failed"):
                    await coordinator.mark_failed()
                raise
        elif cmd in ["export", "cleanup"]:
            await handle_admin_commands(cmd)
        elif cmd == "health":
            import json
            from diabetic.utils.health import get_system_health
            snapshot = await get_system_health()
            print(json.dumps(snapshot, indent=2))
        else:
            logger.error(f"Unknown command: {cmd}")
            logger.error("Usage: python -m diabetic.main [crash|faint|simulation|normal|live|export|cleanup|health|tui]")
    else:
        # Default to regular simulation
        await run_simulation("simulation")

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
            current_pid = os.getpid()
            if old_pid != current_pid and psutil.pid_exists(old_pid):
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
