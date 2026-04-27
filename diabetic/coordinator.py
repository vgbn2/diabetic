import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
from typing import List, Optional
from diabetic.config import config
from diabetic.registry import GlucoseReading, MetabolicSnapshot, MealEvent
from diabetic import medical_constants
from diabetic.ingestion.nightscout import NightscoutClient
from diabetic.ingestion.mongo import MongoDBClient
from diabetic.ingestion.cardiac import HeartRateIngestor
from diabetic.ingestion.weather import WeatherIngestor
from diabetic.dsp.kalman import GlucoseFilter
from diabetic.dsp.signal_quality import SignalQuality
from diabetic.dsp.metabolic_math import MetabolicMath
from diabetic.dsp.context_classifier import classify_context
from diabetic.ml_engine.twin import DigitalTwin
from diabetic.ml_engine.inference import MetabolicInferenceRunner
from diabetic.telegram_bot.decision_matrix import DecisionMatrix, CircuitBreaker, Alert
from diabetic.telegram_bot.handlers import TelegramNotifier, TelegramApp
from diabetic.ui.cli_hud import RealTimeHUD
from diabetic.ui.visualizer import MetabolicVisualizer
from diabetic.utils.stateless_push import StatelessPush
from diabetic.utils.audit_logger import AuditLogger
from diabetic.utils.data_factory import TacticalForecaster, compute_confidence_index
from diabetic.storage.engine import init_db, close_db as close_storage_db
from diabetic.storage.vessel_registry import VesselRegistry
from diabetic.ml_engine.oracle import BasalOracle
try:
    from diabetic.ml_engine.metabolic_palace import MetabolicPalace
except ImportError:
    MetabolicPalace = None

# =============================================================================
# 🏗️ [ORCHESTRATION ARCHITECTURE]
# =Focus: System Initialization, State Tracking, and Registry Managed
# =============================================================================
class Coordinator:
    """
    The Orchestrator. Connects ingestion, smoothing, prediction, and alerting.
    """
    @classmethod
    async def create(cls, audit_logger: Optional['AuditLogger'] = None) -> "Coordinator":
        self = cls.__new__(cls)
        self.logger = logging.getLogger("Bio-Quant.Coordinator")

        self.background_tasks = set()
        self.audit = audit_logger or AuditLogger()
        self.client = NightscoutClient()
        self.mongo = MongoDBClient()
        self.hr_client = HeartRateIngestor()
        self.weather_client = WeatherIngestor()
        self.filter = GlucoseFilter()

        self.neural_runner = MetabolicInferenceRunner()

        self.alert_guard = DecisionMatrix()
        self.circuit_breaker = CircuitBreaker()
        self.notifier = TelegramNotifier()
        self.bot_app = TelegramApp(coordinator=self, audit_logger=self.audit) if config.TELEGRAM_TOKEN else None
        self.hud = RealTimeHUD()
        self.twin = DigitalTwin(
            weight_kg=config.PATIENT_WEIGHT_KG,
            height_cm=config.PATIENT_HEIGHT_CM,
            gender=config.PATIENT_GENDER,
            diabetes_type=config.PATIENT_DIABETES_TYPE,
            age=config.PATIENT_AGE,
            ethnicity=config.PATIENT_ETHNICITY,
            nationality=config.PATIENT_NATIONALITY,
            religion=config.PATIENT_RELIGION,
            diagnosis_year=config.PATIENT_DIAGNOSIS_YEAR,
            activity_level=config.PATIENT_ACTIVITY_LEVEL,
            fructosamin=config.PATIENT_FRUCTOSAMIN,
            is_inflamed=config.PATIENT_INFLAMMATORY_MARKER,
            cycle_start=config.PATIENT_CYCLE_START
        )
        self.visualizer = MetabolicVisualizer(output_dir="charts")
        self.pusher = StatelessPush()
        try:
            self.palace = MetabolicPalace()
        except Exception as e:
            self.logger.warning(f"MetabolicPalace initialization failed: {e}. Semantic memory disabled.")
            self.palace = None

        # [G1] Wire VesselRegistry — multi-tenant bio-trait persistence
        self.vessel_registry = VesselRegistry()
        await init_db()  # idempotent: creates tables if not present
        await self.vessel_registry.migrate_from_env()  # one-time .env -> SQL migration
        self.logger.info("[G1] VesselRegistry initialized and traits loaded for user.")

        # [C2] Revive BasalOracle — harmonic circadian rhythm predictor
        self.oracle = BasalOracle(history_days=3)
        self.logger.info("[C2] BasalOracle instantiated. Will fit after 24h of data accumulation.")

        self.snapshots: List[MetabolicSnapshot] = []
        self.regime_step_count = 0  # FIX C1: Persistent counter independent of buffer length

        self.last_meal: Optional[MealEvent] = None
        self.meal_window_start: Optional[datetime] = None
        self.meal_tune_pending: bool = False
        self.actual_meal_peak: float = 0.0  # FIX C2: Tracks Highest Observed Glucose value during meal window

        # FIX L1: store the twin's predicted peak at meal-log time so auto_tune
        # compares actual glucose against the real 4h meal prediction, not
        # snapshot.predict_30m which is a short-horizon kinematic value.
        self.pending_meal_forecast_peak: Optional[float] = None

        self.is_running = False
        return self

