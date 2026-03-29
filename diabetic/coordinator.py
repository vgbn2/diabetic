import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional
from diabetic.config import config
from diabetic.registry import GlucoseReading, MetabolicSnapshot, MealEvent  # FIX V4/Bug1: MealEvent added
from diabetic import medical_constants
from diabetic.ingestion.nightscout import NightscoutClient
from diabetic.ingestion.cardiac import HeartRateIngestor
from diabetic.dsp.kalman import GlucoseFilter
from diabetic.dsp.signal_quality import SignalQuality
from diabetic.dsp.metabolic_math import MetabolicMath
from diabetic.ml_engine.predictor import GlucoseForecaster
from diabetic.ml_engine.twin import DigitalTwin
from diabetic.telegram_bot.decision_matrix import DecisionMatrix, CircuitBreaker, Alert
from diabetic.telegram_bot.handlers import TelegramNotifier, TelegramApp
from diabetic.ui.cli_hud import RealTimeHUD
from diabetic.ui.visualizer import MetabolicVisualizer
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
        self.hr_client = HeartRateIngestor()
        self.filter = GlucoseFilter()
        self.forecaster = GlucoseForecaster()
        self.alert_guard = DecisionMatrix()
        self.circuit_breaker = CircuitBreaker()
        self.notifier = TelegramNotifier()
        self.bot_app = TelegramApp(coordinator=self, audit_logger=self.audit) if config.TELEGRAM_TOKEN else None
        self.hud = RealTimeHUD()
        self.twin = DigitalTwin()
        self.visualizer = MetabolicVisualizer(output_dir="charts") 
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
        return self.last_meal if self.last_meal else None

    async def _process_reading(self, reading: GlucoseReading, is_backfill: bool = False):
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

        # 3. Treatment & Cardiac Ingestion
        # Polling both streams in parallel for speed (C3 resilient)
        try:
            # Polling both streams in parallel for speed (C3 resilient)
            tr_task = self.client.fetch_recent_treatments(count=10)
            hr_task = self.hr_client.fetch_latest()
            
            # results will be [(insulin, meal), cardiac]
            results = await asyncio.gather(tr_task, hr_task, return_exceptions=True)
            
            # 1. Unpack treatments
            tr_res = results[0]
            if not isinstance(tr_res, Exception) and isinstance(tr_res, tuple):
                ns_insulin, ns_meal = tr_res
                snapshot.last_insulin = ns_insulin
                snapshot.last_meal = self._active_meal(ns_meal)
            else:
                self.logger.warning(f"Nightscout treatment fetch failed: {tr_res}")
                snapshot.last_meal = self.last_meal # Manual fallback
                
            # 2. Unpack cardiac
            hr_res = results[1]
            if not isinstance(hr_res, Exception):
                snapshot.cardiac = hr_res
            else:
                self.logger.warning(f"Cardiac ingestion failed: {hr_res}")
                snapshot.cardiac = None
            
        except Exception as e:
            self.logger.warning(f"In-depth ingestion failed: {e}. Falling back to defaults.")
            snapshot.last_meal = self.last_meal # fallback to manual
            snapshot.cardiac = None

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
        if not is_backfill:
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

        hr_val = snapshot.bpm if snapshot.bpm else "N/A"
        hr_max = snapshot.max_bpm if snapshot.max_bpm else hr_val
        hrv_val = f"{snapshot.hrv:.1f}" if snapshot.hrv else "N/A"
        self.logger.info(f"DONE: {reading.value} -> Pred: {prediction_30m:.1f} | HR: {hr_val} (Pk: {hr_max}) | HRV: {hrv_val} | Snapshots: {len(self.snapshots)}")

        # 7. Digital Twin Regime Detection (every 6 hours)
        regime_trigger = int(360 / medical_constants.SAMPLING_INTERVAL_MINS)
        if len(self.snapshots) % regime_trigger == 0:
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
        if not is_backfill:
            task = asyncio.create_task(self.pusher.push_update({
                "snapshot": snapshot.model_dump(),
                "prediction": prediction_30m
            }))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

        # 10. Update Continuous Chart (Task 8.3.3)
        self.visualizer.update_continuous(self.snapshots)

    def _active_meal(self, ns_meal: Optional[MealEvent]) -> Optional[MealEvent]:
        """
        Arbitrate between Telegram-logged meal and Nightscout-logged meal.
        Rule: Prefer Telegram if it's within the 4-hour metabolic window.
        """
        if not self.last_meal and not ns_meal:
            return None
        now = datetime.now(timezone.utc)
        
        # Check if Telegram meal is still active (4h window)
        if self.last_meal:
            dt = (now - self.last_meal.timestamp).total_seconds() / 60.0
            if dt <= medical_constants.MEAL_WINDOW_MINS:
                return self.last_meal
                
        # Otherwise fallback to Nightscout
        return ns_meal

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

        task_hr = asyncio.create_task(self.hr_client.start_ble_client())
        self.background_tasks.add(task_hr)
        task_hr.add_done_callback(self.background_tasks.discard)

        if self.bot_app:
            self.logger.info("Initializing Telegram Bot callback loop...")
            task_bot = asyncio.create_task(self.bot_app.app.initialize())
            await task_bot
            task_bot = asyncio.create_task(self.bot_app.app.start())
            await task_bot
            task_bot = asyncio.create_task(self.bot_app.app.updater.start_polling())
            self.background_tasks.add(task_bot)

        # 0. Stateful Backfill (Task 8.2.2)
        last_ts = await self.audit.get_last_reading_timestamp()
        if last_ts:
            now = datetime.now(timezone.utc)
            gap_mins = (now - last_ts.replace(tzinfo=timezone.utc)).total_seconds() / 60
            if medical_constants.SAMPLING_INTERVAL_MINS < gap_mins < config.BACKFILL_MAX_HOURS * 60:
                self.logger.info(f"Detected {gap_mins:.1f} min gap. Starting backfill...")
                backfill_readings = await self.client.fetch_since(last_ts)
                if backfill_readings:
                    self.logger.info(f"Filling {len(backfill_readings)} missing readings...")
                    for r in backfill_readings:
                        await self._process_reading(r, is_backfill=True)
                    self.logger.info("Backfill complete. Kalman state stabilized.")

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

        history_count = int(60 / config.SAMPLING_INTERVAL_MINS)
        history = self.snapshots[-history_count:]
        if history:
            prediction_4h = self.twin.predict_4h_trajectory(history, self.last_meal)

            # FIX C2/V1: push the 4-hour curve to the frontend so it is not
            # silently discarded.
            task = asyncio.create_task(self.pusher.push_update({
                "type": "meal_forecast",
                "description": desc,
                "grams": grams,
                "gi_type": gi_type,
                "prediction_4h": prediction_4h.tolist()
            }))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

            # 11. Generate and Send Forecast Chart (Task 8.3.4)
            chart_path = self.visualizer.plot_forecast(
                history=[s.glucose.value for s in history],
                prediction=prediction_4h,
                meal_name=desc
            )
            await self.notifier.send_chart(chart_path, caption=f"Digital Twin Forecast: {desc} ({grams}g)")

            self.logger.info(
                f"4h trajectory computed ({len(prediction_4h)} points). "
                f"Peak: {prediction_4h.max():.1f} mmol/L at t={int(prediction_4h.argmax()*config.SAMPLING_INTERVAL_MINS)} min. "
                "Forecast chart pushed to Telegram."
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