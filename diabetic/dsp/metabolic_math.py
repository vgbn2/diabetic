import numpy as np
from typing import List, Tuple
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic import medical_constants

class MetabolicMath:
    """
    Core mathematical engine for risk assessment.
    Calculates LBGI (Low Blood Glucose Index) and HBGI (High Blood Glucose Index).
    """
    
    @staticmethod
    def calculate_risk_indices(glucose_val: float) -> Tuple[float, float]:
        """
        Transforms glucose (mmol/L) into risk space.
        Based on Kovatchev et al. (University of Virginia).
        """
        # Formula uses mg/dL internally for index calculation
        mgdl_raw = glucose_val * medical_constants.MMOL_TO_MGDL
        
        # Safety floor to prevent log domain errors or -inf results.
        # Sensors and biology rarely go below 20 mg/dL (~1.1 mmol/L).
        mgdl = np.maximum(mgdl_raw, 20.0)
        
        # Symmetrization transformation
        f = 1.509 * (np.log(mgdl)**1.084 - 5.381)
        risk = 10 * (f**2)
        
        lbgi = risk if f < 0 else 0
        hbgi = risk if f > 0 else 0
        
        return lbgi, hbgi

    @staticmethod
    def extract_kinematics(snapshots: List[MetabolicSnapshot], dt: float = None) -> Tuple[float, float]:
        """
        Calculates higher-order derivatives (Velocity, Acceleration).
        Uses current and previous smoothed values.
        """
        if len(snapshots) < 2:
            return 0.0, 0.0
            
        curr = snapshots[-1]
        prev = snapshots[-2]
        
        # Determine dt (minutes)
        if dt is None:
            dt = (curr.glucose.timestamp - prev.glucose.timestamp).total_seconds() / 60.0
            
        # Ensure dt is sane to prevent division by zero or errors on jitter
        dt = np.maximum(dt, 0.5)
        
        # Velocity is already provided by the Kalman filter in snapshot.velocity
        velocity = curr.velocity
        
        # Acceleration = Change in velocity over time
        # Since velocity is in units/min, acceleration is in units/min^2
        acceleration = (curr.velocity - prev.velocity) / dt
        
        return velocity, acceleration

    @staticmethod
    def calculate_atr(snapshots: List[MetabolicSnapshot], period: int = 14) -> float:
        """
        Calculates the Average True Range of glucose variations.
        Useful for measuring metabolic volatility.
        """
        if len(snapshots) < 2:
            return 0.0
        
        true_ranges = [
            abs(snapshots[i].filtered_value - snapshots[i-1].filtered_value)
            for i in range(1, len(snapshots))
        ]
        
        recent = true_ranges[-period:]
        return sum(recent) / len(recent)
