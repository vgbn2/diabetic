"""
diabetic/ml_engine/forecast.py

Horizon projection for the TWA bridge (and the meal-forecast chart). Pure and
DB-free so it is unit-testable without a Coordinator: every input (twin, oracle,
history) is passed explicitly.

Two horizons:
  * 4h tactical  — DigitalTwin.predict_4h_trajectory (kinematic + COB/IOB +
                   oracle basal drift), at SAMPLING_INTERVAL_MINS resolution.
  * 1d circadian — BasalOracle.get_expected_basal sampled hourly over 24h;
                   empty until the oracle has been fit (>= 24h of data).
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import numpy as np

from diabetic import medical_constants as mc


def build_basal_drift(oracle, ref_start: datetime, n_points: int, dt: float,
                      now: Optional[datetime] = None) -> Optional[np.ndarray]:
    """
    Sample the BasalOracle circadian model into a per-step drift array aligned to
    `ref_start` (phase reference). Returns None when the oracle has not been fit,
    which DigitalTwin.predict_4h_trajectory treats as "no basal correction".
    """
    if oracle is None or getattr(oracle, "params", None) is None:
        return None
    now = now or datetime.now(timezone.utc)
    drift = np.zeros(n_points)
    for i in range(n_points):
        drift[i] = oracle.get_expected_basal(now + timedelta(minutes=i * dt), ref_start)
    return drift


def project_4h(twin, history: List, last_meal=None, oracle=None,
               now: Optional[datetime] = None) -> List[float]:
    """4h forward glucose trajectory as a rounded list. Empty when no history."""
    if not history:
        return []
    dt = mc.SAMPLING_INTERVAL_MINS
    n_points = int(240 / dt) + 1
    ref_start = history[0].glucose.timestamp
    drift = build_basal_drift(oracle, ref_start, n_points, dt, now=now)

    # The twin filters stale meals/insulin internally (relative to the latest
    # snapshot), so passing the current ones is safe.
    meals = [last_meal] if last_meal else None
    last_insulin = getattr(history[-1], "last_insulin", None)
    insulin_doses = [last_insulin] if last_insulin else None

    traj = twin.predict_4h_trajectory(
        history, meals=meals, insulin_doses=insulin_doses, basal_drift=drift
    )
    return [round(float(v), 2) for v in traj]


def project_24h(oracle, history: List, now: Optional[datetime] = None) -> List[float]:
    """
    24h circadian glucose projection (25 hourly points). Empty until the oracle
    is fit — there is no honest daily model before then.
    """
    if not history or oracle is None or getattr(oracle, "params", None) is None:
        return []
    ref_start = history[0].glucose.timestamp
    now = now or datetime.now(timezone.utc)
    return [
        round(float(oracle.get_expected_basal(now + timedelta(hours=h), ref_start)), 2)
        for h in range(25)
    ]


def build_horizons(twin, oracle, history: List, last_meal=None,
                   now: Optional[datetime] = None) -> dict:
    """Compute both horizons for the TWA forecast endpoint."""
    return {
        "h4": project_4h(twin, history, last_meal=last_meal, oracle=oracle, now=now),
        "h1d": project_24h(oracle, history, now=now),
    }
