"""Timestamp compatibility helpers for mixed-generation Nightscout documents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def treatment_timestamp(document: dict[str, Any]) -> datetime | None:
    """Return a UTC timestamp from BSON Date, ISO text, or epoch milliseconds."""

    value = document.get("mills")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)

    value = document.get("created_at")
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
