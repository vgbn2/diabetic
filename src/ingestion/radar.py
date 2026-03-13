import numpy as np
import pandas as pd
from scipy.signal import find_peaks, butter, filtfilt
from typing import Tuple, Dict, Optional
from ..logger import logger

class UWBRadarProcessor:
    """
    Processes Ultra-Wideband (UWB) Radar data to extract Heart Rate (HR) and Respiration Rate (RR).
    Uses the Fast-time (Range) / Slow-time (Pulse Repetition) matrix model.
    """
    
    def __init__(self, slow_time_fs: float = 20.0):
        """
        :param slow_time_fs: Sampling frequency of the radar pulses (Hz).
        """
        self.fs = slow_time_fs

    def _bandpass_filter(self, data: np.ndarray, lowcut: float, highcut: float, order: int = 4) -> np.ndarray:
        nyq = 0.5 * self.fs
        low = lowcut / nyq
        high = highcut / nyq
        b, a = butter(order, [low, high], btype='band')
        return filtfilt(b, a, data)

    def extract_vitals(self, radar_matrix: np.ndarray) -> Dict[str, Optional[float]]:
        """
        Main pipeline to extract HR and RR from a 2D radar matrix.
        
        :param radar_matrix: 2D numpy array [slow_time (pulses), fast_time (range bins)]
        :return: Dictionary containing extracted 'hr' (bpm) and 'rr' (bpm).
        """
        if radar_matrix.ndim != 2:
            logger.error("Radar matrix must be 2D (slow_time x fast_time).")
            return {"hr": None, "rr": None}

        # Step 1: Clutter Suppression (Background Subtraction)
        # Subtract the mean across slow-time to remove static reflections (walls, furniture)
        mean_clutter = np.mean(radar_matrix, axis=0)
        y_clutter_removed = radar_matrix - mean_clutter

        # Step 2: Range Bin Selection
        # Identify the range bin (fast-time index) with the maximum variance (chest wall displacement)
        variances = np.var(y_clutter_removed, axis=0)
        chest_bin_idx = np.argmax(variances)
        
        # Extract the 1D signal representing chest motion over time
        chest_signal = y_clutter_removed[:, chest_bin_idx]
        
        logger.info(f"Target located at range bin: {chest_bin_idx}")

        # Step 3: Signal Separation (Filtering)
        # Respiration typically: 0.1 - 0.5 Hz (6 - 30 breaths/min)
        # Heartbeat typically: 0.8 - 2.5 Hz (48 - 150 beats/min)
        
        try:
            resp_signal = self._bandpass_filter(chest_signal, lowcut=0.1, highcut=0.5)
            heart_signal = self._bandpass_filter(chest_signal, lowcut=0.8, highcut=2.5)
        except ValueError as e:
            logger.error(f"Filtering failed (likely not enough data points): {e}")
            return {"hr": None, "rr": None}

        # Step 4: Rate Estimation via FFT
        rr = self._estimate_rate_fft(resp_signal)
        hr = self._estimate_rate_fft(heart_signal)

        return {"hr": hr, "rr": rr}

    def _estimate_rate_fft(self, signal_1d: np.ndarray) -> Optional[float]:
        """Calculates the dominant frequency of a 1D signal using FFT and returns it in BPM."""
        n = len(signal_1d)
        if n == 0:
            return None
            
        # Compute FFT
        freqs = np.fft.rfftfreq(n, d=1/self.fs)
        fft_mag = np.abs(np.fft.rfft(signal_1d))
        
        # Find peak frequency
        peak_idx = np.argmax(fft_mag)
        dominant_freq_hz = freqs[peak_idx]
        
        # Convert Hz to Beats/Breaths per Minute
        bpm = dominant_freq_hz * 60.0
        return bpm

if __name__ == "__main__":
    # Test with synthetic radar data
    fs = 20.0 # 20 Hz pulse rate
    duration = 10 # 10 seconds of data
    t = np.linspace(0, duration, int(fs * duration), endpoint=False)
    
    # Synthetic vital signs
    true_rr_hz = 0.3 # 18 breaths/min
    true_hr_hz = 1.2 # 72 beats/min
    
    # Create synthetic chest movement (Respiration amplitude is much larger than HR)
    chest_motion = 5.0 * np.sin(2 * np.pi * true_rr_hz * t) + 0.5 * np.sin(2 * np.pi * true_hr_hz * t)
    
    # Create a dummy 2D radar matrix (100 bins, signal is at bin 45)
    mock_matrix = np.random.normal(0, 0.1, (len(t), 100)) # Static noise
    mock_matrix[:, 45] += chest_motion # Add the vital signs to one specific range bin
    
    processor = UWBRadarProcessor(slow_time_fs=fs)
    vitals = processor.extract_vitals(mock_matrix)
    
    print("\nRadar Processing Results:")
    print(f"Target HR: {true_hr_hz * 60:.1f} | Extracted HR: {vitals['hr']:.1f} BPM")
    print(f"Target RR: {true_rr_hz * 60:.1f} | Extracted RR: {vitals['rr']:.1f} BPM")
