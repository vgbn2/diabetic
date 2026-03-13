import math
import numpy as np
from scipy.special import gammainc
from datetime import datetime, timedelta
from typing import List, Dict

class MetabolicKinetics:
    """Handles IOB (Insulin on Board) and COB (Carbs on Board) calculations."""
    
    def __init__(self, dia_hours: float = 5.0, peak_minutes: float = 75.0, absorption_rate_g_hr: float = 30.0):
        self.dia_mins = dia_hours * 60
        self.peak_mins = peak_minutes
        self.carb_rate = absorption_rate_g_hr

    def calculate_iob(self, insulin_units: float, minutes_ago: float) -> float:
        """
        Scalable Exponential IOB (Dragan Maksimovic model).
        Returns the units of insulin still active.
        """
        if minutes_ago <= 0: return insulin_units
        if minutes_ago >= self.dia_mins: return 0.0
        
        t = minutes_ago
        tp = self.peak_mins
        td = self.dia_mins
        
        # Calculate tau and n for the gamma distribution based on peak and duration
        tau = tp * (1 - tp / td) / (1 - 2 * tp / td)
        n = tp / tau
        
        # IOB is 1 - (Area Under Activity Curve at t / Total Area)
        # Using regularized incomplete gamma function
        iob_fraction = 1 - gammainc(n + 1, t / tau)
        return max(0.0, insulin_units * iob_fraction)

    def calculate_cob(self, carbs_grams: float, minutes_ago: float) -> float:
        """
        Calculates Carbs on Board using a simple linear decay.
        Future proofed for dynamic absorption models.
        """
        if minutes_ago <= 0: return carbs_grams
        
        absorbed = (self.carb_rate / 60.0) * minutes_ago
        remaining = carbs_grams - absorbed
        return max(0.0, remaining)

    def get_bolus_impact(self, treatments: List[Dict], target_time: datetime) -> Dict[str, float]:
        """
        Aggregates IOB and COB from a list of treatment events for a specific target time.
        """
        total_iob = 0.0
        total_cob = 0.0
        
        for treat in treatments:
            event_time = treat.get('timestamp')
            if not event_time or event_time > target_time:
                continue
            
            minutes_ago = (target_time - event_time).total_seconds() / 60.0
            
            # Add Insulin impact
            insulin = treat.get('insulin', 0.0)
            if insulin > 0:
                total_iob += self.calculate_iob(insulin, minutes_ago)
                
            # Add Carb impact
            carbs = treat.get('carbs', 0.0)
            if carbs > 0:
                total_cob += self.calculate_cob(carbs, minutes_ago)
                
        return {"iob": total_iob, "cob": total_cob}
