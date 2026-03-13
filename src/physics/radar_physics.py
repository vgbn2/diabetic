import numpy as np
import matplotlib.pyplot as plt
from typing import Tuple, List
from ..logger import logger

class RadarPhysicsEngine:
    """
    Simulation of UWB Radar for Heartbeat Detection using Delta Dirac Pulses.
    This simulates the physics of electromagnetic waves reflecting off a moving chest wall.
    """
    
    def __init__(self, c: float = 3e8, fast_time_fs: float = 100e9, slow_time_fs: float = 20.0):
        """
        :param c: Speed of light (m/s).
        :param fast_time_fs: Fast-time sampling rate (100 GHz for sub-mm range resolution).
        :param slow_time_fs: Slow-time pulse repetition frequency (20 Hz).
        """
        self.c = c
        self.fast_fs = fast_time_fs
        self.slow_fs = slow_time_fs
        self.sigma = 0.5e-10 # Pulse width (seconds) for Gaussian monocycle (Delta Dirac approx)

    def generate_gaussian_monocycle(self, t: np.ndarray) -> np.ndarray:
        """Idealized pulse shape representing a Delta Dirac pulse after filtering/transmission."""
        return - (t / self.sigma**2) * np.exp(-t**2 / (2 * self.sigma**2))

    def simulate_radar_return(self, 
                              distance_m: float = 1.0, 
                              duration_s: float = 5.0, 
                              hr_bpm: float = 70.0, 
                              rr_bpm: float = 18.0) -> np.ndarray:
        """
        Simulates the 2D Radar Matrix [Slow-Time x Fast-Time].
        """
        # Slow-time setup
        num_pulses = int(duration_s * self.slow_fs)
        slow_time = np.linspace(0, duration_s, num_pulses)
        
        # Fast-time setup (Look at a 20 cm window around distance_m)
        num_range_bins = 512
        fast_time_offset = (2 * distance_m / self.c) - 1e-9
        fast_time = np.linspace(0, 2e-9, num_range_bins) # 2ns window
        
        # 1. Simulate Chest Wall Displacement (Respiration + Heartbeat)
        # Respiration: ~5mm, Heartbeat: ~0.5mm
        d_resp = 0.005 * np.sin(2 * np.pi * (rr_bpm / 60.0) * slow_time)
        d_heart = 0.0005 * np.sin(2 * np.pi * (hr_bpm / 60.0) * slow_time)
        d_total = distance_m + d_resp + d_heart
        
        # 2. Build the Radar Matrix
        radar_matrix = np.zeros((num_pulses, num_range_bins))
        
        logger.info(f"Simulating {num_pulses} radar pulses over {duration_s} seconds...")
        
        for i in range(num_pulses):
            # Calculate time delay for this specific pulse
            tau = 2 * d_total[i] / self.c
            # The pulse arrives at tau relative to our fast_time window
            # We center the pulse at tau in the fast-time window
            shifted_fast_time = fast_time - (tau - fast_time_offset)
            radar_matrix[i, :] = self.generate_gaussian_monocycle(shifted_fast_time)
            
        # Add white Gaussian noise
        radar_matrix += np.random.normal(0, 0.05, radar_matrix.shape)
        
        return radar_matrix

if __name__ == "__main__":
    # Test the physics engine
    physics = RadarPhysicsEngine()
    matrix = physics.simulate_radar_return(hr_bpm=72.0, rr_bpm=16.0)
    
    print("\nPhysics Simulation Complete:")
    print(f"Matrix Shape: {matrix.shape} (Pulses x Range Bins)")
    print(f"Range Resolution: {physics.c / (2 * physics.fast_fs) * 1000:.3f} mm per bin")
