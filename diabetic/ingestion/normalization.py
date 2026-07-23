"""Boundary normalization for Nightscout clinical records."""

from __future__ import annotations

import math
from typing import Any

from diabetic import medical_constants


_MGDL_UNITS = {"mg/dl", "mgdl", "mg"}
_MMOL_UNITS = {"mmol/l", "mmol", "mmolperliter", "mmol/liter"}


def normalize_nightscout_sgv(raw: Any, units: str | None = None) -> float:
    """Return a Nightscout SGV as mmol/L without guessing from its magnitude.

    Nightscout-compatible ``sgv`` values default to mg/dL when the source does
    not include an authoritative unit. Unknown unit labels are rejected.
    """

    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("SGV must be numeric") from exc

    if not math.isfinite(value) or value <= 0:
        raise ValueError("SGV must be finite and positive")

    normalized_units = (units or "").strip().lower().replace(" ", "")
    if not normalized_units or normalized_units in _MGDL_UNITS:
        return value / medical_constants.MMOL_TO_MGDL
    if normalized_units in _MMOL_UNITS:
        return value
    raise ValueError(f"Unsupported SGV unit: {units!r}")
