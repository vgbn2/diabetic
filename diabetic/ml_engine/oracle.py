import numpy as np
import logging
from datetime import datetime, timezone
from scipy.optimize import curve_fit
from typing import List, Optional
from diabetic.registry import MetabolicSnapshot
from diabetic import medical_constants as mc

logger = logging.getLogger("Bio-Quant.ML.Oracle")

class BasalOracle:
    """
    Harmonic model for Circadian Glucose Rhythms.
    Fits a 24-hour sinusoidal wave to historical data to predict 'Basal Glide'.
    """
    def __init__(self, history_days: int = 3):
        self.history_days = history_days
        self.params = None # [Amplitude, Phase, Offset]
        self.last_fit_time: Optional[datetime] = None
        self.fit_start_ts: Optional[datetime] = None

    def _harmonic_model(self, t_hours, A, phi, C):
        """Standard sinusoidal wave: period=24h."""
        return A * np.sin(2 * np.pi * t_hours / 24.0 + phi) + C

    def fit(self, history: List[MetabolicSnapshot]):
        """Fits the model to historical data."""
        # 24h * 60m / 2.5m = 576 samples
        min_samples = int(24 * 60 / mc.SAMPLING_INTERVAL_MINS)
        if len(history) < min_samples:
            return # Need at least 24h of data

        # Extract times (in hours from start) and glucose
        start_ts = history[0].glucose.timestamp
        self.fit_start_ts = start_ts
        times = []
        values = []

        for s in history:
            # Fit only to "fasting" data (low active carbs/insulin)
            if s.active_carbs < 5.0 and s.active_insulin < 1.0:
                dt_hours = (s.glucose.timestamp - start_ts).total_seconds() / 3600.0
                times.append(dt_hours)
                values.append(s.filtered_value)

        if len(times) < 100: return

        # Initial guess: Amp=1.5, Phase=0, Offset=mean
        guess = [1.5, 0, np.mean(values)]

        # Wave 2 Hardening: Strict Bounds to prevent sinusoidal runaways on noisy data
        # Amp: [0.1, 8.0] mmol/L
        # Phase: [-pi, pi]
        # Offset: [3.0, 15.0] mmol/L
        bounds = ([0.1, -np.pi, 3.0], [8.0, np.pi, 15.0])

        try:
            popt, _ = curve_fit(self._harmonic_model, times, values, p0=guess, bounds=bounds)
            self.params = popt
            self.last_fit_time = datetime.now(timezone.utc)
        except Exception as e:
            # ponytail: fallback to None when curve_fit fails on sparse data; get_expected_basal uses 6.5 default
            logger.warning("BasalOracle curve_fit failed: %s (%s); reverting to baseline default", type(e).__name__, e)
            self.params = None

    def get_expected_basal(self, target_time: datetime, reference_start: Optional[datetime] = None) -> float:
        """Predicts basal glucose for a future timestamp."""
        if self.params is None:
            return 6.5 # Default fallback

        # ponytail: anchor to fit_start_ts or midnight to preserve harmonic diurnal phase
        ref = reference_start or self.fit_start_ts or target_time.replace(hour=0, minute=0, second=0, microsecond=0)
        dt_hours = (target_time - ref).total_seconds() / 3600.0
        return self._harmonic_model(dt_hours, *self.params)

if __name__ == "__main__":
    oracle = BasalOracle()
    logger.info("BasalOracle logic initialized.")
