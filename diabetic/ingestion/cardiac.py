import asyncio
import logging
import math
import random
import statistics
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict
from diabetic.registry import CardiacReading
from diabetic.config import config
from diabetic.medical_constants import (
    CARDIAC_WINDOW_SAMPLES, 
    CARDIAC_QUALITY_DIVISOR,
    BPM_MOCK_CEILING,
    BPM_MOCK_FLOOR,
    HRV_MOCK_CEILING,
    HRV_MOCK_FLOOR
)

try:
    from bleak import BleakClient, BleakError
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False
    BleakClient = None
    BleakError = Exception

class HeartRateIngestor:
    """
    Asynchronous ingestor for cardiac data (BPM/HRV).
    Supports BLE sensor polling and Mock data fallback.
    """
    def __init__(self, *, allow_synthetic: bool = False):
        self.logger = logging.getLogger("Bio-Quant.Ingestor.HR")
        
        # Rolling buffer for stable RMSSD (Task 8.4.1)
        self.rr_buffer: List[float] = [] 
        
        # Aggregate statistics since last 5-min poll (Task 8.4.1)
        self.bpm_aggregate: List[int] = []
        self._last_reading_Snapshot: Optional[CardiacReading] = None
        self.is_running = True

        self.address = getattr(config, "HEART_RATE_SENSOR_ADDRESS", None)
        self.enabled = bool(config.CARDIAC_ENABLED)
        mock_requested = not self.address or self.address.upper() == "MOCK"
        self.is_mock = bool(self.enabled and allow_synthetic and mock_requested)
        self.is_available = bool(self.enabled and (self.is_mock or not mock_requested))
        
        if not self.enabled:
            self.logger.info("Cardiac ingestion disabled.")
        elif self.is_mock:
            self.logger.info("Initializing in MOCK mode (No BLE address configured).")
        elif not self.is_available:
            self.logger.warning(
                "Cardiac provider unavailable: a real BLE address is not configured."
            )
        else:
            self.logger.info(f"Initializing BLE Ingestor for address: {self.address}")

    @staticmethod
    def calculate_rmssd(rr_intervals: List[float]) -> float:
        """RMSSD = sqrt( mean( (deltas)^2 ) ). Standard HRV metric."""
        if len(rr_intervals) < 2:
            return 0.0
        diffs = [abs(rr_intervals[i+1] - rr_intervals[i]) for i in range(len(rr_intervals) - 1)]
        return math.sqrt(sum(d**2 for d in diffs) / len(diffs))

    async def fetch_latest(self, reset: bool = True) -> Optional[CardiacReading]:
        """
        Returns a CardiacReading enriched with aggregate statistics 
        since the last call. (Task 8.4.2)
        """
        if not self.is_available:
            return None
        if self.is_mock:
            for _ in range(5):
                self._last_reading_Snapshot = self._generate_mock_reading()
        
        if not self._last_reading_Snapshot:
            return None

        # Enrich with aggregates if we have tracked data
        if self.bpm_aggregate:
            self._last_reading_Snapshot.mean_bpm = int(statistics.mean(self.bpm_aggregate))
            self._last_reading_Snapshot.max_bpm = max(self.bpm_aggregate)
            
            # Signal quality based on variance (0.0 = chaotic/noise, 1.0 = stable)
            if len(self.bpm_aggregate) > 2:
                volatility = statistics.stdev(self.bpm_aggregate)
                self._last_reading_Snapshot.signal_quality = max(0.0, min(1.0, 1.0 - (volatility / CARDIAC_QUALITY_DIVISOR)))
            
            if reset:
                self.bpm_aggregate = []

        return self._last_reading_Snapshot

    def _generate_mock_reading(self) -> CardiacReading:
        """Simulates physiological resting data with slight noise."""
        # Task 8.4.4: Correlate mock BPM with metabolic state simulation
        hr = config.PATIENT_BPM_BASELINE + random.gauss(0, 2.0)
        rmssd = config.PATIENT_HRV_BASELINE + random.gauss(0, 1.5)
        
        # Ensure values stay in physiological bounds
        hr = max(BPM_MOCK_FLOOR, min(BPM_MOCK_CEILING, hr))
        rmssd = max(HRV_MOCK_FLOOR, min(HRV_MOCK_CEILING, rmssd))
        
        # Record to aggregate for self-consistency
        self.bpm_aggregate.append(int(hr))
        
        return CardiacReading(
            timestamp=datetime.now(timezone.utc),
            bpm=int(hr),
            hrv=round(rmssd, 2),
            source="simulation",
            provenance="synthetic",
        )

    async def start_ble_client(self):
        """
        Background task to connect to BLE sensor and update rr_buffer.
        Requires 'bleak' to be installed.
        """
        if not self.is_available or self.is_mock:
            return

        HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

        def notification_handler(sender, data):
            """Processes BLE GATT notifications for Heart Rate & RR-Intervals."""
            try:
                flags = data[0]
                hr_format_16bit = flags & 0x01
                hr = int.from_bytes(data[1:3], "little") if hr_format_16bit else data[1]
                
                # Health Check: Filter out physiological impossibilities
                if hr < 30 or hr > 220:
                    return

                # Parse RR intervals (Task 8.4.1)
                offset = 3 if hr_format_16bit else 2
                if flags & 0x08: offset += 2 # energy expended
                
                new_rr = []
                while offset + 1 < len(data):
                    raw = int.from_bytes(data[offset:offset+2], "little")
                    rr_ms = raw / 1024.0 * 1000.0
                    
                    # BIOLOGICAL FILTER: RR intervals > 300ms (200 BPM) and < 2000ms (30 BPM)
                    if 300 < rr_ms < 2000:
                        new_rr.append(rr_ms)
                    offset += 2
                
                self.rr_buffer.extend(new_rr)
                
                # Rolling circular buffer management
                if len(self.rr_buffer) > CARDIAC_WINDOW_SAMPLES:
                    self.rr_buffer = self.rr_buffer[-CARDIAC_WINDOW_SAMPLES:]
    
                rmssd = self.calculate_rmssd(self.rr_buffer)
                self.bpm_aggregate.append(int(hr)) # Track for 5-min summary
                
                self._last_reading_Snapshot = CardiacReading(
                    timestamp=datetime.now(timezone.utc),
                    bpm=int(hr),
                    hrv=round(rmssd, 2)
                )
            except Exception as e:
                self.logger.error(f"Failed to parse Heart Rate GATT data: {e}")

        retry_delay = config.BLE_RECONNECT_SECS
        max_delay = 300 # 5 minutes cap
        
        while True:
            if not self.is_running: break
            if not BLE_AVAILABLE:
                self.logger.error("Bleak not installed. BLE ingestion aborted.")
                break

            try:
                self.logger.info(f"Attempting BLE Connection: {self.address} (Retrying in {retry_delay}s if fails)...")
                async with BleakClient(self.address, timeout=20.0) as client:
                    self.logger.info(f"BLE Success: Connected to {self.address}")
                    retry_delay = config.BLE_RECONNECT_SECS # Reset on success
                    await client.start_notify(HR_UUID, notification_handler)
                    
                    while client.is_connected and self.is_running:
                        await asyncio.sleep(5)
                    
                    self.logger.warning("BLE Disconnected gracefully.")
            except Exception as e:
                # RECONNECTION EXPONENTIAL BACKOFF (Wave 3 Hardening)
                self.logger.error(f"BLE Connection failed: {e}. Next retry in {retry_delay}s")
                await asyncio.sleep(retry_delay)
                retry_delay = min(max_delay, retry_delay * 2) # Exponential backoff
