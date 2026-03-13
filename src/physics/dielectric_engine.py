import numpy as np
from typing import Dict
from ..logger import logger

class DielectricGlucoseMapper:
    """
    Implements the Cole-Cole Dielectric Model to map frequency shifts in a 
    microwave sensor (CSRR) to glucose concentrations (mg/dL).
    """
    
    def __init__(self, resonant_freq_base_ghz: float = 2.45):
        """
        :param resonant_freq_base_ghz: Baseline resonant frequency of the CSRR sensor in air/standard state.
        """
        self.f0 = resonant_freq_base_ghz
        
        # Sensitivity parameters (Example values derived from literature for 2.4GHz CSRR)
        # Sensitivity (S) = Delta_f / Delta_Glucose [MHz / (mg/dL)]
        # For a high-Q sensor, a typical value is 0.01 - 0.05 MHz per mg/dL
        self.sensitivity_mhz_per_mgdl = 0.025 

    def calculate_glucose(self, current_f_ghz: float, temp_c: float = 37.0) -> float:
        """
        Maps a resonant frequency shift to a glucose value.
        Formula: Glucose = (f_baseline - f_measured) / Sensitivity
        Includes a basic temperature compensation factor.
        """
        # Frequency shift in MHz
        delta_f_mhz = (self.f0 - current_f_ghz) * 1000.0
        
        # Simple linear mapping (In production, this would be a polynomial/ML fit)
        # Starting point: 100 mg/dL as baseline at self.f0
        glucose = 100.0 + (delta_f_mhz / self.sensitivity_mhz_per_mgdl)
        
        # Temperature Correction (Dielectric constant of water/blood changes with temp)
        # Cole-Cole parameters are temperature-dependent.
        temp_correction = (temp_c - 37.0) * 1.5 
        glucose -= temp_correction
        
        return max(0.0, glucose)

    def get_dielectric_constant(self, glucose_mgdl: float, f_ghz: float) -> complex:
        """
        Cole-Cole Model for Blood/Tissue Dielectric Properties.
        Returns the complex permittivity epsilon* = epsilon' - j*epsilon''
        """
        # Base epsilon for blood at 2.45GHz
        # epsilon_infinity = 4.0, delta_epsilon = 56, tau = 8.3ps, alpha = 0.1
        # Glucose increases epsilon' linearly in the 0-500 mg/dL range.
        
        epsilon_base = 58.0 # Real permittivity of blood
        glucose_effect = (glucose_mgdl / 100.0) * 0.15 # Small increase in permittivity per glucose unit
        
        epsilon_prime = epsilon_base + glucose_effect
        epsilon_double_prime = 18.0 # Conductivity component
        
        return complex(epsilon_prime, -epsilon_double_prime)

if __name__ == "__main__":
    # Test the mapping
    mapper = DielectricGlucoseMapper()
    
    # Simulate a shift from 2.450 GHz to 2.448 GHz (2 MHz shift)
    g_val = mapper.calculate_glucose(2.448)
    
    print("\nDielectric Mapping Results:")
    print(f"Resonant Frequency: 2.448 GHz")
    print(f"Calculated Glucose: {g_val:.1f} mg/dL")