# =============================================================================
# 📡 [DATA SYNTHESIS PIPELINE]
# =Focus: Signal Quality, Smoothing (Kalman), and Multi-Stream Ingestion
# =============================================================================
    async def _process_reading(self, reading: GlucoseReading, is_backfill: bool = False):
        """Standard processing pipeline for a single reading."""
        self.regime_step_count += 1
        
        task = asyncio.create_task(self.audit.log_reading(reading))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

        # 1. Signal Quality Check
        history = [snapshot.glucose for snapshot in self.snapshots] + [reading]
        if len(history) < 3:#why 3?comment when read this
            self.logger.debug(
                f"Startup: only {len(history)} reading(s) — compression recovery check inactive until 3rd reading."
            )
        if SignalQuality.is_compression_low(history):
            self.logger.warning(f"Signal artifact detected at {reading.timestamp}. Skipping.")
            return

        # 1b. Freshness Check
        # FIX C1: always use UTC-aware now; normalise incoming timestamp if naive.
        now = datetime.now(timezone.utc)
        reading_ts = reading.timestamp
        if reading_ts.tzinfo is None:
            reading_ts = reading_ts.replace(tzinfo=timezone.utc)
        if (now - reading_ts).total_seconds() > medical_constants.STALE_DATA_TIMEOUT_SECS:
            self.logger.warning(f"Stale data ignored: {reading.timestamp} is too old.")
            return

        if self.snapshots:
            last_reading_time = self.snapshots[-1].glucose.timestamp
            if last_reading_time.tzinfo is None:
                last_reading_time = last_reading_time.replace(tzinfo=timezone.utc)
            dt = (now - last_reading_time).total_seconds()
            if dt > medical_constants.STALE_DATA_TIMEOUT_SECS:
                self.logger.warning(f"Metabolic data is STALE ({dt/60:.1f} mins old). Prediction accuracy reduced.")

        # 2. Smoothing (Kalman)
        snapshot = self.filter.update(reading)

        # 3. Treatment & Cardiac Ingestion
        try:
            tr_task = self.client.fetch_recent_treatments(count=10)
            hr_task = self.hr_client.fetch_latest()
            we_task = self.weather_client.fetch_current(config.LATITUDE, config.LONGITUDE)
            results = await asyncio.gather(tr_task, hr_task, we_task, return_exceptions=True)

            tr_res = results[0]
            if not isinstance(tr_res, Exception) and isinstance(tr_res, tuple):
                ns_insulin, ns_meal = tr_res
                snapshot.last_insulin = ns_insulin
                snapshot.last_meal = self._active_meal(ns_meal)
            else:
                self.logger.warning(f"Nightscout treatment fetch failed: {tr_res}")
                snapshot.last_meal = self.last_meal

            hr_res = results[1]
            if not isinstance(hr_res, Exception):
                snapshot.cardiac = hr_res
            else:
                self.logger.warning(f"Cardiac ingestion failed: {hr_res}")
                snapshot.cardiac = None
            
            we_res = results[2]
            if not isinstance(we_res, Exception):
                snapshot.environment = we_res
            else:
                self.logger.warning(f"Weather ingestion failed: {we_res}")
                snapshot.environment = None

        except Exception as e:
            self.logger.warning(f"In-depth ingestion failed: {e}. Falling back to defaults.")
            snapshot.last_meal = self.last_meal
            snapshot.cardiac = None

        # 3b. Estimate Active Carbs/Insulin (COB/IOB) for Oracle Filtering
        # Fix C2: Physiological decay — COB uses Twin's log-normal absorption curve;
        # IOB uses Twin's S-curve get_iob_fraction. Both replace the old linear (1 - t/240).
        if snapshot.last_meal and snapshot.last_meal.carbs is not None:
            dt_m = (now - snapshot.last_meal.timestamp).total_seconds() / 60.0
            gi_type = snapshot.last_meal.gi_type or "STARCH"
            # Derive COB fraction: ratio of integral still remaining ahead of dt_m
            # vs the full 240-min integral from the Twin's log-normal curve.
            full_curve = self.twin.simulate_carb_impact(
                snapshot.last_meal.carbs, gi_type=gi_type, resolution_mins=1.0
            )
            total_area = float(full_curve.sum())
            if total_area > 0.0:
                elapsed_idx = min(int(dt_m), len(full_curve) - 1)
                remaining_area = float(full_curve[elapsed_idx:].sum())
                cob_fraction = remaining_area / total_area
            else:
                cob_fraction = max(0.0, 1.0 - dt_m / 240.0)  # safe fallback
            snapshot.active_carbs = max(0.0, snapshot.last_meal.carbs * cob_fraction)

        if snapshot.last_insulin and snapshot.last_insulin.units is not None:
            dt_i = (now - snapshot.last_insulin.timestamp).total_seconds() / 60.0
            snapshot.active_insulin = max(0.0, snapshot.last_insulin.units * self.twin.get_iob_fraction(dt_i))

        # 4. Feature Extraction
        snapshot.atr_14 = MetabolicMath.calculate_atr(self.snapshots + [snapshot], period=14)

        # 5. Forecasting
        # Strategy: Use Multi-Task Neural Engine as primary, fallback to kinematics if warming up.
        neural_res = self.neural_runner.run_inference_on_snapshots(self.snapshots + [snapshot])
        if neural_res:
            prediction_30m = neural_res["glucose"]
            snapshot.predict_30m = prediction_30m
            snapshot.predicted_hr = neural_res["heart_rate"]
            self.logger.info(f"NEURAL_BRAIN: Pred Glu={prediction_30m:.1f} | Pred HR={snapshot.predicted_hr:.1f}")
        else:
            # Wave 2 Hardening: Kinematic Fallback
            # Instead of a flat current value, we project using current velocity over 30m.
            # prediction = current + (velocity * 30)
            velocity, _ = MetabolicMath.extract_kinematics(self.snapshots + [snapshot])
            prediction_30m = snapshot.glucose.value + (velocity * 30.0)
            snapshot.predict_30m = prediction_30m
            self.logger.warning(f"NEURAL_BRAIN: Inference failed. Using Kinematic Projection: {prediction_30m:.1f}")

        # 5b. Tactical Forecaster — 15/30/60m regression-based horizons
        # [G1] VesselRegistry is now live; traits are available via self.vessel_registry
        raw_history: list[tuple[datetime, float]] = [
            (s.glucose.timestamp, s.glucose.value)
            for s in (self.snapshots + [snapshot])[-12:]  # last ~60 mins of data
        ]
        forecaster = TacticalForecaster()
        tactical = forecaster.compute(raw_history)
        snapshot.predict_15m = tactical["p15m"]
        # predict_30m already set by neural/kinematic above; tactical 30m available as secondary
        snapshot.predict_60m = tactical["p60m"]
        snapshot.velocity_score = tactical["velocity"]
        snapshot.confidence_index = compute_confidence_index(raw_history)

        # [C2] Log oracle's expected basal for observability
        if self.oracle.params is not None:
            expected_basal = self.oracle.get_expected_basal(
                target_time=datetime.now(timezone.utc),
                reference_start=self.snapshots[0].glucose.timestamp if self.snapshots else datetime.now(timezone.utc)
            )
            self.logger.debug(f"[Oracle] Expected basal at this time: {expected_basal:.2f} mmol/L")

        # 5c. Context Classification
        snapshot.activity_label = classify_context(snapshot).value

        # 6. Alert Decision
        if not is_backfill:
            alert = await self.alert_guard.evaluate(snapshot, prediction_30m, self.audit)
            if alert and self.circuit_breaker.can_alert(alert.type, severity=alert.severity):
                await self._dispatch_alert(alert)
                task = asyncio.create_task(self.audit.log_event("ALERT_TRIGGERED", alert.model_dump(), level="WARNING"))
                self.background_tasks.add(task)
                task.add_done_callback(self.background_tasks.discard)

        self.snapshots.append(snapshot)

        # 6b. Semantic Memory (Layer 4/5)
        # Trapping anomalies: e.g., high prediction, high value, or HR distress
        if not is_backfill:
            if prediction_30m > 16.0 or reading.value > 16.0 or (snapshot.bpm and snapshot.bpm > 110):
                if self.palace is not None:
                    task = asyncio.create_task(asyncio.to_thread(
                        self.palace.remember_snapshot, snapshot.model_dump(), room="l4_anomaly_audit"
                    ))
                    self.background_tasks.add(task)
                    task.add_done_callback(self.background_tasks.discard)

        if len(self.snapshots) > medical_constants.SNAPSHOT_CAP:
            self.snapshots.pop(0)

        hr_val = snapshot.bpm if snapshot.bpm else "N/A"
        hr_max = snapshot.max_bpm if snapshot.max_bpm else hr_val
        hrv_val = f"{snapshot.hrv:.1f}" if snapshot.hrv else "N/A"
        self.logger.info(f"DONE: {reading.value} -> Pred: {prediction_30m:.1f} | HR: {hr_val} (Pk: {hr_max}) | HRV: {hrv_val} | Snapshots: {len(self.snapshots)}")

        # 7. Digital Twin Regime Detection (every 6 hours)
        regime_trigger = int(360 / medical_constants.SAMPLING_INTERVAL_MINS)
        if self.regime_step_count % regime_trigger == 0:
            regime = self.twin.detect_regime(self.snapshots)
            self.logger.info(f"Metabolic Regime Detected: {regime} (Step: {self.regime_step_count})")

        # 8. Meal Window Auto-Tune
        # FIX C2: track actual peak and compare against predicted forecast peak.
        if self.last_meal and self.meal_window_start and self.meal_tune_pending:
            self.actual_meal_peak = max(self.actual_meal_peak, reading.value)
            
            dt_meal = (reading.timestamp - self.meal_window_start).total_seconds() / 60.0
            if dt_meal >= 230:
                self.logger.info(f"Meal window closed (dt={dt_meal:.1f}m). Triggering Twin Auto-Tune via observed peak: {self.actual_meal_peak:.1f}...")
                if self.pending_meal_forecast_peak and self.pending_meal_forecast_peak > 0.1:
                    # Logic: use the ACTUAL Highest glucose reached vs the PREDICTED Highest glucose.
                    self.twin.auto_tune(self.actual_meal_peak, self.pending_meal_forecast_peak)
                else:
                    self.logger.warning("No stored meal forecast peak — auto_tune skipped.")
                
                # Reset window
                self.last_meal = None
                self.meal_window_start = None
                self.meal_tune_pending = False
                self.pending_meal_forecast_peak = None
                self.actual_meal_peak = 0.0

        # 9. Push to Frontend
        if not is_backfill:
            task = asyncio.create_task(self.pusher.push_update({
                "snapshot": snapshot.model_dump(),
                "prediction": prediction_30m
            }))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

        # 10. Update Continuous Chart
        self.visualizer.update_continuous(self.snapshots)

