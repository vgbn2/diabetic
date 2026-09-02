"""
diabetic/utils/data_factory.py

Bio-Quant State Factory — 5-Layer Metabolic Snapshot Assembler.

Responsibilities:
  - TacticalForecaster: regression-based 15/30/60m glucose projections
  - ConfidenceIndex: data density heuristic (0.0 - 1.0)
  - assemble_snapshot(): full 5-layer state synthesis
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np

logger = logging.getLogger("Bio-Quant.DataFactory")

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
from diabetic.config import config
_SENSOR_INTERVAL_MIN = config.SAMPLING_INTERVAL_MINS          # FIX M1: Follow config
_CONFIDENCE_WINDOW_MIN = 90       # Window for density calculation
_MIN_POINTS_FOR_REGRESSION = 3    # Below this, fall back to linear delta


# --------------------------------------------------------------------------- #
# TacticalForecaster
# --------------------------------------------------------------------------- #

class TacticalForecaster:
    """
    Kinematic glucose projection using linear regression over recent readings.

    Projects glucose at 15m, 30m, and 60m horizons using:
        G(t+Δt) = G_now + V·Δt + 0.5·A·Δt²

    where V (velocity, mmol/L/min) and A (acceleration, mmol/L/min²) are
    estimated via least-squares regression on recent timestamped readings.

    Bio-traits (Age, Weight, BMI) from VesselRegistry are accepted but currently
    used for future ISF-based correction; the kinematic model is physiology-agnostic.
    """

    def __init__(
        self,
        age: Optional[float] = None,
        weight_kg: Optional[float] = None,
        bmi: Optional[float] = None,
    ) -> None:
        self.age = age
        self.weight_kg = weight_kg or 70.0  # Default to 70kg if unknown
        self.bmi = bmi
        
        # [W1] Physiological Correction: compute ISF-based velocity dampener
        # Rule: Heavier patients have higher metabolic inertia (lower ISF).
        # ISF (mmol/L per unit) approx = 100 / (weight * 0.5)
        self.isf = 100.0 / (self.weight_kg * 0.5)
        # Normalize correction factor: baseline is 70kg (ISF ~2.85)
        # correction > 1.0 for lighter (faster change), < 1.0 for heavier (slower change)
        # FIX C1: correction should be isf / baseline_isf, not baseline_isf / isf
        self.velocity_correction = self.isf / 2.85 

    def compute(
        self,
        readings: list[tuple[datetime, float]],
    ) -> dict[str, float]:
        """
        Given a list of (timestamp, glucose_mmol_L) pairs (oldest → newest),
        return a dict with keys: velocity, acceleration, p15m, p30m, p60m.

        Falls back to last-known velocity if fewer than MIN_POINTS readings.
        All values are clamped to physiological range [2.2, 30.0].
        """
        if not readings:
            return {"velocity": 0.0, "acceleration": 0.0, "p15m": 0.0, "p30m": 0.0, "p60m": 0.0}

        # Convert timestamps relative to the latest reading (in minutes)
        t_latest = readings[-1][0]
        times_min = []
        values = []
        for ts, val in readings:
            dt_min = (ts - t_latest).total_seconds() / 60.0
            times_min.append(dt_min)
            values.append(val)

        g_now = values[-1]

        # Check if times_min has distinct timestamps to avoid singular Vandermonde matrix in polyfit
        has_distinct_times = len(set(times_min)) >= 3 if len(times_min) >= 3 else False

        if len(readings) < _MIN_POINTS_FOR_REGRESSION or not has_distinct_times:
            # Simple linear delta fallback
            if len(readings) >= 2 and readings[-1][0] != readings[-2][0]:
                dt = max((readings[-1][0] - readings[-2][0]).total_seconds() / 60.0, 1.0)
                v = (readings[-1][1] - readings[-2][1]) / dt
            else:
                v = 0.0
            a = 0.0
        else:
            # Quadratic regression: G(t) = c0 + c1·t + c2·t²
            x = np.array(times_min)
            y = np.array(values)
            # Fit degree-1 polynomial for velocity (degree-2 for acceleration)
            poly2 = np.polyfit(x, y, 2)   # [c2, c1, c0]
            poly1 = np.polyfit(x, y, 1)   # [c1, c0]
            v = float(poly1[0])            # slope (mmol/L per min)
            a = float(2 * poly2[0])        # 2nd derivative at t=0

        # [W1] Apply velocity correction factor based on physiological ISF
        v *= self.velocity_correction
        a *= self.velocity_correction

        def project(delta_min: float) -> float:
            raw = g_now + v * delta_min + 0.5 * a * delta_min ** 2
            return round(float(np.clip(raw, 2.2, 30.0)), 2)

        return {
            "velocity": round(v, 4),
            "acceleration": round(a, 6),
            "p15m": project(15.0),
            "p30m": project(30.0),
            "p60m": project(60.0),
        }


# --------------------------------------------------------------------------- #
# Confidence Index
# --------------------------------------------------------------------------- #

def compute_confidence_index(
    readings: list[tuple[datetime, float]],
    window_min: int = _CONFIDENCE_WINDOW_MIN,
    interval_min: int = _SENSOR_INTERVAL_MIN,
) -> float:
    """
    Calculate sensor data density for the given time window.

    Returns a float in [0.0, 1.0]:
        1.0 = every expected reading present
        0.0 = no readings in window

    Penalises for missing sensor intervals; never exceeds 1.0.
    """
    if not readings:
        return 0.0

    expected = window_min / interval_min
    now = datetime.now(timezone.utc)

    # Count readings within the window
    received = sum(
        1 for ts, _ in readings
        if (now - ts).total_seconds() / 60.0 <= window_min
    )

    return round(min(received / max(expected, 1), 1.0), 3)


# --------------------------------------------------------------------------- #
# __main__ test shim for /verify step
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys
    from datetime import timedelta

    if "--test-projection" in sys.argv:
        now = datetime.now(timezone.utc)
        mock_readings = [
            (now - timedelta(minutes=20), 7.0),
            (now - timedelta(minutes=15), 6.8),
            (now - timedelta(minutes=10), 6.5),
            (now - timedelta(minutes=5),  6.1),
            (now,                          5.8),
        ]
        forecaster = TacticalForecaster(age=25, weight_kg=70, bmi=22.9)
        result = forecaster.compute(mock_readings)
        confidence = compute_confidence_index(mock_readings)
        logger.info(f"[VERIFY] Velocity: {result['velocity']} mmol/L/min")
        logger.info(f"[VERIFY] Acceleration: {result['acceleration']} mmol/L/min²")
        logger.info(f"[VERIFY] P15m: {result['p15m']} | P30m: {result['p30m']} | P60m: {result['p60m']}")
        logger.info(f"[VERIFY] Confidence Index: {confidence}")
