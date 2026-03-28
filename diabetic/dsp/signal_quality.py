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
        Detects sudden, non-physiological drops often caused by sleeping on the sensor.
        Logic: A drop with immediate recovery OR a non-physiological drop rate.
        """
        if len(last_readings) < 2:
            return False
            
        r_curr = last_readings[-1]
        r_prev = last_readings[-2]
        
        dt = (r_curr.timestamp - r_prev.timestamp).total_seconds() / 60.0
        dt = max(dt, 0.1) # Prevent div by zero
        
        velocity = (r_curr.value - r_prev.value) / dt
        
        # 1. Immediate Rate Check (Physiological Fallacy)
        # Even with an insulin overdose, it is extremely rare for glucose to drop
        # faster than physiological limits (~1.5 mmol/L per 5 mins).
        # We use a conservative 'pure noise' boundary based on COMPRESSION_DROP_LIMIT.
        v_per_5min = velocity * 5.0

        # 2. Recovery Check (Post-hoc confirmation)
        if len(last_readings) >= 3:
            r1, r2, r3 = last_readings[-3:]
            # Normalize internal differences to 5-minute interval for constant comparison
            dt_recent = (r1.timestamp - r2.timestamp).total_seconds() / 60.0
            dt_recent = max(dt_recent, 0.1)
            drop_per_5min = ((r1.value - r2.value) / dt_recent) * 5.0
            recovery = r3.value - r2.value
            
            if drop_per_5min > medical_constants.COMPRESSION_DROP_LIMIT_PER_5MIN and recovery > 1.0:
                return True
            
        # Hard boundary for artifact detection (e.g., -2.0 per 5 min)
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
