"""
diabetic/utils/health.py

System health snapshot — mirrors the `backend integrity --json` pattern from
personal_finance_draft. Returns a machine-readable dict covering ML weights,
database connectivity, snapshot buffer fullness, and last reading freshness.

Usage (CLI):
    python -m diabetic.main health
"""

import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Bio-Quant.Health")


async def get_system_health() -> dict:
    """
    Returns a JSON-serializable health snapshot.
    All checks are non-blocking; connectivity is inferred from config/state,
    not live HTTP — so this is safe to call at any time without side effects.
    """
    from diabetic.config import config
    from diabetic.utils.db import db_manager

    health: dict = {}

    # --- 1. Nightscout ---
    health["nightscout"] = "configured" if config.NIGHTSCOUT_URL else "missing"

    # --- 2. MongoDB ---
    health["mongodb"] = "ok" if db_manager.entries is not None else "missing"

    # --- 3. ML Weights ---
    weight_path = Path(config.ML_WEIGHTS_PATH)
    if weight_path.exists():
        age_secs = datetime.now(timezone.utc).timestamp() - weight_path.stat().st_mtime
        age_days = round(age_secs / 86400.0, 1)
        health["ml_weights"] = {
            "version": config.ML_WEIGHTS_VERSION,
            "age_days": age_days,
            "status": "fresh" if age_days <= 7 else "stale",
            "path": str(weight_path),
        }
    else:
        health["ml_weights"] = {
            "version": config.ML_WEIGHTS_VERSION,
            "age_days": None,
            "status": "missing",
            "path": str(weight_path),
        }

    # --- 4. Snapshot buffer (only meaningful when Coordinator is running) ---
    try:
        from diabetic.coordinator import Coordinator
        coord = Coordinator._instance
        if coord and getattr(coord, "_initialized", False):
            buf_size = len(coord.snapshots)
        else:
            buf_size = 0
    except Exception:
        buf_size = 0

    health["snapshot_buffer"] = buf_size
    health["inference_active"] = buf_size >= 30

    # --- 5. Last reading timestamp (from local SQLite audit log) ---
    last_ts: Optional[datetime] = None
    try:
        from diabetic.utils.audit_logger import AuditLogger
        audit = AuditLogger()
        last_ts = await audit.get_last_reading_timestamp()
    except Exception as e:
        logger.debug("Could not retrieve last reading timestamp: %s", e)

    if last_ts is not None:
        # Ensure UTC-aware
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        age_mins = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60.0
        health["last_reading_ts"] = last_ts.isoformat()
        health["last_reading_age_mins"] = round(age_mins, 1) if math.isfinite(age_mins) else None
    else:
        health["last_reading_ts"] = None
        health["last_reading_age_mins"] = None

    return health
