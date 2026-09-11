"""
Data & Admin handlers.

`export` reuses diabetic.main.handle_admin_commands. `cleanup` replicates the
small admin block from main.py:80-85 but parameterized by `--retention-days`
(default config.RETENTION_DAYS), calling the same MongoDBClient + AuditLogger.
"""
import logging

logger = logging.getLogger("Bio-Quant.CLI")


async def export(flags: dict) -> int:
    from diabetic.main import handle_admin_commands
    await handle_admin_commands("export")
    return 0


async def cleanup(flags: dict) -> int:
    from diabetic.config import config
    from diabetic.operations.retention import execute_retention_cleanup

    raw = str(flags.get("--retention-days") or "").strip()
    try:
        days = int(raw) if raw else config.RETENTION_DAYS
    except ValueError:
        return 2

    logger.info(f"[ADMIN] Enforcing {days}-day retention policy cleanup...")
    outcome = await execute_retention_cleanup(days)
    if outcome.successful:
        logger.info("[ADMIN] Cleanup complete.")
        return 0
    logger.error("[ADMIN] Cleanup failed or incomplete: state=%s, phase=%s", outcome.state, outcome.failed_phase)
    return 1