# =============================================================================
# 🎮 [INTERACTION & INTERFACE]
# =Focus: Alert Dispatching, Meal Logging, and User Feedback
# =============================================================================
    def _active_meal(self, ns_meal: Optional[MealEvent]) -> Optional[MealEvent]:
        """
        Arbitrate between Telegram-logged meal and Nightscout-logged meal.
        Rule: Prefer Telegram if it's within the 4-hour metabolic window.
        """
        if not self.last_meal and not ns_meal:
            return None
        now = datetime.now(timezone.utc)

        if self.last_meal:
            dt = (now - self.last_meal.timestamp).total_seconds() / 60.0
            if dt <= medical_constants.MEAL_WINDOW_MINS:
                return self.last_meal

        return ns_meal

    async def _dispatch_alert(self, alert: Alert):
        """Sends alert to Telegram and logger."""
        self.logger.error(f"ALERT DISPATCHED: {alert.type} - {alert.message}")
        await self.notifier.send_alert(alert)

# =============================================================================
# ⚙️ [MAINTENANCE & REGIONAL SYNC]
# =Focus: Automated Daily Sync, Retention Policy, and Timezone Discovery
# =============================================================================
    async def _maintenance_loop(self):
        """
        Automated Daily Maintenance (Task III). 
        Staggered based on USER_TIMEZONE for load distribution.
        """
        tz = ZoneInfo(config.USER_TIMEZONE)
        self.logger.info(f"Regional Maintenance Loop active. Local Timezone: {config.USER_TIMEZONE}")
        
        while self.is_running:
            now = datetime.now(tz)
            
            # Target is the next occurrence of config.MAINTENANCE_LOCAL_HOUR
            target = now.replace(hour=config.MAINTENANCE_LOCAL_HOUR, minute=0, second=0, microsecond=0)
            
            if now >= target:
                target += timedelta(days=1)
                
            sleep_secs = (target - now).total_seconds()
            self.logger.info(f"REGIONAL_SYNC_SCHEDULED: Next maintenance window in {sleep_secs/3600:.1f} hours (Local: {target.strftime('%H:%M')})")
            
            await asyncio.sleep(sleep_secs)
            
            # Maintenance Cycle
            try:
                self.logger.warning("Starting Regional Maintenance Cycle...")
                await self.audit.log_admin_action("AUTO_MAINTENANCE_START", {"local_time": str(target)})
                
                # 1. Incremental Sync
                await self.mongo.sync_current_period()
                
                # 2. Retention Policy Cleanup
                await self.mongo.run_retention_cleanup(days=180)
                
                await self.audit.log_admin_action("AUTO_MAINTENANCE_COMPLETE", {"local_time": str(target)})
                self.logger.info("Regional Maintenance Cycle complete.")
            except Exception as e:
                self.logger.error(f"Maintenance cycle failed: {e}")
                await self.audit.log_admin_action("AUTO_MAINTENANCE_FAILED", {"error": str(e)})
            
            # Ensure we don't double-trigger if maintenance is extremely fast
            await asyncio.sleep(60)

    async def _refit_oracle_loop(self):
        """[C2] Fits the BasalOracle every 24h on accumulated snapshot history."""
        self.logger.info("[C2] BasalOracle re-fit loop started. First fit in 24h.")
        while self.is_running:
            await asyncio.sleep(24 * 3600)  # 24 hours
            if len(self.snapshots) >= 2:
                try:
                    self.oracle.fit(self.snapshots)
                    if self.oracle.params is not None:
                        self.logger.info(
                            "[C2] BasalOracle fit successful. Params: A=%.2f, phi=%.2f, C=%.2f",
                            *self.oracle.params
                        )
                    else:
                        self.logger.warning("[C2] BasalOracle fit ran but insufficient fasting data. Retaining default.")
                except Exception as e:
                    self.logger.error("[C2] BasalOracle fit failed: %s", e)
            else:
                self.logger.debug("[C2] BasalOracle re-fit skipped: not enough snapshots yet (%d).", len(self.snapshots))

