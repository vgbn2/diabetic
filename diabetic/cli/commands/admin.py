"""Data and administrative command adapters."""
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
        logger.error("Retention days must be an integer.")
        return 2

    result = await execute_retention_cleanup(days)
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
