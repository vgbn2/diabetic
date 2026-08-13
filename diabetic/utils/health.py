"""Bounded, machine-readable runtime health checks."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Bio-Quant.Health")


async def _nightscout_status() -> str:
    from diabetic.ingestion.nightscout import NightscoutClient

    client = NightscoutClient()
    try:
        result = await asyncio.wait_for(client.probe_access(), timeout=4.0)
        return result.state
    except asyncio.TimeoutError:
        return "unreachable"
    finally:
        await client.close()


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
        _nightscout_status(),
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
    coordinator = None
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
    reading_source = "none"
    if coordinator and getattr(coordinator, "_initialized", False) and coordinator.snapshots:
        last_ts = coordinator.snapshots[-1].glucose.timestamp
        reading_source = "coordinator"
    else:
        try:
            from diabetic.utils.audit_logger import AuditLogger

            last_ts = await AuditLogger().get_last_reading_timestamp()
            if last_ts is not None:
                reading_source = "audit"
        except Exception as exc:
            logger.debug("Could not retrieve last reading timestamp: %s", exc)

    reading_fresh = False
    if last_ts is not None:
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        age_mins = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60.0
        reading_fresh = (
            math.isfinite(age_mins)
            and 0.0 <= age_mins <= config.HUD_STALE_AFTER_SECS / 60.0
        )
        health["last_reading_ts"] = last_ts.isoformat()
        health["last_reading_age_mins"] = (
            round(age_mins, 1) if math.isfinite(age_mins) else None
        )
    else:
        health["last_reading_ts"] = None
        health["last_reading_age_mins"] = None

    health["last_reading_source"] = reading_source
    health["last_reading_fresh"] = reading_fresh

    readiness_reasons = []
    if nightscout != "ok":
        readiness_reasons.append(f"nightscout_{nightscout}")
    if mongodb != "ok":
        readiness_reasons.append(f"mongodb_{mongodb}")
    if reading_source != "coordinator":
        readiness_reasons.append("coordinator_reading_unavailable")
    elif not reading_fresh:
        readiness_reasons.append("stale_metabolic_snapshot")

    health["ready"] = not readiness_reasons
    health["readiness_reasons"] = readiness_reasons

    neural_reasons = list(readiness_reasons)
    if health["ml_weights"]["status"] != "fresh":
        neural_reasons.append(f"ml_weights_{health['ml_weights']['status']}")
    if not weights_loaded:
        neural_reasons.append("inference_weights_not_loaded")
    if buffer_size < 30:
        neural_reasons.append("insufficient_snapshot_buffer")
    health["neural_ready"] = not neural_reasons
    health["neural_readiness_reasons"] = neural_reasons

    if coordinator and getattr(coordinator, "_initialized", False):
        fetched_at = getattr(coordinator, "treatment_fetched_at", None)
        health["treatments"] = {
            "state": getattr(coordinator, "treatment_fetch_state", "waiting"),
            "source": getattr(coordinator, "treatment_source", None),
            "fetched_at": fetched_at.isoformat() if fetched_at else None,
            "reason": getattr(coordinator, "treatment_degraded_reason", None),
        }
    else:
        health["treatments"] = {
            "state": "waiting",
            "source": None,
            "fetched_at": None,
            "reason": "coordinator_unavailable",
        }
    return health
