import asyncio
import logging
import sys
import os
import atexit
import threading
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


def _start_twa_thread(coordinator, start_api):
    """Start TWA and project thread failures into the owning event loop."""
    loop = asyncio.get_running_loop()
    failure = loop.create_future()

    def run_api():
        try:
            start_api(coordinator)
        except BaseException as error:
            loop.call_soon_threadsafe(_set_future_exception, failure, error)
        else:
            loop.call_soon_threadsafe(
                _set_future_exception,
                failure,
                RuntimeError("TWA API server stopped unexpectedly"),
            )

    thread = threading.Thread(
        target=run_api,
        daemon=True,
        name="bio-quant-twa",
    )
    coordinator._twa_thread = thread
    coordinator._twa_failure = failure
    thread.start()
    return thread


def _set_future_exception(future: asyncio.Future, error: BaseException) -> None:
    if not future.done():
        future.set_exception(error)


async def _run_live_with_twa_supervision(coordinator) -> None:
    live_task = asyncio.create_task(coordinator.start_live_mode())
    twa_failure = coordinator._twa_failure
    try:
        done, _ = await asyncio.wait(
            {live_task, twa_failure},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if twa_failure in done:
            live_task.cancel()
            await asyncio.gather(live_task, return_exceptions=True)
            await twa_failure
        await live_task
    finally:
        if not live_task.done():
            live_task.cancel()
            await asyncio.gather(live_task, return_exceptions=True)
        if not twa_failure.done():
            twa_failure.cancel()

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
        from diabetic.operations.retention import execute_retention_cleanup

        result = await execute_retention_cleanup(
            config.RETENTION_DAYS,
            mongo=mongo,
            audit=audit,
        )
        if result.successful:
            logger.info(
                "[ADMIN] Cleanup complete: %s entries, %s treatments.",
                result.entries_deleted,
                result.treatments_deleted,
            )
            return 0
        logger.error(
            "[ADMIN] Cleanup %s during %s.",
            result.state,
            result.failed_phase or "unknown",
        )
        return 1

# =============================================================================
# 🚀 [SERVICE ORCHESTRATION]
# =Focus: CLI Argument Parsing and Live/Offline Mode Bootstrapping, change it to telegram command
# =============================================================================
async def _run_command_loop():
    """Dispatch one command attempt; process supervision owns live recovery."""
    if len(sys.argv) <= 1:
        await run_simulation("simulation")
        return 0

    cmd = sys.argv[1]
    if cmd in ["crash", "faint", "simulation", "normal"]:
        await run_simulation(cmd)
        return 0
    if cmd == "live":
        from diabetic.ml_engine.scheduler import MetabolicScheduler
        from diabetic.telegram_bot.twa_api import start_api

        coordinator = await Coordinator.create(allow_synthetic=False)
        await coordinator.begin_start()

        # TWA must share this process for COORDINATOR_REF. The daemon thread is
        # not restarted in-process; process supervision owns recovery.
        try:
            _start_twa_thread(coordinator, start_api)

            if config.AUTO_TRAIN_ENABLED:
                scheduler = MetabolicScheduler()
                coordinator._scheduler_task = asyncio.create_task(
                    scheduler.run_forever()
                )
            else:
                logger.info("Automated model training is disabled.")

            await _run_live_with_twa_supervision(coordinator)
            return 0
        except BaseException:
            twa_failure = getattr(coordinator, "_twa_failure", None)
            if twa_failure is not None and twa_failure.done():
                try:
                    twa_failure.exception()
                except asyncio.CancelledError:
                    pass
            await coordinator.mark_failed()
            raise
    if cmd in ["export", "cleanup"]:
        return await handle_admin_commands(cmd) or 0
    if cmd == "health":
        import json
        from diabetic.utils.health import get_system_health

        snapshot = await get_system_health()
        print(json.dumps(snapshot, indent=2))
        return 0

    logger.error("Unknown command: %s", cmd)
    logger.error(
        "Usage: python -m diabetic.main "
        "[crash|faint|simulation|normal|live|export|cleanup|health|tui]"
    )
    return 2

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
        exit_code = await _run_command_loop()
        if exit_code:
            raise SystemExit(exit_code)
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
