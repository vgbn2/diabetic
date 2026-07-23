import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Any, List, Optional
import numpy as np
from collections import deque
from diabetic.config import config
from diabetic.registry import GlucoseReading, InsulinDose, MetabolicSnapshot, MealEvent
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
from diabetic.ml_engine.forecast import build_horizons, build_basal_drift

from diabetic.telegram_bot.decision_matrix import DecisionMatrix, CircuitBreaker, Alert, AlertSeverity
from diabetic.telegram_bot.handlers import TelegramNotifier, TelegramApp

from diabetic.ui.cli_hud import RealTimeHUD
from diabetic.ui.visualizer import MetabolicVisualizer

from diabetic.utils.audit_logger import AuditLogger
from diabetic.utils.data_factory import TacticalForecaster, compute_confidence_index

from diabetic.storage.engine import init_db, close_db as close_storage_db
from diabetic.storage.vessel_registry import VesselRegistry
from diabetic.ml_engine.oracle import BasalOracle

# =============================================================================
# 🏗️ [ORCHESTRATION ARCHITECTURE]
# =Focus: System Initialization, State Tracking, and Registry Managed
# =============================================================================
class Coordinator:
    """
    The Orchestrator. Connects ingestion, smoothing, prediction, and alerting.
    """
    _instance: Optional["Coordinator"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Coordinator, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    @classmethod
    async def create(
        cls,
        audit_logger: Optional['AuditLogger'] = None,
        *,
        allow_synthetic: bool = False,
    ) -> "Coordinator":
        self = cls()
        if self._initialized:
            return self

        self.logger = logging.getLogger("Bio-Quant.Coordinator")
        self.background_tasks = set()
        self.audit = audit_logger or AuditLogger()
        self.client = NightscoutClient()
        self.mongo = MongoDBClient()
        self.allow_synthetic = allow_synthetic
        self.hr_client = HeartRateIngestor(allow_synthetic=allow_synthetic)
        self.weather_client = WeatherIngestor(allow_synthetic=allow_synthetic)
        self.filter = GlucoseFilter()

        self.neural_runner = MetabolicInferenceRunner()

        self.alert_guard = DecisionMatrix()
        self.circuit_breaker = CircuitBreaker()
        self.notifier = TelegramNotifier()
        self.notifier.audit_logger = self.audit
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
        # [G1] Wire VesselRegistry — multi-tenant bio-trait persistence
        self.vessel_registry = VesselRegistry()
        await init_db()  # idempotent: creates tables if not present
        await self.vessel_registry.migrate_from_env()  # one-time .env -> SQL migration
        self.logger.info("[G1] VesselRegistry initialized and traits loaded for user.")

        # [C2] Revive BasalOracle — harmonic circadian rhythm predictor
        self.oracle = BasalOracle(history_days=3)
        self.logger.info("[C2] BasalOracle instantiated. Will fit after 24h of data accumulation.")

        self.snapshots: deque[MetabolicSnapshot] = deque(maxlen=medical_constants.SNAPSHOT_CAP)
        self.regime_step_count = 0  # FIX C1: Persistent counter independent of buffer length

        # [F1] TWA forecast horizons, refreshed each live cycle by process_reading.
        self.last_prediction_4h: list = []   # 4h tactical trajectory (twin)
        self.last_prediction_1d: list = []   # 24h circadian projection (oracle)

        self.last_meal: Optional[MealEvent] = None
        self.meal_window_start: Optional[datetime] = None
        self.meal_tune_pending: bool = False
        self.actual_meal_peak: float = 0.0  # FIX C2: Tracks Highest Observed Glucose value during meal window

        # FIX L1: store the twin's predicted peak at meal-log time so auto_tune
        # compares actual glucose against the real 4h meal prediction, not
        # snapshot.predict_30m which is a short-horizon kinematic value.
        self.pending_meal_forecast_peak: Optional[float] = None
        self._confidence_smoothed: float = 1.0
        
        # O1: Consolidated Tactical Forecaster (physiology-aware)
        self.forecaster = TacticalForecaster(
            age=config.PATIENT_AGE,
            weight_kg=config.PATIENT_WEIGHT_KG
        )

        self.is_running = False
        self._initialized = True
        
        # Sovereign Atlas Level 2: Async ingestion queue
        self.ingestion_queue = asyncio.Queue(maxsize=120)
        self.worker_task: Optional[asyncio.Task] = None
        
        return self

    async def _worker_loop(self):
        """Sovereign Atlas Level 2: Async ingestion queue worker."""
        self.logger.info("Coordinator ingestion worker loop started.")
        while True:
            try:
                # Wait for a reading to arrive in the queue
                reading = await self.ingestion_queue.get()
                
                # Process the reading through the heavy neural/kalman pipeline
                await self._process_reading(reading)
                
                # Mark the task as done
                self.ingestion_queue.task_done()
            except asyncio.CancelledError:
                self.logger.info("Coordinator ingestion worker shut down.")
                break
            except Exception as e:
                self.logger.error(f"Error in ingestion worker loop: {e}")# =============================================================================
# 📡 [DATA SYNTHESIS PIPELINE]
# =Focus: Signal Quality, Smoothing (Kalman), and Multi-Stream Ingestion
# =============================================================================
    async def _fetch_recent_treatments(self, count: int = 10):
        """Fetch treatments from Mongo when direct access is available; otherwise use REST."""
        if getattr(self.mongo, "treatments", None) is not None:
            return await self.mongo.fetch_recent_treatments(count=count)
        return await self.client.fetch_recent_treatments(count=count)

    @staticmethod
    def _latest_treatment(value: Any, expected_type: type):
        """Normalize ingestion clients that return either one item or a list."""
        if value is None:
            return None
        if isinstance(value, expected_type):
            return value
        if isinstance(value, (list, tuple)):
            candidates = [item for item in value if isinstance(item, expected_type)]
            if candidates:
                return max(candidates, key=lambda item: item.timestamp)
        return None

    async def _process_reading(self, reading: GlucoseReading, is_backfill: bool = False):
        """Standard processing pipeline for a single reading."""
        self.regime_step_count += 1
        
        task = asyncio.create_task(self.audit.log_reading(reading))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

        # 1. Signal Quality Check
        history = [snapshot.glucose for snapshot in self.snapshots] + [reading]
        if len(history) < medical_constants.SIGNAL_MIN_HISTORY:
            self.logger.debug(
                f"Startup: only {len(history)} reading(s) — compression recovery check inactive until 3rd reading."
            )
        if SignalQuality.is_compression_low(history):
            self.logger.warning(f"Signal artifact detected at {reading.timestamp}. Skipping.")
            return
        if SignalQuality.is_compression_spike(history):
            self.logger.warning(f"Post-hypo spike artifact detected at {reading.timestamp} (value={reading.value:.1f}). Skipping.")
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
            tr_task = self._fetch_recent_treatments(count=10)
            hr_task = self.hr_client.fetch_latest()
            we_task = self.weather_client.fetch_current(config.LATITUDE, config.LONGITUDE)
            ms_task = self.vessel_registry.get_medical_state(config.USER_ID)
            results = await asyncio.gather(tr_task, hr_task, we_task, ms_task, return_exceptions=True)

            tr_res = results[0]
            if not isinstance(tr_res, Exception) and isinstance(tr_res, tuple):
                ns_insulin, ns_meal = tr_res
                ns_insulin = self._latest_treatment(ns_insulin, InsulinDose)
                ns_meal = self._latest_treatment(ns_meal, MealEvent)
                snapshot.last_insulin = ns_insulin
                snapshot.last_meal = self._active_meal(ns_meal)
            else:
                self.logger.warning(f"Nightscout treatment fetch failed: {tr_res}")
                snapshot.last_meal = self.last_meal

            hr_res = results[1]
            if not isinstance(hr_res, Exception):
                snapshot.cardiac = hr_res
                if (
                    hr_res is not None
                    and hr_res.provenance == "real"
                    and not is_backfill
                ):
                    persist_hr = asyncio.create_task(
                        self.mongo.save_cardiac_reading(hr_res)
                    )
                    self.background_tasks.add(persist_hr)
                    persist_hr.add_done_callback(self.background_tasks.discard)
            else:
                self.logger.warning(f"Cardiac ingestion failed: {hr_res}")
                snapshot.cardiac = None
            
            we_res = results[2]
            if (
                not isinstance(we_res, Exception)
                and we_res
                and (self.allow_synthetic or we_res.provenance == "real")
            ):
                snapshot.environment = we_res
                # PERSISTENCE (Phase 3): Anchor local weather to historical readings
                if not is_backfill:
                    persist_task = asyncio.create_task(self.mongo.save_environment_reading(we_res))
                    self.background_tasks.add(persist_task)
                    persist_task.add_done_callback(self.background_tasks.discard)
            else:
                self.logger.warning(f"Weather ingestion failed or returned null: {we_res}")
                snapshot.environment = None

            ms_res = results[3]
            if not isinstance(ms_res, Exception) and ms_res:
                # Dynamic Sick Mode Check
                is_active = ms_res.sick_mode_active
                if ms_res.sick_mode_expires_at:
                    if datetime.now(timezone.utc) > ms_res.sick_mode_expires_at.replace(tzinfo=timezone.utc):
                        is_active = False
                snapshot.is_sick = is_active
            else:
                snapshot.is_sick = False

        except Exception as e:
            self.logger.warning(f"In-depth ingestion failed: {e}. Falling back to defaults.")
            snapshot.last_meal = self.last_meal
            snapshot.cardiac = None
            snapshot.is_sick = False

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
            insulin_type = snapshot.last_insulin.type or "RAPID"
            snapshot.active_insulin = max(0.0, snapshot.last_insulin.units * self.twin.get_iob_fraction(dt_i, insulin_type=insulin_type))

        # 4. Feature Extraction
        snapshot.atr_14 = MetabolicMath.calculate_atr(list(self.snapshots) + [snapshot], period=14)

        # 5. Forecasting
        # Strategy: Use Multi-Task Neural Engine as primary, fallback to kinematics if warming up.
        neural_res = self.neural_runner.run_inference_on_snapshots(list(self.snapshots) + [snapshot])
        cnn_prediction = None
        if neural_res:
            cnn_prediction = neural_res["glucose"]
            snapshot.predicted_hr = neural_res["heart_rate"]
            self.logger.info(f"NEURAL_BRAIN: Pred Glu={cnn_prediction:.1f} | Pred HR={snapshot.predicted_hr:.1f}")

        # Wave 2 Hardening: Kinematic Fallback
        velocity = snapshot.velocity
        acceleration = snapshot.acceleration
        
        # [H1-P1] Apply BasalOracle correction to kinematic fallback
        # FIX: Oracle returns absolute basal glucose, so compute DELTA from current filtered value.
        # FIX: Use filtered_value (Kalman-smoothed), not raw glucose.value (susceptible to CGM spikes).
        oracle_offset = 0.0
        if self.oracle.params is not None:
            oracle_absolute = self.oracle.get_expected_basal(now + timedelta(minutes=30), now)
            oracle_offset = oracle_absolute - snapshot.filtered_value  # delta only
            self.logger.info(f"ORACLE_BIAS: Expected={oracle_absolute:.2f}, Current={snapshot.filtered_value:.2f}, Delta={oracle_offset:+.2f}")
            
        kinematic_prediction = snapshot.filtered_value + (velocity * 30.0) + oracle_offset
        
        prediction_30m = kinematic_prediction # Default

        if cnn_prediction is not None:
            # --- PHASE 4.1: Alpha Gating ---
            divergence = abs(cnn_prediction - kinematic_prediction)
            
            if divergence > medical_constants.ALPHA_GATE_DIVERGENCE_LIMIT and snapshot.confidence_index < medical_constants.ALPHA_GATE_CONFIDENCE_THRESHOLD:
                self.logger.warning(f"ALPHA GATE REJECTION: CNN ({cnn_prediction:.1f}) diverged from Kinematic ({kinematic_prediction:.1f}) by {divergence:.1f}. Confidence: {snapshot.confidence_index:.2f}. Falling back to Kinematic.")
                prediction_30m = kinematic_prediction
            else:
                # Standard blend if gate is passed
                prediction_30m = 0.5 * kinematic_prediction + 0.5 * cnn_prediction
            # -------------------------------
        else:
            self.logger.warning(f"NEURAL_BRAIN: Inference failed. Using Kinematic Projection: {prediction_30m:.1f}")
        
        snapshot.predict_30m = prediction_30m

        # 5b. Tactical Forecaster — 15/30/60m regression-based horizons
        points_1h = int(60 / medical_constants.SAMPLING_INTERVAL_MINS)
        points_90m = int(90 / medical_constants.SAMPLING_INTERVAL_MINS)
        full_history = list(self.snapshots) + [snapshot]
        
        raw_history: list[tuple[datetime, float]] = [
            (s.glucose.timestamp, s.glucose.value)
            for s in full_history[-points_1h:]  # Exactly 60 mins of data
        ]
        confidence_history: list[tuple[datetime, float]] = [
            (s.glucose.timestamp, s.glucose.value)
            for s in full_history[-points_90m:]  # Exactly 90 mins of data
        ]
        tactical = self.forecaster.compute(raw_history)
        snapshot.predict_15m = tactical["p15m"]
        snapshot.predict_60m = tactical["p60m"]
        snapshot.velocity_score = tactical["velocity"]
        
        raw_confidence = compute_confidence_index(confidence_history)
        self._confidence_smoothed = 0.8 * self._confidence_smoothed + 0.2 * raw_confidence
        snapshot.confidence_index = self._confidence_smoothed

        # 5c. Context Classification
        snapshot.activity_label = classify_context(snapshot).value

        # 6. Alert Decision
        # Guard: filtered_value < 0.5 indicates an uninitialized snapshot — skip alerting.
        # Strategy: Skip alerting during backfill/sync.
        if snapshot.filtered_value < 0.5:
            self.logger.warning("Skipping alert: filtered_value not yet initialized.")
            self.snapshots.append(snapshot)
            return
        if is_backfill:
            self.snapshots.append(snapshot)
            return

        try:
            alert = await self.alert_guard.evaluate(snapshot, prediction_30m, self.audit)
            if alert and self.circuit_breaker.can_alert(alert.type, severity=alert.severity):
                await self._dispatch_alert(alert)
                task = asyncio.create_task(self.audit.log_event("ALERT_TRIGGERED", alert.model_dump(), level="WARNING"))
                self.background_tasks.add(task)
                task.add_done_callback(self.background_tasks.discard)
        except Exception as e:
            self.logger.error(f"Alert evaluation failed: {e}. Attempting fallback alert...")
            if reading.value < medical_constants.HYPO_CRITICAL:
                emergency_alert = Alert(
                    timestamp=datetime.now(timezone.utc),
                    type="EMERGENCY_FALLBACK",
                    severity=AlertSeverity.EMERGENCY,
                    message=f"CRITICAL: Glucose is {reading.value:.1f}. Alert engine failure fallback triggered.",
                    glucose_value=reading.value
                )
                await self._dispatch_alert(emergency_alert)


        self.snapshots.append(snapshot)

        # 6a. Refresh TWA forecast horizons (4h tactical + 1d circadian).
        # Never let a forecast error break the processing/alert loop — retain last good.
        try:
            horizons = build_horizons(self.twin, self.oracle, list(self.snapshots), self.last_meal)
            self.last_prediction_4h = horizons["h4"]
            self.last_prediction_1d = horizons["h1d"]
        except Exception as e:
            self.logger.error(f"[F1] Forecast horizon refresh failed: {e.__class__.__name__}")

        hr_val = snapshot.bpm if snapshot.bpm else "N/A"
        hr_max = snapshot.max_bpm if snapshot.max_bpm else hr_val
        hrv_val = f"{snapshot.hrv:.1f}" if snapshot.hrv else "N/A"
        self.logger.info(f"DONE: {reading.value} -> Pred: {prediction_30m:.1f} | HR: {hr_val} (Pk: {hr_max}) | HRV: {hrv_val} | Snapshots: {len(self.snapshots)}")

        # 7. Digital Twin Regime Detection (every 6 hours)
        regime_trigger = int(360 / medical_constants.SAMPLING_INTERVAL_MINS)
        if self.regime_step_count % regime_trigger == 0:
            regime = self.twin.detect_regime(list(self.snapshots))
            self.logger.info(f"Metabolic Regime Detected: {regime} (Step: {self.regime_step_count})")

        # 8. Meal Window Auto-Tune
        if self.meal_tune_pending and self.meal_window_start:
            elapsed = (snapshot.glucose.timestamp - self.meal_window_start).total_seconds() / 60.0
            if elapsed >= 230:
                await self._auto_tune_meal(snapshot)
                self.meal_tune_pending = False
                self.meal_window_start = None

        # 9. Update Continuous Chart
        self.visualizer.update_continuous(list(self.snapshots))

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
                await self.mongo.run_retention_cleanup(days=config.RETENTION_DAYS)

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
                    await asyncio.to_thread(self.oracle.fit, list(self.snapshots))
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

        # Sovereign Atlas Level 2: Async Worker
        self.worker_task = asyncio.create_task(self._worker_loop())
        self.background_tasks.add(self.worker_task)
        self.worker_task.add_done_callback(self.background_tasks.discard)

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
            task_bot.add_done_callback(self.background_tasks.discard)

        # 0. Stateful Backfill (Hardened for Neural Warm-up)
        # STAGE 1: Blocking Priority (Neural Engine Saturation)
        self.logger.info("Starting STAGE 1 backfill (Neural Engine Saturation)...")
        
        try:
            # Strategy: Fetch exactly 35 readings to guarantee the 30-snapshot neural requirement.
            if self.mongo.entries is not None:
                backfill_readings = await self.mongo.fetch_neural_window()
            else:
                # Fallback to REST if MongoDB is not active
                backfill_readings = await self.client.fetch_recent_glucose(count=35)
                
            if backfill_readings:
                self.logger.info(f"Filling {len(backfill_readings)} historical readings to internal memory...")
                for r in backfill_readings:
                    await self._process_reading(r, is_backfill=True)
                
                if len(self.snapshots) < 30:
                    self.logger.warning(f"⚠️ NEURAL_BRAIN STARVATION: Only {len(self.snapshots)}/30 snapshots available. AI will be inactive until {30 - len(self.snapshots)} more readings arrive.")
                else:
                    self.logger.info(f"✅ NEURAL_BRAIN SATURATED: {len(self.snapshots)} snapshots loaded. AI Active.")
            else:
                self.logger.warning("No historical readings found. Starting in Cold Mode.")
        except Exception as be:
            self.logger.error(f"Critical Backfill Failure: {be}. Starting in degraded mode.")

        # STAGE 2: Deep Historical Sync (Background)
        # Launches after Stage 1 to populate the Audit Log with all-time history.
        now = datetime.now(timezone.utc)
        blocking_cutoff = now - timedelta(hours=24)
        sync_task = asyncio.create_task(self._deep_historical_sync(blocking_cutoff))
        self.background_tasks.add(sync_task)
        sync_task.add_done_callback(self.background_tasks.discard)



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
                    reading = readings[0]
                    # Wave 8 Hardening: Poll-level freshness check
                    now = datetime.now(timezone.utc)
                    r_ts = reading.timestamp.replace(tzinfo=timezone.utc) if reading.timestamp.tzinfo is None else reading.timestamp
                    if (now - r_ts).total_seconds() > medical_constants.STALE_DATA_TIMEOUT_SECS:
                        self.logger.warning(f"Poll returned stale data ({r_ts}). Waiting for fresh reading...")
                    else:
                        try:
                            self.ingestion_queue.put_nowait(reading)
                        except asyncio.QueueFull:
                            self.logger.warning("Ingestion queue flooded (>120). Dropping oldest packet to maintain realtime processing.")
                            _ = self.ingestion_queue.get_nowait()
                            self.ingestion_queue.task_done()
                            self.ingestion_queue.put_nowait(reading)
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
        history = list(self.snapshots)[-history_count:]
        if history:
            # [C2] Build basal drift array from Oracle for 4h projection
            dt = config.SAMPLING_INTERVAL_MINS
            n_points = int(240 / dt) + 1
            basal_drift = build_basal_drift(
                self.oracle, history[0].glucose.timestamp, n_points, dt
            )

            prediction_4h = self.twin.predict_4h_trajectory(
                history, 
                meals=[self.last_meal],
                insulin_doses=[history[-1].last_insulin] if history and history[-1].last_insulin else None,
                basal_drift=basal_drift
            )

            # FIX L1: store peak now for use by auto_tune at t+230 min
            self.pending_meal_forecast_peak = float(prediction_4h.max())

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

    async def _deep_historical_sync(self, end_ts: datetime):
        """Background task to fetch and audit history prior to the blocking backfill window."""
        limit_days = medical_constants.BACKFILL_DAYS_LIMIT
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=limit_days)
        self.logger.info(f"Background Sync: Starting deep historical fetch (Backwards from {end_ts.strftime('%Y-%m-%d')} to {cutoff_date.strftime('%Y-%m-%d')})")
        
        # We fetch in chunks of 3 days to avoid overwhelming the API
        current_end = end_ts
        chunk_days = 3
        total_synced = 0
        
        while self.is_running and current_end > cutoff_date:
            start_ts = max(cutoff_date, current_end - timedelta(days=chunk_days))
            try:
                if self.mongo.entries is not None:
                    # fetch_since fetches everything > start_ts
                    readings = await self.mongo.fetch_since(start_ts)
                else:
                    readings = await self.client.fetch_since(start_ts)

                if not readings:
                    self.logger.info(f"Background Sync Complete: Total {total_synced} historical readings audited.")
                    break
                
                # We only care about readings BEFORE current_end
                readings = [r for r in readings if r.timestamp < current_end]
                if not readings:
                    self.logger.info(f"Background Sync Complete: No older data found. Total {total_synced} audited.")
                    break

                for r in readings:
                    # We log to audit without full metabolic processing (skip expensive CPU tasks)
                    await self.audit.log_event("HISTORICAL_SYNC", r.model_dump())
                    total_synced += 1
                
                current_end = min(r.timestamp for r in readings)
                self.logger.info(f"Background Sync: Audited {len(readings)} readings. Moved cursor to {current_end.strftime('%Y-%m-%d')}")
                
                # Yield to live process
                await asyncio.sleep(5)
                
            except Exception as e:
                self.logger.error(f"Background Sync Failure: {e}. Retrying in 60s...")
                await asyncio.sleep(60)


    async def _auto_tune_meal(self, snapshot: MetabolicSnapshot):
        """Compares actual peak vs forecast peak; adjusts CSF."""
        if self.pending_meal_forecast_peak is None:
            return
        
        # Find actual peak in 230-min window post-meal
        since_meal = [
            s for s in self.snapshots
            if s.glucose.timestamp >= self.meal_window_start
        ]
        actual_peak = max((s.glucose.value for s in since_meal), default=None)
        if actual_peak is None:
            return
        
        forecast_peak = self.pending_meal_forecast_peak
        ratio = actual_peak / forecast_peak if forecast_peak > 0 else 1.0
        ratio = np.clip(ratio, 0.6, 1.4)  # Limit aggressive corrections
        
        # Damped update (don't overcorrect in one meal)
        ALPHA = 0.2
        self.twin.csf *= (1 + ALPHA * (ratio - 1.0))
        self.twin.csf = float(np.clip(self.twin.csf, 0.1, 5.0))
        
        self.logger.info(f"[AutoTune] CSF adjusted: ratio={ratio:.2f}, new CSF={self.twin.csf:.3f}")
        self.pending_meal_forecast_peak = None

