from typing import List
from diabetic.registry import GlucoseReading
from diabetic import medical_constants

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

        Fully operational only with >= 3 readings (recovery check requires 3).
        With 2 readings, only the hard rate boundary check applies.
        With < 2 readings, returns False unconditionally.
        """
        if len(last_readings) < 2:
            return False

        r_curr = last_readings[-1]
        r_prev = last_readings[-2]

        dt = (r_curr.timestamp - r_prev.timestamp).total_seconds() / 60.0
        dt = max(dt, 0.1)  # prevent div by zero on clock jitter

        velocity = (r_curr.value - r_prev.value) / dt
        v_per_5min = velocity * 5.0

        # Recovery Check (Post-hoc confirmation)
        if len(last_readings) >= 3:
            r1, r2, r3 = last_readings[-3:]
            # last_readings is oldest-first: r1=oldest, r2=middle, r3=newest.
            # FIX Bug2: was (r1.timestamp - r2.timestamp) which is negative
            # (r1 < r2 in time), causing max(negative, 0.1) = 0.1 always,
            # amplifying drop_per_5min by ~50x. Corrected to r2 - r1.
            dt_recent = (r2.timestamp - r1.timestamp).total_seconds() / 60.0
            dt_recent = max(dt_recent, 0.1)
            drop_per_5min = ((r1.value - r2.value) / dt_recent) * 5.0
            recovery = r3.value - r2.value

            if drop_per_5min > medical_constants.COMPRESSION_DROP_LIMIT_PER_5MIN and recovery > 1.0:
                return True

        # Hard boundary: artifact-level drop rate without recovery confirmation
        if v_per_5min < -medical_constants.COMPRESSION_DROP_LIMIT_PER_5MIN:
            return True

        return False

    @staticmethod
    def check_data_gap(last_readings: List[GlucoseReading], max_gap_mins: int = 20) -> bool:
        """Returns True if there is a significant missing data gap."""
        if len(last_readings) < 2:
            return False

        dt = (last_readings[-1].timestamp - last_readings[-2].timestamp).total_seconds() / 60.0
        return dt > max_gap_mins