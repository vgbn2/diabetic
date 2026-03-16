import numpy as np
from typing import Tuple, Dict, Optional
from ..logger import logger

class RadarPhysicsEngine:
    """
    Simulates UWB Radar Pulse propagation and vital sign reflection.
    Refined: Includes Random Body Movement (RBM) and Multipath interference.
    """
    
    def __init__(self, c: float = 3e8, fast_time_fs: float = 128e9, slow_time_fs: float = 20.0):
        self.c = c
        self.fast_fs = fast_time_fs
        self.slow_fs = slow_time_fs
        # Pulse width for Gaussian monocycle (T_p)
        self.tau_p = 0.5e-9 

    def generate_monocycle(self, t: np.ndarray) -> np.ndarray:
        """Physical UWB pulse (2nd derivative of Gaussian)."""
        return (1 - 4 * np.pi * (t / self.tau_p)**2) * np.exp(-2 * np.pi * (t / self.tau_p)**2)

    def simulate_radar_return(self, 
                              distance_m: float = 1.0, 
                              duration_s: float = 10.0, 
                              hr_bpm: float = 72.0, 
                              rr_bpm: float = 16.0,
                              snr_db: float = 15.0,
                              movement_intensity: float = 0.0) -> np.ndarray:
        """
        Generates a 2D Radar Matrix [Slow-Time x Fast-Time] with artifacts.
        """
        num_pulses = int(duration_s * self.slow_fs)
        slow_time = np.linspace(0, duration_s, num_pulses)
        
        num_range_bins = 1024
        window_size_ns = 4.0
        fast_time = np.linspace(0, window_size_ns * 1e-9, num_range_bins)
        
        # 1. Biological Displacement
        d_resp = 0.005 * np.sin(2 * np.pi * (rr_bpm / 60.0) * slow_time)
        d_heart = 0.0005 * np.sin(2 * np.pi * (hr_bpm / 60.0) * slow_time)
        
        # 2. Random Body Movement (RBM)
        # Large-scale low-frequency noise that masks small vital signs
        rbm = movement_intensity * np.cumsum(np.random.normal(0, 0.0001, num_pulses))
        
        d_total = distance_m + d_resp + d_heart + rbm
        
        # 3. Fast-Time / Slow-Time Matrix Generation
        radar_matrix = np.zeros((num_pulses, num_range_bins))
        
        # Add Multipath (Static reflections from walls)
        clutter_bin_idx = int(0.6 * num_range_bins) # Static wall at 0.6 window
        radar_matrix[:, clutter_bin_idx] = 1.0 
        
        logger.info(f"Simulating Radar: Pulse Width {self.tau_p*1e12:.1f}ps | Resolution {self.c/(2*self.fast_fs)*1000:.2f}mm")
        
        for i in range(num_pulses):
            tau_delay = 2 * d_total[i] / self.c
            # Pulse Arrival Time shifted into our fast-time window
            shifted_t = fast_time - tau_delay
            radar_matrix[i, :] += self.generate_monocycle(shifted_t)
            
        # 4. Add Noise (SNR control)
        signal_power = np.mean(radar_matrix**2)
        noise_power = signal_power / (10**(snr_db / 10))
        noise = np.random.normal(0, np.sqrt(noise_power), radar_matrix.shape)
        
        return radar_matrix + noise

if __name__ == "__main__":
    physics = RadarPhysicsEngine()
    
    # CASE: Dirty Signal (Low SNR + Movement)
    matrix = physics.simulate_radar_return(snr_db=5.0, movement_intensity=0.1)
    
    print("\n--- Radar Physics Validation ---")
    print(f"Matrix Generated: {matrix.shape}")
    print(f"Noise Level: High (SNR 5dB)")
    print(f"RBM Artifacts: Enabled")
