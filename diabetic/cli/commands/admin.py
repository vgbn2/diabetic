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
    from diabetic.ingestion.mongo import MongoDBClient
    from diabetic.utils.audit_logger import AuditLogger

    raw = str(flags.get("--retention-days") or "").strip()
    days = int(raw) if raw else config.RETENTION_DAYS

    audit = AuditLogger()
    mongo = MongoDBClient()

    logger.info(f"[ADMIN] Enforcing {days}-day retention policy cleanup...")
    await audit.log_admin_action("CLEANUP_START", {"retention_days": days})
    await mongo.run_retention_cleanup(days=days)
    await audit.log_admin_action("CLEANUP_COMPLETE", {"retention_days": days})
    logger.info("[ADMIN] Cleanup complete.")
    return 0