# =============================================================================
# 🛑 [TERMINATION]
# =Focus: Graceful Shutdown of Background Tasks and Services
# =============================================================================
    async def stop(self):
        """Graceful shutdown of all services."""
        self.is_running = False
        await self.shutdown()
        self.logger.info("Bio-Quant Orchestrator stopped.")

    async def shutdown(self):
        """Graceful shutdown of background tasks and clients."""
        self.logger.info("Coordinator shutting down...")
        
        # Phase 3: Cancel Autonomous Scheduler
        if hasattr(self, '_scheduler_task') and self._scheduler_task:
            self.logger.info("Cancelling Autonomous Scheduler task...")
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

        # Cancel all background tasks
        for task in list(self.background_tasks):
            task.cancel()
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
        
        # Stop bot polling
        if self.bot_app and self.bot_app.app.updater and self.bot_app.app.updater.running:
            await self.bot_app.app.updater.stop()
            await self.bot_app.app.stop()
            await self.bot_app.app.shutdown()
        
        # Close ingestion clients
        if hasattr(self.client, 'close'):
            await self.client.close()
        if hasattr(self.mongo, 'close'):
            await self.mongo.close()
        if hasattr(self.weather_client, 'close'):
            await self.weather_client.close()
        from diabetic.storage.engine import close_db as close_storage_db
        await close_storage_db()
        
        self.logger.info("Coordinator shutdown complete.")

if __name__ == "__main__":
    async def main():
        c = await Coordinator.create()
        await c.start_live_mode()
    asyncio.run(main())
