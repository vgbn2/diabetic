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
from diabetic.ingestion.event_integrity import (
    BufferedGlucoseEvent,
    GlucoseEventBuffer,
    canonical_event_source,
    prepare_warmup_readings,
)
from diabetic.ingestion.cardiac import HeartRateIngestor
from diabetic.ingestion.weather import WeatherIngestor

from diabetic.dsp.kalman import GlucoseFilter
from diabetic.dsp.signal_quality import SignalQuality
from diabetic.dsp.metabolic_math import MetabolicMath
from diabetic.dsp.context_classifier import classify_context

from diabetic.ml_engine.twin import DigitalTwin
from diabetic.ml_engine.inference import MetabolicInferenceRunner
from diabetic.ml_engine.forecast import build_horizons, build_basal_drift

from diabetic.telegram_bot.decision_matrix import (
    Alert,
    AlertReservation,
    AlertSeverity,
    CircuitBreaker,
    DecisionMatrix,
)
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
        self.last_provider_meal: Optional[MealEvent] = None
        self.last_provider_insulin: Optional[InsulinDose] = None
        self.treatment_fetch_state = "waiting"
        self.treatment_source: Optional[str] = None
        self.treatment_fetched_at: Optional[datetime] = None
        self.treatment_degraded_reason: Optional[str] = None
        self.meal_window_start: Optional[datetime] = None
        self.meal_tune_pending: bool = False
        self.actual_meal_peak: float = 0.0  # FIX C2: Tracks Highest Observed Glucose value during meal window

        # FIX L1: store the twin's predicted peak at meal-log time so auto_tune
        # compares actual glucose against the real 4h meal prediction, not
        # snapshot.predict_30m which is a short-horizon kinematic value.
        self.pending_meal_forecast_peak: Optional[float] = None

        # O1: Consolidated Tactical Forecaster (physiology-aware)
        self.forecaster = TacticalForecaster(
            age=config.PATIENT_AGE,
            weight_kg=config.PATIENT_WEIGHT_KG
        )

        self.is_running = False
        self._initialized = True
        
        # Live readings are idempotent before they can mutate clinical state. Overflow
        # moves durably marked events to bounded reconciliation rather than dropping them.
        self.ingestion_buffer = GlucoseEventBuffer(
            maxsize=120,
            processed_capacity=medical_constants.SNAPSHOT_CAP * 4,
        )
        self.worker_task: Optional[asyncio.Task] = None
        self._worker_failure: Optional[asyncio.Future] = None

        return self

    async def _worker_loop(self):
        """Process one event once; unknown partial failures stop the runtime."""
        self.logger.info("Coordinator ingestion worker loop started.")
        while True:
            event: Optional[BufferedGlucoseEvent] = None
            try:
                event = await self.ingestion_buffer.get()
                await self._process_reading(event.reading)
                await self.ingestion_buffer.complete(event)
                if event.gap_id is not None:
                    await self._record_gap_event(
                        {
                            "gap_id": event.gap_id,
                            "state": "replayed",
                            "source": event.key.source,
                        }
                    )
            except asyncio.CancelledError:
                if event is not None:
                    try:
                        await asyncio.shield(
                            asyncio.wait_for(
                                self.ingestion_buffer.fail(
                                    event,
                                    reason="processing_cancelled",
                                    write_gap=self._record_gap_event,
                                ),
                                timeout=5.0,
                            )
                        )
                    except Exception as error:
                        self.logger.critical(
                            "Could not durably mark cancelled glucose work: %s",
                            error.__class__.__name__,
                        )
                self.logger.info("Coordinator ingestion worker shut down.")
                raise
            except Exception as error:
                try:
                    if event is not None:
                        await self.ingestion_buffer.fail(
                            event,
                            reason="processing_failed",
                            write_gap=self._record_gap_event,
                        )
                except Exception as marker_error:
                    await self.mark_failed()
                    self._signal_worker_failure(marker_error)
                    raise marker_error from error
                await self.mark_failed()
                self._signal_worker_failure(error)
                self.logger.error(
                    "Fatal glucose processing failure: %s",
                    error.__class__.__name__,
                )
                raise

    def _signal_worker_failure(self, error: BaseException) -> None:
        future = getattr(self, "_worker_failure", None)
        if future is not None and not future.done():
            future.set_exception(error)

    async def _wait_for_poll_interval(self, seconds: float) -> None:
        """Sleep until the next poll unless the critical worker fails first."""
        worker_failure = self._worker_failure
        if worker_failure is None:
            await asyncio.sleep(seconds)
            return
        sleep_task = asyncio.create_task(asyncio.sleep(seconds))
        try:
            done, _ = await asyncio.wait(
                {sleep_task, worker_failure},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if worker_failure in done:
                sleep_task.cancel()
                await asyncio.gather(sleep_task, return_exceptions=True)
                await worker_failure
            await sleep_task
        finally:
            if not sleep_task.done():
                sleep_task.cancel()
                await asyncio.gather(sleep_task, return_exceptions=True)

    async def _record_gap_event(self, payload: dict) -> bool:
        """Persist reconciliation state before live coalescing can continue."""
        try:
            result = await self.audit.record_glucose_gap(payload)
            return result.durable
        except Exception as error:
            self.logger.error(
                "Glucose gap audit degraded: %s", error.__class__.__name__
            )
            return False

    async def _admit_live_reading(self, reading: GlucoseReading):
        if not self.is_running or self._lifecycle_state != "running":
            raise RuntimeError("runtime is not accepting live glucose events")
        result = await self.ingestion_buffer.offer(
            reading,
            write_gap=self._record_gap_event,
        )
        if result.action != "enqueued":
            self.logger.info(
                "Glucose event admission=%s source=%s",
                result.action,
                result.key.source if result.key is not None else reading.source,
            )
        return result

    async def _reconcile_pending_gaps(
        self,
        warmup_readings: List[GlucoseReading],
    ) -> None:
        """Resolve durable restart gaps only when verified history covers their range."""
        pending = await self.audit.get_pending_glucose_gaps()
        covered_keys = {
            (canonical_event_source(reading.source), reading.source_event_id)
            for reading in warmup_readings
            if reading.source_event_id is not None
        }
        for gap in pending:
            source = gap.get("source")
            from_event_id = gap.get("from_event_id")
            through_event_id = gap.get("through_event_id")
            if (
                (source, from_event_id) in covered_keys
                and (source, through_event_id) in covered_keys
            ):
                await self._record_gap_event(
                    {
                        "gap_id": gap["gap_id"],
                        "state": "replayed",
                        "source": gap["source"],
                        "through_event_id": through_event_id,
                    }
                )

# =============================================================================
# 📡 [DATA SYNTHESIS PIPELINE]
# =Focus: Signal Quality, Smoothing (Kalman), and Multi-Stream Ingestion
# =============================================================================
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

    async def _warm_snapshot(self, reading: GlucoseReading) -> bool:
        """Rebuild ordered filter state without live provider or alert side effects."""
        history = [snapshot.glucose for snapshot in self.snapshots] + [reading]
        if SignalQuality.is_compression_low(history):
            return False
        if SignalQuality.is_compression_spike(history):
            return False

        snapshot = self.filter.update(reading)
        snapshot.atr_14 = MetabolicMath.calculate_atr(
            list(self.snapshots) + [snapshot], period=14
        )
        confidence_history = [
            (item.glucose.timestamp, item.glucose.value)
            for item in (list(self.snapshots) + [snapshot])[-18:]
        ]
        snapshot.confidence_index = compute_confidence_index(
            confidence_history,
            reference_time=reading.timestamp,
        )
        self.snapshots.append(snapshot)
        self.regime_step_count += 1
        return await self.ingestion_buffer.record_warmup(reading)

    async def _process_reading(self, reading: GlucoseReading, is_backfill: bool = False):
        """Standard processing pipeline for a single reading."""
        if is_backfill:
            return await self._warm_snapshot(reading)

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
                if (
                    hr_res is not None
                    and hr_res.provenance == "real"
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
                persist_task = asyncio.create_task(
                    self.mongo.save_environment_reading(we_res)
                )
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
        full_history = list(self.snapshots) + [snapshot]
        snapshot.atr_14 = MetabolicMath.calculate_atr(full_history, period=14)
        points_90m = int(90 / medical_constants.SAMPLING_INTERVAL_MINS)
        confidence_history: list[tuple[datetime, float]] = [
            (item.glucose.timestamp, item.glucose.value)
            for item in full_history[-points_90m:]
        ]
        raw_confidence = compute_confidence_index(
            confidence_history,
            reference_time=reading_ts,
        )
        snapshot.confidence_index = raw_confidence

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
        raw_history: list[tuple[datetime, float]] = [
            (item.glucose.timestamp, item.glucose.value)
            for item in full_history[-points_1h:]
        ]
        tactical = self.forecaster.compute(raw_history)
        snapshot.predict_15m = tactical["p15m"]
        snapshot.predict_60m = tactical["p60m"]
        snapshot.velocity_score = tactical["velocity"]

        # 5c. Context Classification
        snapshot.activity_label = classify_context(snapshot).value

        # 6. Alert Decision
        # Guard: filtered_value < 0.5 indicates an uninitialized snapshot — skip alerting.
        # Strategy: Skip alerting during backfill/sync.
        if snapshot.filtered_value < 0.5:
            self.logger.warning("Skipping alert: filtered_value not yet initialized.")
            self.snapshots.append(snapshot)
            return
        try:
            alert = await self.alert_guard.evaluate(snapshot, prediction_30m, self.audit)
            if alert:
                reservation = self.circuit_breaker.reserve(
                    alert.type, alert.alert_id, severity=alert.severity
                )
                if reservation is not None:
                    await self._dispatch_alert(alert, reservation)
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
                reservation = self.circuit_breaker.reserve(
                    emergency_alert.type,
                    emergency_alert.alert_id,
                    severity=emergency_alert.severity,
                )
                if reservation is not None:
                    await self._dispatch_alert(emergency_alert, reservation)


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

    async def _dispatch_alert(
        self,
        alert: Alert,
        reservation: AlertReservation,
    ):
        """Attempt delivery and commit cooldown only after provider acceptance."""
        attempt_durable = False
        try:
            attempt = await self.audit.log_event(
                "ALERT_ATTEMPTED",
                {
                    "alert_id": alert.alert_id,
                    "alert_type": alert.type,
                    "severity": alert.severity.value,
                },
                level="WARNING",
            )
            attempt_durable = attempt.durable
        except Exception as error:
            self.logger.error(
                "Alert attempt audit degraded: %s", error.__class__.__name__
            )
        try:
            result = await self.notifier.send_alert(alert)
        except asyncio.CancelledError:
            self.circuit_breaker.release(reservation)
            raise
        outcome = {
            "alert_id": alert.alert_id,
            "alert_type": alert.type,
            "state": result.state,
            "attempts": result.attempts,
            "reason": result.reason,
            "provider_message_id": result.message_id,
            "attempt_audit_durable": attempt_durable,
        }
        if result.accepted:
            self.circuit_breaker.commit(reservation)
            delivered_durable = False
            try:
                delivered = await self.audit.log_event(
                    "ALERT_DELIVERED", outcome, level="WARNING"
                )
                delivered_durable = delivered.durable
            except Exception as error:
                self.logger.error(
                    "Delivered alert audit degraded: %s",
                    error.__class__.__name__,
                )
            if delivered_durable:
                self.logger.error(
                    "ALERT DELIVERED: type=%s alert_id=%s",
                    alert.type,
                    alert.alert_id,
                )
            else:
                self.logger.error(
                    "ALERT ACCEPTED BUT AUDIT DEGRADED: type=%s alert_id=%s",
                    alert.type,
                    alert.alert_id,
                )
            return result

        self.circuit_breaker.release(reservation)
        try:
            await self.audit.log_event(
                "ALERT_UNDELIVERED", outcome, level="ERROR"
            )
        except Exception as error:
            self.logger.error(
                "Undelivered alert audit degraded: %s",
                error.__class__.__name__,
            )
        self.logger.error(
            "ALERT UNDELIVERED: type=%s alert_id=%s state=%s",
            alert.type,
            alert.alert_id,
            result.state,
        )
        return result

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
        """Poll Nightscout after the process supervisor claims startup."""
        await self._require_start_claim()
        self.is_running = True
        self.logger.info(f"Coordinator started in LIVE mode (Interval: {config.DATA_POLLING_INTERVAL}s)")

        task_hud = asyncio.create_task(self.hud.run_live(self))
        self.background_tasks.add(task_hud)
        task_hud.add_done_callback(self.background_tasks.discard)

        # The ingestion worker is critical and supervised separately from optional tasks.
        self._worker_failure = asyncio.get_running_loop().create_future()
        self.worker_task = asyncio.create_task(self._worker_loop())

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
                # Match Mongo's bounded recovery window; only the latest 35 unique
                # events are loaded into memory after reconciliation coverage is checked.
                backfill_readings = await self.client.fetch_recent_glucose(count=288)
                
            warmup_readings = prepare_warmup_readings(
                backfill_readings,
                limit=35,
            )
            if warmup_readings:
                self.logger.info(
                    "Filling %s ordered unique historical readings to internal memory...",
                    len(warmup_readings),
                )
                replayed_readings = []
                for reading in warmup_readings:
                    if await self._process_reading(reading, is_backfill=True):
                        replayed_readings.append(reading)
                await self._reconcile_pending_gaps(replayed_readings)

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
                        await self._admit_live_reading(reading)
            except (ValueError, ConnectionError) as e:
                # Only crash if both backends fail with fatal Auth errors
                if ("URL" in str(e) or "token" in str(e).lower() or "Unauthorized" in str(e)) and self.mongo.entries is None:
                    self.logger.error(f"FATAL ERROR: {e}. Shutting down.")
                    self.is_running = False
                    raise SystemExit(1)
                self.logger.error(f"Polling failure: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")

            await self._wait_for_poll_interval(config.DATA_POLLING_INTERVAL)

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
        """Idempotently stop every resource owned by this process runtime."""
        async with self._lifecycle_lock:
            if self._shutdown_complete or self._lifecycle_state == "stopping":
                return
            failed = self._lifecycle_state == "failed"
            self._lifecycle_state = "stopping"
            self.is_running = False

        logger = getattr(self, "logger", logging.getLogger("Bio-Quant.Coordinator"))
        logger.info("Coordinator shutting down...")

        from diabetic.telegram_bot.twa_api import clear_api_coordinator

        clear_api_coordinator(self)

        scheduler_task = getattr(self, "_scheduler_task", None)
        if scheduler_task is not None:
            logger.info("Cancelling Autonomous Scheduler task...")
            scheduler_task.cancel()
            await asyncio.gather(scheduler_task, return_exceptions=True)
            self._scheduler_task = None

        worker_task = getattr(self, "worker_task", None)
        if worker_task is not None:
            if not worker_task.done():
                worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)
            self.worker_task = None
        worker_failure = getattr(self, "_worker_failure", None)
        if worker_failure is not None:
            if worker_failure.done() and not worker_failure.cancelled():
                worker_failure.exception()
            elif not worker_failure.done():
                worker_failure.cancel()
            self._worker_failure = None

        background_tasks = getattr(self, "background_tasks", set())
        for task in list(background_tasks):
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
            background_tasks.clear()

        bot_app = getattr(self, "bot_app", None)
        if (
            bot_app
            and bot_app.app.updater
            and bot_app.app.updater.running
        ):
            await bot_app.app.updater.stop()
            await bot_app.app.stop()
            await bot_app.app.shutdown()

        for name in ("client", "mongo", "weather_client"):
            resource = getattr(self, name, None)
            close = getattr(resource, "close", None)
            if close is not None:
                await close()
        await close_storage_db()

        async with self._lifecycle_lock:
            self._shutdown_complete = True
            self._lifecycle_state = "failed" if failed else "stopped"
        logger.info("Coordinator shutdown complete.")

async def _run_standalone() -> None:
    coordinator = Coordinator()
    try:
        coordinator = await Coordinator.create()
        await coordinator.begin_start()
        await coordinator.start_live_mode()
    except BaseException:
        await coordinator.mark_failed()
        raise
    finally:
        await coordinator.shutdown()


if __name__ == "__main__":
    asyncio.run(_run_standalone())