# =============================================================================
# 🔄 [LIVE MONITORING LOOP]
# =Focus: Real-Time Polling, Backfill Management, and HUD Orchestration
# =============================================================================
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

        task_maint = asyncio.create_task(self._maintenance_loop())
        self.background_tasks.add(task_maint)
        task_maint.add_done_callback(self.background_tasks.discard)

        # [C2] BasalOracle 24-hour re-fit loop
        task_oracle = asyncio.create_task(self._refit_oracle_loop())
        self.background_tasks.add(task_oracle)
        task_oracle.add_done_callback(self.background_tasks.discard)

        if self.bot_app:
            self.logger.info("Initializing Telegram Bot callback loop...")
            task_bot = asyncio.create_task(self.bot_app.app.initialize())
            await task_bot
            task_bot = asyncio.create_task(self.bot_app.app.start())
            await task_bot
            task_bot = asyncio.create_task(self.bot_app.app.updater.start_polling())
            self.background_tasks.add(task_bot)

        # 0. Stateful Backfill
        last_ts = await self.audit.get_last_reading_timestamp()
        if last_ts:
            # FIX: normalise to UTC-aware before comparisons AND before passing to fetch_since
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            gap_mins = (now - last_ts).total_seconds() / 60
            if medical_constants.SAMPLING_INTERVAL_MINS < gap_mins < config.BACKFILL_MAX_HOURS * 60:
                self.logger.info(f"Detected {gap_mins:.1f} min gap. Starting backfill...")
                
                # OPTIMIZATION: Prioritize MongoDB for deep historical backfills
                if self.mongo.entries is not None:
                    self.logger.info("Using MongoDB for high-fidelity backfill optimization...")
                    backfill_readings = await self.mongo.fetch_since(last_ts)
                else:
                    self.logger.info("Using Nightscout REST API for backfill...")
                    backfill_readings = await self.client.fetch_since(last_ts)
                
                if backfill_readings:
                    self.logger.info(f"Filling {len(backfill_readings)} missing readings...")
                    for r in backfill_readings:
                        await self._process_reading(r, is_backfill=True)
                    self.logger.info("Backfill complete. Kalman state stabilized.")

        while self.is_running:
            try:
                # Polling Strategy: Try MongoDB first if configured (zero latency), fallback to REST
                readings = []
                if self.mongo.entries is not None:
                    try:
                        readings = await self.mongo.fetch_recent_glucose(count=1)
                    except Exception as me:
                        self.logger.warning(f"MongoDB polling failed, falling back to REST: {me}")
                
                if not readings:
                    readings = await self.client.fetch_recent_glucose(count=1)
                
                if readings:
                    await self._process_reading(readings[0])
            except (ValueError, ConnectionError) as e:
                # Only crash if both backends fail with fatal Auth errors
                if ("URL" in str(e) or "token" in str(e).lower() or "Unauthorized" in str(e)) and self.mongo.entries is None:
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
        self.last_meal = MealEvent(
            timestamp=datetime.now(timezone.utc),
            carbs=grams,
            gi_type=gi_type
        )
        self.meal_window_start = datetime.now(timezone.utc)
        self.meal_tune_pending = True

        history_count = int(60 / config.SAMPLING_INTERVAL_MINS)
        history = self.snapshots[-history_count:]
        if history:
            prediction_4h = self.twin.predict_4h_trajectory(
                history, 
                meals=[self.last_meal],
                insulin_doses=[history[-1].last_insulin] if history and history[-1].last_insulin else None
            )

            # FIX L1: store peak now for use by auto_tune at t+230 min
            self.pending_meal_forecast_peak = float(prediction_4h.max())

            task = asyncio.create_task(self.pusher.push_update({
                "type": "meal_forecast",
                "description": desc,
                "grams": grams,
                "gi_type": gi_type,
                "prediction_4h": prediction_4h.tolist()
            }))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)

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
        # FIX: removed asyncio.wait() from here — it belongs only in stop(), not
        # in an interactive command handler (was blocking up to 5s on every /meal).

# =============================================================================
# 🛑 [TERMINATION]
# =Focus: Graceful Shutdown of Background Tasks and Services
# =============================================================================
    async def stop(self):
        """Graceful shutdown of all services."""
        self.is_running = False

        if self.bot_app:
            self.logger.info("Stopping Telegram Bot...")
            try:
                if self.bot_app.app.updater and self.bot_app.app.updater.running:
                    await self.bot_app.app.updater.stop()
                await self.bot_app.app.stop()
                await self.bot_app.app.shutdown()
            except Exception as e:
                self.logger.debug(f"Bot shutdown warning: {e}")

        if self.background_tasks:
            self.logger.info(f"Awaiting {len(self.background_tasks)} background tasks before shutdown...")
            await asyncio.wait(self.background_tasks, timeout=5.0)

        # Wave 0 Hardening: Close persistent clients
        self.logger.info("Closing persistent network and database resources...")
        await self.client.close()
        await self.weather_client.close()
        await self.pusher.close()
        
        from diabetic.utils.db import db_manager
        await db_manager.close()
        
        self.logger.info("Bio-Quant Orchestrator stopped.")

if __name__ == "__main__":
    async def main():
        c = await Coordinator.create()
        await c.start_live_mode()
    asyncio.run(main())