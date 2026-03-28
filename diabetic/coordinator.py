import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional
from diabetic.config import config
from diabetic.registry import GlucoseReading, MetabolicSnapshot, MealEvent  # FIX V4/Bug1: MealEvent added
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

        # FIX T4: raised from 100 to medical_constants.SNAPSHOT_CAP (300)
        # so detect_regime() can satisfy its REGIME_MIN_SNAPSHOTS=200 threshold.
        self.snapshots: List[MetabolicSnapshot] = []

        # FIX V4: single source of truth for active Telegram-logged meal.
        # Nightscout-sourced meal lives in snapshot.last_meal only.
        self.last_meal: Optional[MealEvent] = None
        self.meal_window_start: Optional[datetime] = None

        # FIX T3: flag prevents auto_tune from firing multiple times per meal
        # window and survives polling gaps (replaces narrow 20-min window check).
        self.meal_tune_pending: bool = False

        self.is_running = False

    def _active_meal(self) -> Optional[MealEvent]:
        """
        FIX V4: Returns the authoritative active meal for prediction context.
        Prefers the Telegram-logged meal (self.last_meal) over the Nightscout
        treatment entry (snapshot.last_meal) when both are present, to avoid
        double-counting the same meal event from two sources.
        Returns None if no Telegram meal is active.
        """
        return self.last_meal if self.last_meal else None

    async def _process_reading(self, reading: GlucoseReading):
        """Standard processing pipeline for a single reading."""
        # Task 7.1.7: Log raw reading to cloud
        task = asyncio.create_task(self.audit.log_reading(reading))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

        # 1. Signal Quality Check
        # FIX C3: Log warning during startup when compression check is not yet
        # fully operational (requires >= 3 readings for recovery confirmation).
        history = [snapshot.glucose for snapshot in self.snapshots] + [reading]
        if len(history) < 3:
            self.logger.debug(
                f"Startup: only {len(history)} reading(s) — compression recovery check inactive until 3rd reading."
            )
        if SignalQuality.is_compression_low(history):
            self.logger.warning(f"Signal artifact detected at {reading.timestamp}. Skipping.")
            return

        # 1b. Freshness Check
        now = datetime.now(timezone.utc) if reading.timestamp.tzinfo else datetime.now()
        if (now - reading.timestamp).total_seconds() > medical_constants.STALE_DATA_TIMEOUT_SECS:
            self.logger.warning(f"Stale data ignored: {reading.timestamp} is too old.")
            return

        if self.snapshots:
            last_reading_time = self.snapshots[-1].glucose.timestamp
            dt = (now - last_reading_time).total_seconds()
            if dt > medical_constants.STALE_DATA_TIMEOUT_SECS:
                self.logger.warning(f"Metabolic data is STALE ({dt/60:.1f} mins old). Prediction accuracy reduced.")

        # 2. Smoothing (Kalman)
        snapshot = self.filter.update(reading)

        # 3. Treatment Ingestion (Insulin/Carbs from Nightscout)
        # NOTE: snapshot.last_meal is sourced from Nightscout treatments API.
        # For prediction context, use _active_meal() to prefer the
        # Telegram-logged meal when both are present (FIX V4).
        insulin, meal = await self.client.fetch_recent_treatments(count=10)
        snapshot.last_insulin = insulin
        snapshot.last_meal = meal

        # 4. Feature Extraction (Kinematics & Volatility)
        # Note: extract_kinematics returns (velocity, acceleration). Velocity
        # is discarded here because snapshot.velocity is already set correctly
        # by the Kalman filter. Only acceleration is needed at this call site.
        _, acceleration = MetabolicMath.extract_kinematics(self.snapshots + [snapshot])
        snapshot.acceleration = acceleration
        snapshot.atr_14 = MetabolicMath.calculate_atr(self.snapshots + [snapshot], period=14)

        # 5. Forecasting
        prediction_30m = self.forecaster.predict_30m(self.snapshots + [snapshot])
        # FIX V2: write prediction back to snapshot so auto_tune and downstream
        # consumers receive the actual forecast, not the default 0.0.
        snapshot.predict_30m = prediction_30m

        # 6. Alert Decision
        alert = self.alert_guard.evaluate(snapshot, prediction_30m)
        if alert and self.circuit_breaker.can_alert(alert.type, severity=alert.severity):
            await self._dispatch_alert(alert)
            task = asyncio.create_task(self.audit.log_event("ALERT_TRIGGERED", alert.model_dump(), level="WARNING"))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

        self.snapshots.append(snapshot)

        # FIX T4: cap raised to SNAPSHOT_CAP (300) so detect_regime() can
        # accumulate REGIME_MIN_SNAPSHOTS (200) readings before returning NORMAL.
        if len(self.snapshots) > medical_constants.SNAPSHOT_CAP:
            self.snapshots.pop(0)

        self.logger.info(f"DONE: {reading.value} -> Pred: {prediction_30m:.1f} | Snapshots: {len(self.snapshots)}")

        # 7. Digital Twin Regime Detection (every 6 hours)
        if len(self.snapshots) % 72 == 0:
            regime = self.twin.detect_regime(self.snapshots)
            self.logger.info(f"Metabolic Regime Detected: {regime}")

        # 8. Meal Window Auto-Tune
        # FIX T3: replaced narrow 230-250 min window with a flag-based trigger.
        # Original window was only 4 readings wide — one polling failure would
        # miss it permanently. Now fires once as soon as dt_meal >= 230 min,
        # regardless of how many readings occurred in that window.
        if self.last_meal and self.meal_window_start and self.meal_tune_pending:
            dt_meal = (reading.timestamp - self.meal_window_start).total_seconds() / 60.0
            if dt_meal >= 230:
                self.logger.info("Meal window closed. Triggering Twin Auto-Tune...")
                self.twin.auto_tune(reading.value, snapshot.predict_30m)
                self.last_meal = None
                self.meal_window_start = None
                self.meal_tune_pending = False  # consume the flag

        # 9. Push to Frontend
        task = asyncio.create_task(self.pusher.push_update({
            "snapshot": snapshot.model_dump(),
            "prediction": prediction_30m
        }))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    async def _dispatch_alert(self, alert: Alert):
        """Sends alert to Telegram and logger."""
        self.logger.error(f"ALERT DISPATCHED: {alert.type} - {alert.message}")
        await self.notifier.send_alert(alert)

    async def start_live_mode(self):
        """Polls Nightscout every N minutes and runs HUD."""
        self.is_running = True
        self.logger.info(f"Coordinator started in LIVE mode (Interval: {config.DATA_POLLING_INTERVAL}s)")

        task_hud = asyncio.create_task(self.hud.run_live(self))
        self.background_tasks.add(task_hud)
        task_hud.add_done_callback(self.background_tasks.discard)

        task_pusher = asyncio.create_task(self.pusher.heartbeat())
        self.background_tasks.add(task_pusher)
        task_pusher.add_done_callback(self.background_tasks.discard)

        if self.bot_app:
            self.logger.info("Initializing Telegram Bot callback loop...")
            task_bot = asyncio.create_task(self.bot_app.app.initialize())
            await task_bot
            task_bot = asyncio.create_task(self.bot_app.app.start())
            await task_bot
            task_bot = asyncio.create_task(self.bot_app.app.updater.start_polling())
            self.background_tasks.add(task_bot)

        while self.is_running:
            try:
                readings = await self.client.fetch_recent_glucose(count=1)
                if readings:
                    await self._process_reading(readings[0])
            except (ValueError, ConnectionError) as e:
                if "URL" in str(e) or "token" in str(e).lower() or "Unauthorized" in str(e):
                    self.logger.error(f"FATAL ERROR: {e}. Shutting down.")
                    self.is_running = False
                    raise SystemExit(1)
                self.logger.error(f"Polling failure: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")

            await asyncio.sleep(config.DATA_POLLING_INTERVAL)

    async def handle_meal_input(self, desc: str, grams: float, gi_type: str = "STARCH"):
        """Entry point for Telegram /meal command."""
        self.logger.info(f"Processing Meal: {desc} ({grams}g)")
        # FIX V4: self.last_meal is the Telegram-sourced meal (user-logged).
        # snapshot.last_meal (set in _process_reading) is Nightscout-sourced.
        # _active_meal() arbitrates between them in prediction context.
        self.last_meal = MealEvent(
            timestamp=datetime.now(timezone.utc),
            carbs=grams,
            gi_type=gi_type
        )
        self.meal_window_start = datetime.now(timezone.utc)
        # FIX T3: arm the flag so auto_tune fires once after 230 min
        self.meal_tune_pending = True

        history = self.snapshots[-12:]  # Last hour
        if history:
            prediction_4h = self.twin.predict_4h_trajectory(history, self.last_meal)

            # FIX C2/V1: push the 4-hour curve to the frontend so it is not
            # silently discarded. Visualizer rendering remains deferred.
            task = asyncio.create_task(self.pusher.push_update({
                "type": "meal_forecast",
                "description": desc,
                "grams": grams,
                "gi_type": gi_type,
                "prediction_4h": prediction_4h.tolist()
            }))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

            self.logger.info(
                f"4h trajectory computed ({len(prediction_4h)} points). "
                f"Peak: {prediction_4h.max():.1f} mmol/L at t={int(prediction_4h.argmax()*5)} min. "
                f"Pushed to frontend. Visualizer rendering DEFERRED."
            )

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