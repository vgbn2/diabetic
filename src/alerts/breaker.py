from datetime import datetime, timedelta
from typing import Optional
from ..logger import logger

class DataCircuitBreaker:
    """
    Prevents the inference engine from predicting on stale or invalid data.
    Directly addresses the 'Interpolation Fallacy'.
    """
    
    def __init__(self, max_gap_minutes: int = 15):
        self.max_gap = timedelta(minutes=max_gap_minutes)
        self.last_sync_time: Optional[datetime] = None
        self.is_tripped: bool = False
        self.failure_count: int = 0
        self.max_failures: int = 3

    def validate_packet(self, timestamp: datetime) -> bool:
        """
        Check if the incoming packet is within a valid time window.
        Trips the breaker if a large gap is detected.
        """
        now = datetime.now()
        
        # 1. Check for staleness (Real-world latency)
        if (now - timestamp) > self.max_gap:
            logger.error(f"Data packet is stale. Lag: {(now - timestamp).total_seconds()/60:.1f} minutes.")
            self._trip()
            return False
            
        # 2. Check for data gaps (Interpolation check)
        if self.last_sync_time:
            gap = timestamp - self.last_sync_time
            if gap > self.max_gap:
                logger.warning(f"Metabolic gap detected: {gap.total_seconds()/60:.1f} minutes. Predictions paused.")
                self._trip()
                return False

        # Reset if everything is nominal
        self._reset(timestamp)
        return True

    def _trip(self):
        if not self.is_tripped:
            logger.critical("CIRCUIT BREAKER TRIPPED: Metabolic inference halted due to data integrity risk.")
            self.is_tripped = True
            
    def _reset(self, timestamp: datetime):
        if self.is_tripped:
            logger.info("CIRCUIT BREAKER RESET: Resuming inference on synchronized data stream.")
            self.is_tripped = False
        self.last_sync_time = timestamp
        self.failure_count = 0
