from typing import List
from backend.src.registry import GlucoseReading

class SignalQuality:
    """
    Identifies sensor artifacts and anomalies.
    Critical for avoiding false alarms from 'Compression Lows'.
    """
    @staticmethod
    def is_compression_low(last_readings: List[GlucoseReading]) -> bool:
        """
        Detects sudden, non-physiological drops often caused by sleeping on the sensor.
        Logic: A drop > 2 mmol/L in 5 mins with immediate recovery is likely compression.
        """
        if len(last_readings) < 3:
            return False
            
        r1, r2, r3 = last_readings[-3:]
        drop = r1.value - r2.value
        recovery = r3.value - r2.value
        
        # Physiological limits: Glucose rarely drops > 1.5 mmol/L in 5 mins naturally
        if drop > 2.0 and recovery > 1.0:
            return True
            
        return False

    @staticmethod
    def check_data_gap(last_readings: List[GlucoseReading], max_gap_mins: int = 20) -> bool:
        """Returns True if there is a significant missing data gap."""
        if len(last_readings) < 2:
            return False
            
        dt = (last_readings[-1].timestamp - last_readings[-2].timestamp).total_seconds() / 60.0
        return dt > max_gap_mins
