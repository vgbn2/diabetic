import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Any, List, Optional
import numpy as np
from collections import deque
from diabetic.config import config
from diabetic.registry import (
    GlucoseReading,
    InsulinDose,
    MealEvent,
    MetabolicSnapshot,
    TreatmentFetchResult,
)
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
# =Focus: System Initialization, State Tracking, and Registry Management
# =============================================================================
class Coordinator:
    """
    Central orchestration engine for data ingestion, signal processing,
    neural inference, metabolic state tracking, and alert dispatching.
    """
    _instance: Optional["Coordinator"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Coordinator, cls).__new__(cls)
            cls._instance._initialized = False
            cls._instance._lifecycle_state = "initialized"
            cls._instance._lifecycle_lock = asyncio.Lock()
            cls._instance._shutdown_complete = False
            cls._instance._startup_claimed = False
            cls._instance._twa_thread = None
            cls._instance._twa_failure = None
            cls._instance._scheduler_task = None
            cls._instance.background_tasks = set()
            cls._instance.is_running = False
        return cls._instance

    async def begin_start(self) -> None:
        """Claim the only supported live start before any resource is created."""
        async with self._lifecycle_lock:
            if self._lifecycle_state in {"stopped", "failed"}:
                raise RuntimeError(
                    "runtime requires process replacement after stop or failure"
                )
            if self._startup_claimed or self._lifecycle_state in {
                "starting",
                "running",
                "stopping",
            }:
                raise RuntimeError("runtime startup is already claimed")
            self._startup_claimed = True
            self._lifecycle_state = "starting"

    async def _require_start_claim(self) -> None:
        async with self._lifecycle_lock:
            if not self._startup_claimed or self._lifecycle_state != "starting":
                raise RuntimeError("live mode requires an active startup claim")
            self._lifecycle_state = "running"

    async def mark_failed(self) -> None:
        """Record fatal runtime state without attempting in-process recovery."""
        async with self._lifecycle_lock:
            if self._lifecycle_state not in {"stopping", "stopped"}:
                self._lifecycle_state = "failed"
            self.is_running = False

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
        self._owns_audit_logger = audit_logger is None
        self.audit = audit_logger or AuditLogger()
        self.allow_synthetic = allow_synthetic

        # R61: Cohesive initialization seams
        self._init_services()
        await self._init_storage_and_oracle()
        self._init_state_buffers()

        self.is_running = False
        self._initialized = True
        return self

    def _init_services(self) -> None:
        """Initialize ingestion clients, DSP filters, neural inference, alerts, and UI components."""
        self.client = NightscoutClient()
        self.mongo = MongoDBClient()
        self.hr_client = HeartRateIngestor(allow_synthetic=self.allow_synthetic)
        self.weather_client = WeatherIngestor(allow_synthetic=self.allow_synthetic)
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
            cycle_start=config.PATIENT_CYCLE_START,
        )
        self.visualizer = MetabolicVisualizer(output_dir="charts")

    async def _init_storage_and_oracle(self) -> None:
        """Initialize database tables, vessel traits migration, and BasalOracle."""
        self.vessel_registry = VesselRegistry()
        await init_db()  # idempotent: creates tables if not present
        await self.vessel_registry.migrate_from_env()  # one-time .env -> SQL migration
        self.logger.info("[G1] VesselRegistry initialized and traits loaded for user.")

        self.oracle = BasalOracle(history_days=3)
        self.logger.info("[C2] BasalOracle instantiated. Will fit after 24h of data accumulation.")

    def _init_state_buffers(self) -> None:
        """Initialize internal state tracking buffers, forecast deques, and ingestion queue."""
        self.snapshots: deque[MetabolicSnapshot] = deque(maxlen=medical_constants.SNAPSHOT_CAP)
        self.regime_step_count = 0

        self.last_prediction_4h: list = []
        self.last_prediction_1d: list = []

        self.last_meal: Optional[MealEvent] = None
        self.last_provider_meal: Optional[MealEvent] = None
        self.last_provider_insulin: Optional[InsulinDose] = None
        self.treatment_fetch_state = "waiting"
        self.treatment_source: Optional[str] = None
        self.treatment_fetched_at: Optional[datetime] = None
        self.treatment_degraded_reason: Optional[str] = None
        self.meal_window_start: Optional[datetime] = None
        self.meal_tune_pending: bool = False
        self.actual_meal_peak: float = 0.0
        self.pending_meal_forecast_peak: Optional[float] = None
        self._confidence_smoothed: float = 1.0

        self.forecaster = TacticalForecaster(
            age=config.PATIENT_AGE,
            weight_kg=config.PATIENT_WEIGHT_KG,
        )

        self.ingestion_queue = asyncio.Queue(maxsize=120)
        self.worker_task: Optional[asyncio.Task] = None

    # =========================================================================
    # ⚡ [R62: TASK TRACKING & DRAIN CONTRACT]
    # =========================================================================
    def track_background_task(
        self,
        coro_or_task: Any,
        name: Optional[str] = None,
    ) -> asyncio.Task:
        """
        Explicitly track a background task with lifecycle supervision and done cleanup.
        """
        if isinstance(coro_or_task, asyncio.Task):
            task = coro_or_task
        else:
            task = asyncio.create_task(coro_or_task, name=name)

        self.background_tasks.add(task)

        def _on_done(t: asyncio.Task):
            self.background_tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc:
                    self.logger.error("Background task '%s' failed: %s", t.get_name(), exc)

        task.add_done_callback(_on_done)
        return task

    async def drain_background_tasks(
        self,
        timeout: float = 5.0,
        cancel_remaining: bool = False,
    ) -> None:
        """
        Drain all currently active background tasks up to timeout, then optionally cancel remaining.
        """
        tasks = list(self.background_tasks)
        if not tasks:
            return

        if cancel_remaining:
            for task in tasks:
                if not task.done():
                    task.cancel()

        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self.logger.warning("Timed out draining %d background tasks. Forcing cancellation.", len(tasks))
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self.background_tasks.clear()

    async def _worker_loop(self):
        """Sovereign Atlas Level 2: Async ingestion queue worker."""
        self.logger.info("Coordinator ingestion worker loop started.")
        while True:
            try:
                reading = await self.ingestion_queue.get()
                await self._process_reading(reading)
                self.ingestion_queue.task_done()
            except asyncio.CancelledError:
                self.logger.info("Coordinator ingestion worker shut down.")
                break
            except Exception as e:
                self.logger.error(f"Error in ingestion worker loop: {e}")

    # =========================================================================
    # 📡 [DATA SYNTHESIS PIPELINE & STAGE SEAMS (R61)]
    # =========================================================================
    async def _fetch_recent_treatments(self, count: int = 10) -> TreatmentFetchResult:
        """Fetch treatments with REST fallback when direct Mongo is degraded."""
        if getattr(self.mongo, "treatments", None) is not None:
            try:
                primary = await self.mongo.fetch_recent_treatments(count=count)
            except Exception as exc:
                primary = TreatmentFetchResult(
                    source="mongo",
                    state="degraded",
                    error_reason=type(exc).__name__,
                )
            if primary.state == "ok":
                return primary

            try:
                secondary = await self.client.fetch_recent_treatments(count=count)
            except Exception as exc:
                secondary = TreatmentFetchResult(
                    source="nightscout",
                    state="degraded",
                    error_reason=type(exc).__name__,
                )
            if secondary.state == "ok":
                return secondary
            return TreatmentFetchResult(
                source="mongo+nightscout",
                state="degraded",
                error_reason="all_treatment_providers_degraded",
            )

        try:
            return await self.client.fetch_recent_treatments(count=count)
        except Exception as exc:
            return TreatmentFetchResult(
                source="nightscout",
                state="degraded",
                error_reason=type(exc).__name__,
            )

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

    def _stage_signal_quality(self, reading: GlucoseReading) -> bool:
        """Stage 1: Verify signal quality, artifact rejection, and freshness."""
        reading_history = [s.glucose for s in self.snapshots] + [reading]
        if SignalQuality.is_compression_low(reading_history):
            self.logger.warning(
                "COMPRESSION ARTIFACT (LOW): Sensor reading dropped precipitously. "
                "Bypassing filter update and alerting to prevent false hypoglycemia intervention."
            )
            return False

        if SignalQuality.is_compression_spike(reading_history):
            self.logger.warning(
                "COMPRESSION ARTIFACT (SPIKE): Transient rate-of-change spike detected. "
                "Suppressing spurious alert triggers."
            )
            return False

        now = datetime.now(timezone.utc)
        reading_ts = reading.timestamp
        if reading_ts.tzinfo is None:
            reading_ts = reading_ts.replace(tzinfo=timezone.utc)
        if (now - reading_ts).total_seconds() > medical_constants.STALE_DATA_TIMEOUT_SECS:
            self.logger.warning(f"Stale data ignored: {reading.timestamp} is too old.")
            return False

        if self.snapshots:
            last_reading_time = self.snapshots[-1].glucose.timestamp
            if last_reading_time.tzinfo is None:
                last_reading_time = last_reading_time.replace(tzinfo=timezone.utc)
            dt = (now - last_reading_time).total_seconds()
            if dt > medical_constants.STALE_DATA_TIMEOUT_SECS:
                self.logger.warning(f"Metabolic data is STALE ({dt/60:.1f} mins old). Prediction accuracy reduced.")

        return True

    async def _stage_multistream_ingestion(
        self,
        snapshot: MetabolicSnapshot,
        is_backfill: bool = False,
    ) -> None:
        """Stage 2: Multi-stream ingestion gathering treatments, HR, weather, and sick mode."""
        try:
            tr_task = self._fetch_recent_treatments(count=10)
            hr_task = self.hr_client.fetch_latest()
            we_task = self.weather_client.fetch_current(config.LATITUDE, config.LONGITUDE)
            ms_task = self.vessel_registry.get_medical_state(config.USER_ID)
            results = await asyncio.gather(tr_task, hr_task, we_task, ms_task, return_exceptions=True)

            tr_res = results[0]
            if isinstance(tr_res, TreatmentFetchResult):
                self._apply_treatment_result(snapshot, tr_res)
            else:
                reason = (
                    type(tr_res).__name__
                    if isinstance(tr_res, Exception)
                    else "invalid_treatment_result"
                )
                self._apply_treatment_result(
                    snapshot,
                    TreatmentFetchResult(
                        source="coordinator",
                        state="degraded",
                        error_reason=reason,
                    ),
                )

            hr_res = results[1]
            if not isinstance(hr_res, Exception):
                snapshot.cardiac = hr_res
                if hr_res is not None and hr_res.provenance == "real" and not is_backfill:
                    self.track_background_task(
                        self.mongo.save_cardiac_reading(hr_res),
                        name="save_cardiac_reading",
                    )
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
                if not is_backfill:
                    self.track_background_task(
                        self.mongo.save_environment_reading(we_res),
                        name="save_environment_reading",
                    )
            else:
                self.logger.warning(f"Weather ingestion failed or returned null: {we_res}")
                snapshot.environment = None

            ms_res = results[3]
            if not isinstance(ms_res, Exception) and ms_res:
                is_active = ms_res.sick_mode_active
                if ms_res.sick_mode_expires_at:
                    if datetime.now(timezone.utc) > ms_res.sick_mode_expires_at.replace(tzinfo=timezone.utc):
                        is_active = False
                snapshot.is_sick = is_active
            else:
                snapshot.is_sick = False

        except Exception as e:
            self.logger.warning(f"In-depth ingestion failed: {e}. Falling back to defaults.")
            self._apply_treatment_result(
                snapshot,
                TreatmentFetchResult(
                    source="coordinator",
                    state="degraded",
                    error_reason=type(e).__name__,
                ),
            )
            snapshot.cardiac = None
            snapshot.is_sick = False

    def _stage_metabolic_decay(self, snapshot: MetabolicSnapshot, now: datetime) -> None:
        """Stage 3: Estimate active carbs/insulin (COB/IOB) via DigitalTwin decay curves."""
        if snapshot.last_meal and snapshot.last_meal.carbs is not None:
            dt_m = (now - snapshot.last_meal.timestamp).total_seconds() / 60.0
            gi_type = snapshot.last_meal.gi_type or "STARCH"
            full_curve = self.twin.simulate_carb_impact(
                snapshot.last_meal.carbs, gi_type=gi_type, resolution_mins=1.0
            )
            total_area = float(full_curve.sum())
            if total_area > 0.0:
                elapsed_idx = min(int(dt_m), len(full_curve) - 1)
                remaining_area = float(full_curve[elapsed_idx:].sum())
                cob_fraction = remaining_area / total_area
            else:
                cob_fraction = max(0.0, 1.0 - dt_m / 240.0)
            snapshot.active_carbs = max(0.0, snapshot.last_meal.carbs * cob_fraction)

        if snapshot.last_insulin and snapshot.last_insulin.units is not None:
            dt_i = (now - snapshot.last_insulin.timestamp).total_seconds() / 60.0
            insulin_type = snapshot.last_insulin.type or "RAPID"
            snapshot.active_insulin = max(
                0.0,
                snapshot.last_insulin.units * self.twin.get_iob_fraction(dt_i, insulin_type=insulin_type),
            )

    def _stage_feature_extraction(self, snapshot: MetabolicSnapshot) -> None:
        """Stage 4: Compute ATR-14 volatility."""
        snapshot.atr_14 = MetabolicMath.calculate_atr(list(self.snapshots) + [snapshot], period=14)

    def _stage_forecasting(self, snapshot: MetabolicSnapshot, now: datetime) -> float:
        """Stage 5: Multi-task neural inference, circadian delta bias, and kinematic blending."""
        neural_res = self.neural_runner.run_inference_on_snapshots(list(self.snapshots) + [snapshot])
        cnn_prediction = None
        if neural_res:
            cnn_prediction = neural_res["glucose"]
            snapshot.predicted_hr = neural_res["heart_rate"]
            self.logger.info(f"NEURAL_BRAIN: Pred Glu={cnn_prediction:.1f} | Pred HR={snapshot.predicted_hr:.1f}")

        velocity = snapshot.velocity
        acceleration = snapshot.acceleration
        oracle_offset = 0.0

        if self.oracle.is_fitted:
            t_future = now + timedelta(minutes=30)
            oracle_basal_future = self.oracle.predict_basal(t_future)
            oracle_basal_now = self.oracle.predict_basal(now)
            oracle_offset = oracle_basal_future - oracle_basal_now

        kinematic_prediction = snapshot.filtered_value + (velocity * 30.0) + (0.5 * acceleration * (30.0 ** 2)) + oracle_offset

        if cnn_prediction is not None:
            raw_diff = abs(cnn_prediction - kinematic_prediction)
            delta_threshold = 2.0
            if raw_diff > delta_threshold:
                alpha = 0.2
                self.logger.warning(
                    f"⚠️ [ALPHA GATING DIVERGENCE] CNN ({cnn_prediction:.2f}) vs Kinematic ({kinematic_prediction:.2f}) "
                    f"Δ={raw_diff:.2f} > {delta_threshold}. Dampening AI influence (alpha={alpha})."
                )
            else:
                alpha = 0.7
            prediction_30m = (alpha * cnn_prediction) + ((1.0 - alpha) * kinematic_prediction)
        else:
            prediction_30m = kinematic_prediction

        snapshot.predict_30m = prediction_30m

        tactical = self.forecaster.forecast(
            current_glucose=snapshot.filtered_value,
            velocity=snapshot.velocity,
            acceleration=snapshot.acceleration,
            cob=snapshot.active_carbs,
            iob=snapshot.active_insulin,
            csf=self.twin.csf,
            cr=self.twin.cr,
            isf=self.twin.isf,
            dt_mins=config.SAMPLING_INTERVAL_MINS,
            steps_15m=3,
            steps_60m=12,
        )
        snapshot.predict_15m = tactical.pred_15m
        snapshot.predict_60m = tactical.pred_60m

        self.logger.info(
            f"Glucose: Raw={snapshot.glucose.value:.1f} | Filtered={snapshot.filtered_value:.1f} | "
            f"Pred30m={prediction_30m:.1f} | Pred15m={snapshot.predict_15m:.1f} | Pred60m={snapshot.predict_60m:.1f} | "
            f"V={velocity:+.3f} | A={acceleration:+.4f}"
        )
        return prediction_30m

    async def _stage_alert_dispatch(
        self,
        snapshot: MetabolicSnapshot,
        reading: GlucoseReading,
        prediction_30m: float,
        is_backfill: bool,
    ) -> None:
        """Stage 6: Decision matrix evaluation and alert dispatching."""
        current_context = classify_context(list(self.snapshots) + [snapshot])
        snapshot.context = current_context

        if is_backfill:
            return

        try:
            alert = self.alert_guard.evaluate(
                snapshot=snapshot,
                reading=reading,
                predicted_30m=prediction_30m,
                context=current_context,
            )
            if alert:
                if self.circuit_breaker.can_send(alert):
                    await self._dispatch_alert(alert)
                else:
                    self.logger.info(f"Alert throttled by circuit breaker: {alert.type}")
        except Exception as e:
            self.logger.error(f"Decision matrix evaluation failed: {e}. Checking fallback critical bounds...")
            if reading.value < medical_constants.CRITICAL_HYPO_THRESHOLD:
                emergency_alert = Alert(
                    type="CRITICAL_HYPO_FALLBACK",
                    severity=AlertSeverity.CRITICAL,
                    message=f"CRITICAL HYPO: Glucose is {reading.value:.1f} mmol/L. Urgent intervention needed.",
                    timestamp=datetime.now(timezone.utc),
                )
                await self._dispatch_alert(emergency_alert)

    async def _stage_post_cycle(
        self,
        snapshot: MetabolicSnapshot,
        is_backfill: bool,
    ) -> None:
        """Stage 7: TWA forecast horizon projection, regime detection, auto-tune, and chart rendering."""
        # TWA Forecast Horizons (4h tactical + 24h circadian)
        h_4h, h_1d = build_horizons(
            twin=self.twin,
            oracle=self.oracle,
            snapshots=list(self.snapshots),
            last_meal=snapshot.last_meal,
            last_insulin=snapshot.last_insulin,
            sampling_interval_mins=config.SAMPLING_INTERVAL_MINS,
        )
        self.last_prediction_4h = h_4h
        self.last_prediction_1d = h_1d

        # Persist reading and audit
        if not is_backfill:
            self.track_background_task(
                self.mongo.save_glucose_reading(snapshot.glucose),
                name="save_glucose_reading",
            )
            self.track_background_task(
                self.audit.log_reading(snapshot),
                name="audit_log_reading",
            )

        # Periodic Metabolic Regime Classification (every 6h = 72 cycles)
        self.regime_step_count += 1
        if self.regime_step_count % 72 == 0 and len(self.snapshots) >= 72:
            regime = self.twin.detect_regime(list(self.snapshots))
            self.logger.info(f"Metabolic Regime Detected: {regime} (Step: {self.regime_step_count})")

        # Meal Window Auto-Tune
        if self.meal_tune_pending and self.meal_window_start:
            elapsed = (snapshot.glucose.timestamp - self.meal_window_start).total_seconds() / 60.0
            if elapsed >= 230:
                await self._auto_tune_meal(snapshot)
                self.meal_tune_pending = False
                self.meal_window_start = None

        # Continuous chart update
        self.visualizer.update_continuous(list(self.snapshots))

    async def _process_reading(self, reading: GlucoseReading, is_backfill: bool = False) -> bool:
        """
        Sequential execution pipeline for incoming glucose readings.
        """
        # 1. Signal Quality & Freshness
        if not self._stage_signal_quality(reading):
            return False

        # 2. Smoothing (Kalman)
        snapshot = self.filter.update(reading)
        now = datetime.now(timezone.utc)

        # 3. Multi-stream Ingestion
        await self._stage_multistream_ingestion(snapshot, is_backfill=is_backfill)

        # 4. Metabolic Decay & Feature Extraction
        self._stage_metabolic_decay(snapshot, now)
        self._stage_feature_extraction(snapshot)

        # 5. Forecasting & Kinematic Blending
        prediction_30m = self._stage_forecasting(snapshot, now)

        # 6. Append Snapshot
        self.snapshots.append(snapshot)

        # 7. Alert Evaluation & Dispatch
        await self._stage_alert_dispatch(snapshot, reading, prediction_30m, is_backfill=is_backfill)

        # 8. Post-Cycle Projections & Visualizer
        await self._stage_post_cycle(snapshot, is_backfill=is_backfill)

        return True

    # =========================================================================
    # 🎮 [INTERACTION & INTERFACE]
    # =========================================================================
    def _active_meal(self, ns_meal: Optional[MealEvent]) -> Optional[MealEvent]:
        """Arbitrate between Telegram-logged meal and Nightscout-logged meal."""
        if not self.last_meal and not ns_meal:
            return None
        now = datetime.now(timezone.utc)

        if self.last_meal:
            dt = (now - self.last_meal.timestamp).total_seconds() / 60.0
            if dt <= medical_constants.MEAL_WINDOW_MINS:
                return self.last_meal

        return ns_meal

    @staticmethod
    def _is_active_treatment(event, window_mins: float) -> bool:
        if event is None:
            return False
        timestamp = event.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_mins = (datetime.now(timezone.utc) - timestamp).total_seconds() / 60.0
        return 0.0 <= age_mins <= window_mins

    def _active_provider_insulin(self) -> Optional[InsulinDose]:
        dose = self.last_provider_insulin
        if dose is None:
            return None
        window_mins = (
            medical_constants.BASAL_DURATION_HOURS * 60.0
            if dose.type.upper() == "LONG"
            else medical_constants.INSULIN_ACTION_WINDOW_MINS
        )
        return dose if self._is_active_treatment(dose, window_mins) else None

    def _active_provider_meal(self) -> Optional[MealEvent]:
        meal = self.last_provider_meal
        return (
            meal
            if self._is_active_treatment(meal, medical_constants.MEAL_WINDOW_MINS)
            else None
        )

    def _apply_treatment_result(
        self,
        snapshot: MetabolicSnapshot,
        result: TreatmentFetchResult,
    ) -> None:
        self.treatment_fetch_state = result.state
        self.treatment_source = result.source
        self.treatment_fetched_at = result.fetched_at
        self.treatment_degraded_reason = result.error_reason

        if result.state == "ok":
            self.last_provider_insulin = self._latest_treatment(
                result.insulin, InsulinDose
            )
            self.last_provider_meal = self._latest_treatment(result.meals, MealEvent)
        else:
            self.logger.warning(
                "Treatment context degraded (%s): retaining bounded last-known-good state",
                result.error_reason or "unknown",
            )

        snapshot.last_insulin = self._active_provider_insulin()
        snapshot.last_meal = self._active_meal(self._active_provider_meal())

    async def _dispatch_alert(self, alert: Alert):
        """Sends alert to Telegram and logger."""
        self.logger.error(f"ALERT DISPATCHED: {alert.type} - {alert.message}")
        await self.notifier.send_alert(alert)

    # =========================================================================
    # ⚙️ [MAINTENANCE & REGIONAL SYNC]
    # =========================================================================
    async def _maintenance_loop(self):
        """Automated Daily Maintenance. Staggered based on USER_TIMEZONE."""
        tz = ZoneInfo(config.USER_TIMEZONE)
        self.logger.info(f"Regional Maintenance Loop active. Local Timezone: {config.USER_TIMEZONE}")

        while self.is_running:
            now = datetime.now(tz)
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
                from diabetic.operations.retention import execute_retention_cleanup

                retention = await execute_retention_cleanup(
                    config.RETENTION_DAYS,
                    mongo=self.mongo,
                    audit=self.audit,
                )
                if not retention.successful:
                    await self.audit.log_admin_action(
                        "AUTO_MAINTENANCE_FAILED",
                        {
                            "state": retention.state,
                            "failed_phase": retention.failed_phase,
                        },
                    )
                    self.logger.error(
                        "Regional maintenance retention %s during %s.",
                        retention.state,
                        retention.failed_phase or "unknown",
                    )
                    continue

                await self.audit.log_admin_action("AUTO_MAINTENANCE_COMPLETE", {"local_time": str(target)})
                self.logger.info("Regional Maintenance Cycle complete.")
            except Exception as e:
                self.logger.error(f"Maintenance cycle failed: {e}")
                await self.audit.log_admin_action("AUTO_MAINTENANCE_FAILED", {"error": str(e)})

            await asyncio.sleep(60)

    async def _refit_oracle_loop(self):
        """[C2] Fits the BasalOracle every 24h on accumulated snapshot history."""
        self.logger.info("[C2] BasalOracle re-fit loop started. First fit in 24h.")
        while self.is_running:
            await asyncio.sleep(24 * 3600)
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

    # =========================================================================
    # 🔄 [LIVE MONITORING LOOP]
    # =========================================================================
    async def start_live_mode(self):
        """Poll Nightscout after the process supervisor claims startup."""
        await self._require_start_claim()
        self.is_running = True
        self.logger.info(f"Coordinator started in LIVE mode (Interval: {config.DATA_POLLING_INTERVAL}s)")

        self.track_background_task(self.hud.run_live(self), name="hud_live")
        self.worker_task = asyncio.create_task(self._worker_loop(), name="ingestion_worker")
        self.track_background_task(self.hr_client.start_ble_client(), name="ble_client")
        self.track_background_task(self._maintenance_loop(), name="maintenance_loop")
        self.track_background_task(self._refit_oracle_loop(), name="refit_oracle_loop")

        if self.bot_app:
            self.logger.info("Initializing Telegram Bot callback loop...")
            await self.bot_app.app.initialize()
            await self.bot_app.app.start()
            task_bot = asyncio.create_task(self.bot_app.app.updater.start_polling(), name="bot_updater")
            self.track_background_task(task_bot, name="bot_updater")

        # 0. Stateful Backfill (Hardened for Neural Warm-up)
        self.logger.info("Starting STAGE 1 backfill (Neural Engine Saturation)...")
        try:
            if self.mongo.entries is not None:
                backfill_readings = await self.mongo.fetch_neural_window()
            else:
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

        now = datetime.now(timezone.utc)
        blocking_cutoff = now - timedelta(hours=24)
        self.track_background_task(self._deep_historical_sync(blocking_cutoff), name="deep_sync")

        while self.is_running:
            try:
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
            gi_type=gi_type,
        )
        self.meal_window_start = datetime.now(timezone.utc)
        self.meal_tune_pending = True

        history_count = int(60 / config.SAMPLING_INTERVAL_MINS)
        history = list(self.snapshots)[-history_count:]
        if history:
            dt = config.SAMPLING_INTERVAL_MINS
            n_points = int(240 / dt) + 1
            basal_drift = build_basal_drift(
                self.oracle, history[0].glucose.timestamp, n_points, dt
            )

            prediction_4h = self.twin.predict_4h_trajectory(
                history,
                meals=[self.last_meal],
                insulin_doses=[history[-1].last_insulin] if history and history[-1].last_insulin else None,
                basal_drift=basal_drift,
            )

            self.pending_meal_forecast_peak = float(prediction_4h.max())

            chart_path = self.visualizer.plot_forecast(
                history=[s.glucose.value for s in history],
                prediction=prediction_4h,
                meal_name=desc,
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

        current_end = end_ts
        chunk_days = 3
        total_synced = 0

        while self.is_running and current_end > cutoff_date:
            start_ts = max(cutoff_date, current_end - timedelta(days=chunk_days))
            try:
                if self.mongo.entries is not None:
                    readings = await self.mongo.fetch_since(start_ts)
                else:
                    readings = await self.client.fetch_since(start_ts)

                if not readings:
                    self.logger.info(f"Background Sync Complete: Total {total_synced} historical readings audited.")
                    break

                readings = [r for r in readings if r.timestamp < current_end]
                if not readings:
                    self.logger.info(f"Background Sync Complete: No older data found. Total {total_synced} audited.")
                    break

                for r in readings:
                    await self.audit.log_event("HISTORICAL_SYNC", r.model_dump())
                    total_synced += 1

                current_end = min(r.timestamp for r in readings)
                self.logger.info(f"Background Sync: Audited {len(readings)} readings. Moved cursor to {current_end.strftime('%Y-%m-%d')}")
                await asyncio.sleep(5)
            except Exception as e:
                self.logger.error(f"Background Sync Failure: {e}. Retrying in 60s...")
                await asyncio.sleep(60)

    async def _auto_tune_meal(self, snapshot: MetabolicSnapshot):
        """Compares actual peak vs forecast peak; adjusts CSF."""
        if self.pending_meal_forecast_peak is None:
            return

        since_meal = [
            s for s in self.snapshots
            if s.glucose.timestamp >= self.meal_window_start
        ]
        actual_peak = max((s.glucose.value for s in since_meal), default=None)
        if actual_peak is None:
            return

        forecast_peak = self.pending_meal_forecast_peak
        ratio = actual_peak / forecast_peak if forecast_peak > 0 else 1.0
        ratio = np.clip(ratio, 0.6, 1.4)

        ALPHA = 0.2
        self.twin.csf *= (1 + ALPHA * (ratio - 1.0))
        self.twin.csf = float(np.clip(self.twin.csf, 0.1, 5.0))

        self.logger.info(f"[AutoTune] CSF adjusted: ratio={ratio:.2f}, new CSF={self.twin.csf:.3f}")
        self.pending_meal_forecast_peak = None

    # =========================================================================
    # 🛑 [TERMINATION (R62 DRAIN CONTRACT)]
    # =========================================================================
    async def stop(self):
        """Graceful shutdown of all services."""
        self.is_running = False
        await self.shutdown()
        self.logger.info("Bio-Quant Orchestrator stopped.")

    async def shutdown(self):
        """Idempotently stop every resource owned by this process runtime."""
        async with self._lifecycle_lock:
            if self._shutdown_complete or self._lifecycle_state == "stopping":
                return
            failed = self._lifecycle_state == "failed"
            self._lifecycle_state = "stopping"
            self.is_running = False

        logger = getattr(self, "logger", logging.getLogger("Bio-Quant.Coordinator"))
        logger.info("Coordinator shutting down...")

        # Tier 1: Clear TWA API Projection Reference
        from diabetic.telegram_bot.twa_api import clear_api_coordinator
        clear_api_coordinator(self)

        # Tier 2: Cancel Autonomous Scheduler Task
        scheduler_task = getattr(self, "_scheduler_task", None)
        if scheduler_task is not None:
            logger.info("Cancelling Autonomous Scheduler task...")
            scheduler_task.cancel()
            await asyncio.gather(scheduler_task, return_exceptions=True)
            self._scheduler_task = None

        # Tier 3: Cancel Ingestion Worker
        worker_task = getattr(self, "worker_task", None)
        if worker_task is not None:
            if not worker_task.done():
                worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
            self.worker_task = None

        # Tier 4: Cancel Notifier Pending Auto-Review Tasks
        notifier = getattr(self, "notifier", None)
        if notifier is not None and hasattr(notifier, "pending_tasks"):
            for p_task in list(notifier.pending_tasks):
                p_task.cancel()
            if notifier.pending_tasks:
                await asyncio.gather(*notifier.pending_tasks, return_exceptions=True)
                notifier.pending_tasks.clear()

        # Tier 5: Drain & Cancel Coordinator Background Tasks
        await self.drain_background_tasks(timeout=2.0, cancel_remaining=True)

        # Tier 6: Stop Telegram Bot
        bot_app = getattr(self, "bot_app", None)
        if (
            bot_app
            and bot_app.app.updater
            and bot_app.app.updater.running
        ):
            await bot_app.app.updater.stop()
            await bot_app.app.stop()
            await bot_app.app.shutdown()

        # Tier 7: Close Ingestion Clients
        for name in ("client", "mongo", "weather_client"):
            resource = getattr(self, name, None)
            close = getattr(resource, "close", None)
            if close is not None:
                await close()

        # Tier 8: Close Storage and Audit Loggers
        audit = getattr(self, "audit", None)
        if getattr(self, "_owns_audit_logger", False) and audit is not None:
            await audit.close()
        await close_storage_db()

        # Tier 9: Finalize Lifecycle State
        async with self._lifecycle_lock:
            self._shutdown_complete = True
            self._lifecycle_state = "failed" if failed else "stopped"
        logger.info("Coordinator shutdown complete.")


if __name__ == "__main__":
    async def main():
        c = await Coordinator.create()
        await c.begin_start()
        await c.start_live_mode()
    asyncio.run(main())
