from typing import List
from diabetic.registry import GlucoseReading
from diabetic import medical_constants as mc

class SignalQuality:
    """
    Identifies sensor artifacts and anomalies.
    Critical for avoiding false alarms from 'Compression Lows'.
    """
    @staticmethod
    def is_compression_low(last_readings: List[GlucoseReading]) -> bool:
        """
        Detects sudden, non-physiological drops caused by sleeping on the sensor.
        Logic: a drop with immediate recovery OR a non-physiological drop rate.
        """
        from diabetic.dsp.metabolic_math import MetabolicMath

        if len(last_readings) < 2:
            return False

        r_curr = last_readings[-1]
        r_prev = last_readings[-2]

        dt = MetabolicMath.get_dt(r_curr.timestamp, r_prev.timestamp)
        velocity = (r_curr.value - r_prev.value) / dt  # mmol/L per minute

        # 1. Recovery Check (Requires 3 readings)
        if len(last_readings) >= 3:
            r1, r2, r3 = last_readings[-3:]
            dt_r12 = MetabolicMath.get_dt(r2.timestamp, r1.timestamp)
            v12 = (r2.value - r1.value) / max(0.1, dt_r12)
            recovery = r3.value - r2.value

            if v12 < -mc.COMPRESSION_DROP_LIMIT and recovery > mc.COMPRESSION_RECOVERY_MIN:
                return True

        # 2. Hard boundary (Artifact-level drop rate)
        if velocity < -mc.COMPRESSION_DROP_LIMIT:
            return True

        return False

    @staticmethod
    def check_data_gap(last_readings: List[GlucoseReading], max_gap_mins: int = 15) -> bool:
        """Returns True if there is a significant missing data gap."""
        if len(last_readings) < 2:
            return False

        from diabetic.dsp.metabolic_math import MetabolicMath
        dt = MetabolicMath.get_dt(last_readings[-1].timestamp, last_readings[-2].timestamp)
        return dt > max_gap_mins