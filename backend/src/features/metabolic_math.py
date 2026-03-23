import numpy as np
from typing import List, Tuple
from backend.src.registry import GlucoseReading, MetabolicSnapshot

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
        mgdl = glucose_val * 18.018
        
        # Symmetrization transformation
        f = 1.509 * (np.log(mgdl)**1.084 - 5.381)
        risk = 10 * (f**2)
        
        lbgi = risk if f < 0 else 0
        hbgi = risk if f > 0 else 0
        
        return lbgi, hbgi

    @staticmethod
    def extract_kinematics(snapshots: List[MetabolicSnapshot]) -> Tuple[float, float]:
        """
        Calculates higher-order derivatives (Velocity, Acceleration).
        Uses current and previous smoothed values.
        """
        if len(snapshots) < 2:
            return 0.0, 0.0
            
        curr = snapshots[-1]
        prev = snapshots[-2]
        
        # Velocity is already provided by the Kalman filter in snapshot.velocity
        velocity = curr.velocity
        
        # Acceleration = Change in velocity over time (dt=5 mins)
        acceleration = (curr.velocity - prev.velocity) / 5.0
        
        return velocity, acceleration
