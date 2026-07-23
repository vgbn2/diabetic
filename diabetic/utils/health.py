"""Bounded, machine-readable runtime health checks."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("Bio-Quant.Health")


async def _nightscout_status(url: str) -> str:
    if not url:
        return "missing"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{url.rstrip('/')}/api/v1/status.json")
            return "ok" if response.status_code < 500 else "unreachable"
    except Exception:
        return "unreachable"


async def _mongo_status(db_manager) -> str:
    if db_manager.client is None:
        return "missing"
    try:
        await asyncio.wait_for(db_manager.client.admin.command("ping"), timeout=3.0)
        return "ok"
    except Exception:
        return "unreachable"


async def get_system_health() -> dict:
    from diabetic.config import config
    from diabetic.ml_engine.training_service import read_training_manifest, sha256_file
    from diabetic.utils.db import db_manager

    nightscout, mongodb = await asyncio.gather(
        _nightscout_status(config.NIGHTSCOUT_URL),
        _mongo_status(db_manager),
    )
    health: dict = {"nightscout": nightscout, "mongodb": mongodb}

    weight_path = Path(config.ML_WEIGHTS_PATH)
    manifest = read_training_manifest()
    if weight_path.exists():
        age_secs = datetime.now(timezone.utc).timestamp() - weight_path.stat().st_mtime
        age_days = round(age_secs / 86400.0, 1)
        actual_hash = sha256_file(weight_path)
        expected_hash = manifest.get("sha256")
        checksum_ok = expected_hash is not None and expected_hash == actual_hash
        status = "fresh" if age_days <= config.TRAIN_STALE_DAYS else "stale"
        if expected_hash is None:
            status = "unverified"
        elif not checksum_ok:
            status = "checksum_mismatch"
        health["ml_weights"] = {
            "version": config.ML_WEIGHTS_VERSION,
            "age_days": age_days,
            "status": status,
            "checksum_ok": checksum_ok,
            "path": str(weight_path),
        }
    else:
        health["ml_weights"] = {
            "version": config.ML_WEIGHTS_VERSION,
            "age_days": None,
            "status": "missing",
            "checksum_ok": False,
            "path": str(weight_path),
        }

    weights_loaded = False
    try:
        from diabetic.coordinator import Coordinator

        coordinator = Coordinator._instance
        if coordinator and getattr(coordinator, "_initialized", False):
            buffer_size = len(coordinator.snapshots)
            weights_loaded = bool(
                getattr(getattr(coordinator, "neural_runner", None), "weights_loaded", False)
            )
        else:
            buffer_size = 0
    except Exception:
        buffer_size = 0

    health["snapshot_buffer"] = buffer_size
    health["inference_weights_loaded"] = weights_loaded
    health["inference_active"] = buffer_size >= 30 and weights_loaded

    last_ts: Optional[datetime] = None
    try:
        from diabetic.utils.audit_logger import AuditLogger

        last_ts = await AuditLogger().get_last_reading_timestamp()
    except Exception as exc:
        logger.debug("Could not retrieve last reading timestamp: %s", exc)

    if last_ts is not None:
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        age_mins = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60.0
        health["last_reading_ts"] = last_ts.isoformat()
        health["last_reading_age_mins"] = (
            round(age_mins, 1) if math.isfinite(age_mins) else None
        )
    else:
        health["last_reading_ts"] = None
        health["last_reading_age_mins"] = None

    health["ready"] = (
        nightscout == "ok"
        and mongodb == "ok"
        and health["ml_weights"]["status"] in {"fresh", "stale"}
    )
    return health
