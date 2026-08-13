"""Bounded retention policy and truthful cleanup audit sequencing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Literal, Optional


MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650
RetentionState = Literal["completed", "partial", "unavailable", "failed"]


@dataclass(frozen=True)
class RetentionCleanupResult:
    state: RetentionState
    retention_days: int
    entries_deleted: int = 0
    treatments_deleted: int = 0
    failed_phase: Optional[str] = None
    reason: Optional[str] = None
    audit_durable: bool = True

    @property
    def successful(self) -> bool:
        return self.state == "completed" and self.audit_durable

    def audit_payload(self) -> dict:
        return {
            "retention_days": self.retention_days,
            "state": self.state,
            "entries_deleted": self.entries_deleted,
            "treatments_deleted": self.treatments_deleted,
            "failed_phase": self.failed_phase,
            "reason": self.reason,
        }


def retention_days_valid(days: object) -> bool:
    return (
        isinstance(days, int)
        and not isinstance(days, bool)
        and MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS
    )


def invalid_retention_result(days: object) -> RetentionCleanupResult:
    return RetentionCleanupResult(
        state="failed",
        retention_days=days if isinstance(days, int) and not isinstance(days, bool) else 0,
        failed_phase="validation",
        reason="invalid_retention_days",
    )


async def execute_retention_cleanup(
    days: int,
    *,
    mongo=None,
    audit=None,
) -> RetentionCleanupResult:
    """Run one retention cleanup and keep deletion truth separate from audit durability."""
    if mongo is None:
        from diabetic.ingestion.mongo import MongoDBClient

        mongo = MongoDBClient()
    if audit is None:
        from diabetic.utils.audit_logger import AuditLogger

        audit = AuditLogger()

    try:
        start = await audit.log_admin_action(
            "CLEANUP_START", {"retention_days": days}
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return RetentionCleanupResult(
            state="failed",
            retention_days=days,
            failed_phase="audit_start",
            reason=error.__class__.__name__,
            audit_durable=False,
        )
    if not start.durable:
        return RetentionCleanupResult(
            state="failed",
            retention_days=days,
            failed_phase="audit_start",
            reason="audit_not_durable",
            audit_durable=False,
        )

    if retention_days_valid(days):
        result = await mongo.run_retention_cleanup(days=days)
    else:
        result = invalid_retention_result(days)

    event_type = {
        "completed": "CLEANUP_COMPLETE",
        "partial": "CLEANUP_PARTIAL",
        "unavailable": "CLEANUP_FAILED",
        "failed": "CLEANUP_FAILED",
    }[result.state]
    try:
        outcome = await audit.log_admin_action(event_type, result.audit_payload())
    except asyncio.CancelledError:
        if result.entries_deleted or result.treatments_deleted:
            return replace(result, audit_durable=False)
        raise
    except Exception:
        return replace(result, audit_durable=False)
    if not outcome.durable:
        return replace(result, audit_durable=False)
    return result
