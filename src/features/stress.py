import pandas as pd
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class HRVRecord:
    timestamp: datetime
    rmssd: float # Root Mean Square of Successive Differences (standard HRV metric)

class DynamicStressIndex:
    """
    Calculates the Dynamic Stress Index (DSI) based on Heart Rate Variability (HRV).
    A higher DSI indicates higher sympathetic nervous system arousal (stress).
    """
    
    def __init__(self, history_window_days: int = 7):
        self.history_window_days = history_window_days
        self.hrv_history: List[HRVRecord] = []
        self.baseline_hrv: float = 50.0 # Default starting baseline (ms)

    def add_reading(self, record: HRVRecord):
        """Add a new HRV reading and update the baseline."""
        self.hrv_history.append(record)
        self._prune_history(record.timestamp)
        self._recalculate_baseline()

    def _prune_history(self, current_time: datetime):
        """Remove readings older than the history window."""
        cutoff_time = current_time - pd.Timedelta(days=self.history_window_days)
        self.hrv_history = [r for r in self.hrv_history if r.timestamp >= cutoff_time]

    def _recalculate_baseline(self):
        """Recalculate the rolling average HRV baseline."""
        if len(self.hrv_history) > 10: # Need some minimum amount of data to be reliable
            self.baseline_hrv = sum(r.rmssd for r in self.hrv_history) / len(self.hrv_history)

    def get_current_dsi(self, current_rmssd: Optional[float] = None) -> float:
        """
        Calculate the current Dynamic Stress Index.
        Formula: max(0.5, Baseline_HRV / Current_HRV)
        Lower HRV = Higher Stress.
        """
        if current_rmssd is None or current_rmssd <= 0:
            return 1.0 # Neutral baseline if no data
            
        # Prevent division by zero and cap extreme values
        current_rmssd = max(current_rmssd, 5.0) 
        
        dsi = self.baseline_hrv / current_rmssd
        return max(0.5, min(dsi, 3.0)) # Cap DSI between 0.5 (very relaxed) and 3.0 (extreme stress)
