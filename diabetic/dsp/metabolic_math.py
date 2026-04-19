import numpy as np
from typing import List, Tuple
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic import medical_constants as mc

class MetabolicMath:
    """
    Core mathematical engine for risk assessment.
    """

    @staticmethod
    def calculate_risk_indices(glucose_val: float) -> Tuple[float, float]:
        """
        Transforms glucose (mmol/L) into risk space.
        """
        mgdl_raw = glucose_val * mc.MMOL_TO_MGDL
        mgdl = np.clip(mgdl_raw, mc.KOVATCHEV_FLOOR_MGDL, mc.KOVATCHEV_CEIL_MGDL)
        symmetrized_val = mc.KOVATCHEV_PRE_MULT * (np.log(mgdl)**mc.KOVATCHEV_EXP - mc.KOVATCHEV_OFFSET)
        risk = mc.KOVATCHEV_RISK_MULT * (symmetrized_val**2)
        lbgi = risk if symmetrized_val < 0 else 0.0
        hbgi = risk if symmetrized_val > 0 else 0.0
        return lbgi, hbgi

    @staticmethod
    def get_dt(time_curr, time_prev) -> float:
        """
        Calculates time delta in minutes with a numerical safety floor.
        """
        dt = (time_curr - time_prev).total_seconds() / 60.0
        return max(dt, mc.MIN_DT_FLOOR)

    @staticmethod
    def calculate_atr(snapshots: List[MetabolicSnapshot], period: int = 14) -> float:
        """
        Calculates the Time-Normalized Average True Range of glucose variations.
        """
        if len(snapshots) < 2:
            return 0.0

        lookback = snapshots[-(period + 1):]
        normalized_ranges = []

        for i in range(1, len(lookback)):
            curr = lookback[i]
            prev = lookback[i-1]
            delta = abs(curr.filtered_value - prev.filtered_value)
            dt = MetabolicMath.get_dt(curr.glucose.timestamp, prev.glucose.timestamp)
            normalized_ranges.append(delta * (mc.SAMPLING_INTERVAL_MINS / dt))

        return sum(normalized_ranges) / len(normalized_ranges)