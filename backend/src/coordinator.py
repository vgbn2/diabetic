import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

from backend.src.config import config
from backend.src.registry import GlucoseReading, MetabolicSnapshot
from backend.src.ingestion.nightscout_client import NightscoutClient
from backend.src.smoothing.kalman_filter import GlucoseFilter
from backend.src.smoothing.signal_quality import SignalQuality
from backend.src.features.metabolic_math import MetabolicMath
from backend.src.forecasting.glucose_predictor import GlucoseForecaster
from backend.src.alert_engine.decision_matrix import DecisionMatrix, CircuitBreaker, Alert
from backend.src.alert_engine.telegram_notifier import TelegramNotifier
from backend.src.ui.cli_hud import RealTimeHUD
from backend.src.utils.audit_logger import AuditLogger
from backend.src.utils.stateless_push import StatelessPush

class Coordinator:
    """
    The Orchestrator. Connects ingestion, smoothing, prediction, and alerting.
    """
    def __init__(self):
        self.client = NightscoutClient()
        self.filter = GlucoseFilter()
        self.forecaster = GlucoseForecaster()
        self.alert_guard = DecisionMatrix()
        self.circuit_breaker = CircuitBreaker()
        self.notifier = TelegramNotifier()
        self.hud = RealTimeHUD()
        self.audit = AuditLogger()
        self.pusher = StatelessPush()
        
        self.snapshots: List[MetabolicSnapshot] = []
        self.is_running = False
        
        logging.basicConfig(level=config.LOG_LEVEL)
        self.logger = logging.getLogger("Bio-Quant.Coordinator")

    async def _process_reading(self, reading: GlucoseReading):
        """Standard processing pipeline for a single reading."""
        # 1. Signal Quality Check
        history = [s.glucose for s in self.snapshots] + [reading]
        if SignalQuality.is_compression_low(history):
            self.logger.warning(f"⚠️ Signal artifact detected at {reading.timestamp}. Skipping.")
            return

        # 1b. Freshness Check (Data must be within last 15 mins)
        now = datetime.now(timezone.utc) if reading.timestamp.tzinfo else datetime.now()
        if (now - reading.timestamp).total_seconds() > 900:
            self.logger.warning(f"⌛ Stale data ignored: {reading.timestamp} is too old.")
            return

        # 2. Smoothing (Kalman)
        snapshot = self.filter.update(reading)
        
        # 3. Feature Extraction (Kinematics)
        velocity, acceleration = MetabolicMath.extract_kinematics(self.snapshots + [snapshot])
        snapshot.velocity = velocity
        snapshot.acceleration = acceleration
        
        # 4. Forecasting (XGBoost/Kinematic)
        prediction_30m = self.forecaster.predict_30m(self.snapshots + [snapshot])
        
        # 5. Alert Decision
        alert = self.alert_guard.evaluate(snapshot, prediction_30m)
        if alert and self.circuit_breaker.can_alert(alert.type):
            await self._dispatch_alert(alert)
            await self.audit.log_event("ALERT_TRIGGERED", alert.dict(), level="WARNING")
            
        self.snapshots.append(snapshot)
        # Keep window of 100 snapshots to prevent memory leak
        if len(self.snapshots) > 100:
            self.snapshots.pop(0)

        self.logger.info(f"DONE: {reading.value} -> Pred: {prediction_30m:.1f} | Snapshots: {len(self.snapshots)}")
        
        # 6. Push to Frontend (Stateless Push)
        asyncio.create_task(self.pusher.push_update({
            "snapshot": snapshot.dict(),
            "prediction": prediction_30m
        }))

    async def _dispatch_alert(self, alert: Alert):
        """Sends alert to Telegram and logger."""
        self.logger.error(f"🚨 ALERT DISPATCHED: {alert.type} - {alert.message}")
        await self.notifier.send_alert(alert)

    async def start_live_mode(self):
        """Polls Nightscout every N minutes and runs HUD."""
        self.is_running = True
        self.logger.info(f"🚀 Coordinator started in LIVE mode (Interval: {config.DATA_POLLING_INTERVAL}s)")
        
        # Run HUD and Heartbeat in parallel
        asyncio.create_task(self.hud.run_live(self))
        asyncio.create_task(self.pusher.heartbeat())
        
        while self.is_running:
            try:
                readings = await self.client.fetch_recent_glucose(count=1)
                if readings:
                    await self._process_reading(readings[0])
            except Exception as e:
                self.logger.error(f"Polling failure: {e}")
                
            await asyncio.sleep(config.DATA_POLLING_INTERVAL)

    def stop(self):
        self.is_running = False

if __name__ == "__main__":
    c = Coordinator()
    # For testing, we won't loop indefinitely
    asyncio.run(c.start_live_mode())
