import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional
from diabetic.config import config
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic import medical_constants
from diabetic.ingestion.nightscout import NightscoutClient
from diabetic.dsp.kalman import GlucoseFilter
from diabetic.dsp.signal_quality import SignalQuality
from diabetic.dsp.metabolic_math import MetabolicMath
from diabetic.ml_engine.predictor import GlucoseForecaster
from diabetic.ml_engine.twin import DigitalTwin
from diabetic.telegram_bot.decision_matrix import DecisionMatrix, CircuitBreaker, Alert
from diabetic.telegram_bot.handlers import TelegramNotifier, TelegramApp
from diabetic.ui.cli_hud import RealTimeHUD
# from diabetic.ui.visualizer import MetabolicVisualizer [DEFERRED]
from diabetic.utils.audit_logger import AuditLogger
from diabetic.utils.stateless_push import StatelessPush

class Coordinator:
    """
    The Orchestrator. Connects ingestion, smoothing, prediction, and alerting.
    """
    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        logging.basicConfig(level=config.LOG_LEVEL)
        self.logger = logging.getLogger("Bio-Quant.Coordinator")
        
        # Concurrency management
        self.background_tasks = set()

        self.audit = audit_logger or AuditLogger()
        
        # Task 7.1.7: Initialize with config baseline
        self.client = NightscoutClient()
        self.filter = GlucoseFilter()
        self.forecaster = GlucoseForecaster()
        self.alert_guard = DecisionMatrix()
        self.circuit_breaker = CircuitBreaker()
        self.notifier = TelegramNotifier()
        self.bot_app = TelegramApp(coordinator=self, audit_logger=self.audit) if config.TELEGRAM_TOKEN else None
        self.hud = RealTimeHUD()
        self.twin = DigitalTwin()
        # self.visualizer = MetabolicVisualizer() [DEFERRED]
        self.pusher = StatelessPush()
        
        self.snapshots: List[MetabolicSnapshot] = []
        self.last_meal: Optional[MealEvent] = None
        self.meal_window_start: Optional[datetime] = None
        self.is_running = False

    async def _process_reading(self, reading: GlucoseReading):
        """Standard processing pipeline for a single reading."""
        # Task 7.1.7: Log raw reading to cloud
        task = asyncio.create_task(self.audit.log_reading(reading))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        
        # 1. Signal Quality Check
        history = [snapshot.glucose for snapshot in self.snapshots] + [reading]
        if SignalQuality.is_compression_low(history):
            self.logger.warning(f"⚠️ Signal artifact detected at {reading.timestamp}. Skipping.")
            return

        # 1b. Freshness Check (Data must be within last 15 mins)
        now = datetime.now(timezone.utc) if reading.timestamp.tzinfo else datetime.now()
        if (now - reading.timestamp).total_seconds() > medical_constants.STALE_DATA_TIMEOUT_SECS:
            self.logger.warning(f"⌛ Stale data ignored: {reading.timestamp} is too old.")
            return

        # Check for staleness of *last processed* data point
        if self.snapshots:
            last_reading_time = self.snapshots[-1].glucose.timestamp
            dt = (now - last_reading_time).total_seconds()
            if dt > medical_constants.STALE_DATA_TIMEOUT_SECS:
                self.logger.warning(f"Metabolic data is STALE ({dt/60:.1f} mins old). Prediction accuracy reduced.")

        # 2. Smoothing (Kalman)
        snapshot = self.filter.update(reading)
        
        # 3. Treatment Ingestion (Insulin/Carbs)
        # Fetch latest treatments to provide context for prediction and alerting.
        insulin, meal = await self.client.fetch_recent_treatments(count=10)
        snapshot.last_insulin = insulin
        snapshot.last_meal = meal
        
        # 4. Feature Extraction (Kinematics & Volatility)
        _, acceleration = MetabolicMath.extract_kinematics(self.snapshots + [snapshot])
        snapshot.acceleration = acceleration
        snapshot.atr_14 = MetabolicMath.calculate_atr(self.snapshots + [snapshot], period=14)
        
        # 5. Forecasting (Weighted Kinematic)
        prediction_30m = self.forecaster.predict_30m(self.snapshots + [snapshot])
        
        # 5. Alert Decision
        alert = self.alert_guard.evaluate(snapshot, prediction_30m)
        if alert and self.circuit_breaker.can_alert(alert.type, severity=alert.severity):
            await self._dispatch_alert(alert)
            task = asyncio.create_task(self.audit.log_event("ALERT_TRIGGERED", alert.model_dump(), level="WARNING"))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)
            
        self.snapshots.append(snapshot)
        # Keep window of 100 snapshots to prevent memory leak
        if len(self.snapshots) > 100:
            self.snapshots.pop(0)

        self.logger.info(f"DONE: {reading.value} -> Pred: {prediction_30m:.1f} | Snapshots: {len(self.snapshots)}")

        # 6. Digital Twin Regime Detection & Tuning (Phase 8)
        if len(self.snapshots) % 72 == 0: # Every 6 hours
             regime = self.twin.detect_regime(self.snapshots)
             self.logger.info(f"Metabolic Regime Detected: {regime}")

        # 7. Check for Meal Window Closure (4 hours)
        if self.last_meal and self.meal_window_start:
            dt_meal = (reading.timestamp - self.meal_window_start).total_seconds() / 60.0
            if 230 < dt_meal < 250: # Close to 4 hours
                # compare actual vs twin prediction for tuning
                # This is a simplified tuning trigger
                self.logger.info("Meal window closed. Triggering Twin Auto-Tune...")
                self.twin.auto_tune(reading.value, snapshot.predict_30m)
                self.last_meal = None
                self.meal_window_start = None

        # 8. Push to Frontend (Stateless Push)
        task = asyncio.create_task(self.pusher.push_update({
            "snapshot": snapshot.model_dump(),
            "prediction": prediction_30m
        }))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def _dispatch_alert(self, alert: Alert):
        """Sends alert to Telegram and logger."""
        self.logger.error(f"🚨 ALERT DISPATCHED: {alert.type} - {alert.message}")
        await self.notifier.send_alert(alert)

    async def start_live_mode(self):
        """Polls Nightscout every N minutes and runs HUD."""
        self.is_running = True
        self.logger.info(f"🚀 Coordinator started in LIVE mode (Interval: {config.DATA_POLLING_INTERVAL}s)")
        
        # Run HUD and Heartbeat in parallel
        task_hud = asyncio.create_task(self.hud.run_live(self))
        self.background_tasks.add(task_hud)
        task_hud.add_done_callback(self.background_tasks.discard)

        task_pusher = asyncio.create_task(self.pusher.heartbeat())
        self.background_tasks.add(task_pusher)
        task_pusher.add_done_callback(self.background_tasks.discard)

        # Start Telegram Bot if token provided
        if self.bot_app:
            self.logger.info("Initializing Telegram Bot callback loop...")
            # We use a wrapper to run the bot's polling loop
            task_bot = asyncio.create_task(self.bot_app.app.initialize())
            await task_bot
            task_bot = asyncio.create_task(self.bot_app.app.start())
            await task_bot
            task_bot = asyncio.create_task(self.bot_app.app.updater.start_polling())
            self.background_tasks.add(task_bot)
            # No discard callback yet, as we want to handle shutdown later
        
        while self.is_running:
            try:
                readings = await self.client.fetch_recent_glucose(count=1)
                if readings:
                    await self._process_reading(readings[0])
            except (ValueError, ConnectionError) as e:
                # Fatal Configuration or Network Errors
                if "URL" in str(e) or "token" in str(e).lower() or "Unauthorized" in str(e):
                    self.logger.error(f"FATAL ERROR: {e}. Shutting down engine to prevent loops.")
                    self.is_running = False
                    raise SystemExit(1)
                self.logger.error(f"Polling failure: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")
            
            await asyncio.sleep(config.DATA_POLLING_INTERVAL)

    async def handle_meal_input(self, desc: str, grams: float, gi_type: str = "STARCH"):
        """Entry point for Telegram /meal command."""
        self.logger.info(f"Processing Meal: {desc} ({grams}g)")
        self.last_meal = MealEvent(
            timestamp=datetime.now(),
            carbs=grams,
            gi_type=gi_type
        )
        self.meal_window_start = datetime.now()
        
        # 1. Run simulation forward
        history = self.snapshots[-12:] # Last hour
        if history:
            prediction_4h = self.twin.predict_4h_trajectory(history, self.last_meal)
            
            # 2. [DEFERRED] Generate and Push Chart
            # hist_vals = [s.filtered_value for s in history]
            # chart_path = self.visualizer.plot_forecast(hist_vals, prediction_4h, desc)
            
            # if self.notifier:
            #      await self.notifier.send_chart(...)
            
            # if self.notifier:
            #      await self.notifier.send_chart(...)
            
            self.logger.info("Simulation run locally. Visualizer DEFERRED.")
            
        if self.background_tasks:
            self.logger.info(f"Awaiting {len(self.background_tasks)} background tasks before shutdown...")
            await asyncio.wait(self.background_tasks, timeout=5.0)

    async def stop(self):
        """Graceful shutdown of all services."""
        self.is_running = False
        
        if self.bot_app:
            self.logger.info("Stopping Telegram Bot...")
            await self.bot_app.app.updater.stop()
            await self.bot_app.app.stop()
            await self.bot_app.app.shutdown()

        if self.background_tasks:
            self.logger.info(f"Awaiting {len(self.background_tasks)} background tasks before shutdown...")
            await asyncio.wait(self.background_tasks, timeout=5.0)

if __name__ == "__main__":
    c = Coordinator()
    asyncio.run(c.start_live_mode())
