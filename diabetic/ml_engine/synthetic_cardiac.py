import numpy as np
from datetime import datetime
from typing import Optional
from diabetic.registry import CardiacReading, GlucoseReading
from diabetic import medical_constants as mc
from diabetic.config import config

class SyntheticCardiacEstimator:#how realistic is this?
    """
    Bio-Quant Synthetic Cardiac Layer (Layer 2.5).
    Estimates heart rate (BPM) and variability (HRV) from glucose dynamics
    when physical sensor hardware is missing.
    """
    
    def __init__(self):
        self.baseline_bpm = config.PATIENT_BPM_BASELINE or 70.0
        self.baseline_hrv = config.PATIENT_HRV_BASELINE or 50.0

    def estimate(self, 
                 glucose: GlucoseReading, 
                 velocity: float = 0.0, 
                 current_time: Optional[datetime] = None) -> CardiacReading:
        """
        Synthesizes a CardiacReading based on physiological stress markers.
        """
        if current_time is None:
            current_time = glucose.timestamp

        # 1. Circadian Oscillation (-5 to +5 BPM)
        # Deepest sleep at 3 AM (-5), Peak activity at 3 PM (+5)
        hour_pos = (current_time.hour + current_time.minute / 60.0) / 24.0
        circadian_offset = 5.0 * np.sin(2 * np.pi * (hour_pos - 0.375))
        
        # 2. Adrenaline Response (Hypo Stress)
        # Significant HR spike when BG < 3.9 mmol/L
        hypo_stress = 0.0
        if glucose.value < mc.LOW_SIDE_THRESHOLD:
            # Scale stress up to +20 BPM as glucose approaches critical floor
            delta = mc.LOW_SIDE_THRESHOLD - glucose.value
            hypo_stress = (delta / (mc.LOW_SIDE_THRESHOLD - mc.PHYSIO_FLOOR)) * 20.0
            
        # 3. Kinetic Stress (Rapid Drops)
        # HR increases with rapid downward velocity
        kinetic_stress = 0.0
        if velocity < 0:
            # Every 0.1 mmol/L per min drop adds ~10 BPM
            kinetic_stress = abs(velocity) / 0.1 * 10.0
            
        # 4. Hyper-Inflammation (High Sugar)
        # Sustained high sugar slightly elevates resting heart rate
        hyper_elevation = 0.0
        if glucose.value > mc.RENAL_THRESHOLD:
            hyper_elevation = (glucose.value - mc.RENAL_THRESHOLD) * 1.5

        # Final BPM Calculation
        est_bpm = self.baseline_bpm + circadian_offset + hypo_stress + kinetic_stress + hyper_elevation
        
        # HRV usually drops as BPM increases (Stress correlation)
        hrv_ratio = max(0.4, 1.0 - (hypo_stress + kinetic_stress) / 40.0)
        est_hrv = self.baseline_hrv * hrv_ratio

        return CardiacReading(
            timestamp=current_time,
            bpm=int(np.clip(est_bpm, 45, 160)),
            hrv=round(float(np.clip(est_hrv, 10, 100)), 2),
            source="synthetic_v1"
        )

# Singleton instance for the inference runner
cardiac_synthesizer = SyntheticCardiacEstimator()
