"""Presentation-only glucose unit conversion.

Clinical models, storage, filtering, forecasting, and alerting always use mmol/L.
This module is the only owner allowed to apply the process-wide display preference.
"""

from __future__ import annotations

from typing import Iterable, Literal

from diabetic import medical_constants
from diabetic.config import config

DisplayRange = Literal["low", "in_range", "high"]


def prefers_mmol() -> bool:
    return bool(config.PREFER_MMOL)


def unit_label() -> str:
    return "mmol/L" if prefers_mmol() else "mg/dL"


def decimal_places() -> int:
    return 1 if prefers_mmol() else 0


def glucose_value(value_mmol: float) -> float:
    if prefers_mmol():
        return float(value_mmol)
    return float(value_mmol) * medical_constants.MMOL_TO_MGDL


def glucose_velocity(value_mmol_per_minute: float) -> float:
    return glucose_value(value_mmol_per_minute)


def glucose_series(values_mmol: Iterable[float]) -> list[float]:
    return [glucose_value(value) for value in values_mmol]


def format_glucose(value_mmol: float) -> str:
    return f"{glucose_value(value_mmol):.{decimal_places()}f}"


def format_velocity(value_mmol_per_minute: float) -> str:
    places = 2 if prefers_mmol() else 1
    return f"{glucose_velocity(value_mmol_per_minute):+.{places}f}"


def hud_range(value_mmol: float) -> DisplayRange:
    if value_mmol < 4.0:
        return "low"
    if value_mmol > 10.0:
        return "high"
    return "in_range"


def hud_haptic_warning(value_mmol: float) -> bool:
    return value_mmol < 4.0 or value_mmol > 13.0
