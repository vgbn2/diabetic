"""Regression gates for freshness, timestamps, and atomic model promotion."""

import tempfile
import unittest
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from diabetic import medical_constants
from diabetic.ingestion.timestamps import treatment_timestamp
from diabetic.ml_engine.train import TrainingResult
from diabetic.registry import (
    GlucoseReading,
    InsulinDose,
    MealEvent,
    MetabolicSnapshot,
    TreatmentFetchResult,
)


class TestTreatmentTimestamp(unittest.TestCase):
    def test_supported_nightscout_timestamp_shapes(self):
        expected = datetime(2026, 6, 1, tzinfo=timezone.utc)
        millis = int(expected.timestamp() * 1000)
        self.assertEqual(treatment_timestamp({"mills": millis}), expected)
        self.assertEqual(treatment_timestamp({"created_at": expected}), expected)
        self.assertEqual(
            treatment_timestamp({"created_at": "2026-06-01T00:00:00Z"}),
            expected,
        )

    def test_invalid_timestamp_is_not_guessed(self):
        self.assertIsNone(treatment_timestamp({}))
        self.assertIsNone(treatment_timestamp({"created_at": "not-a-date"}))


class TestHudFreshness(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        from diabetic.telegram_bot import twa_api

        twa_api.COORDINATOR_REF = None

    async def test_waiting_is_nullable_not_zero(self):
        from diabetic.telegram_bot import twa_api

        twa_api.COORDINATOR_REF = None
        state = await twa_api.get_hud_data()
        self.assertEqual(state.state, "waiting")
        self.assertIsNone(state.glucose)
        self.assertFalse(state.ready)

    async def test_stale_snapshot_is_not_ready(self):
        from diabetic.config import config
        from diabetic.telegram_bot import twa_api

        timestamp = datetime.now(timezone.utc) - timedelta(
            seconds=config.HUD_STALE_AFTER_SECS + 1
        )
        snapshot = MetabolicSnapshot(
            glucose=GlucoseReading(timestamp=timestamp, value=8.2, trend="Flat"),
            filtered_value=8.2,
        )
        twa_api.COORDINATOR_REF = SimpleNamespace(snapshots=[snapshot])
        state = await twa_api.get_hud_data()
        self.assertEqual(state.state, "stale")
        self.assertFalse(state.ready)
        self.assertEqual(state.glucose, 8.2)

    async def test_treatment_failure_marks_fresh_hud_degraded(self):
        from diabetic.telegram_bot import twa_api

        snapshot = MetabolicSnapshot(
            glucose=GlucoseReading(
                timestamp=datetime.now(timezone.utc),
                value=8.2,
                trend="Flat",
            ),
            filtered_value=8.2,
        )
        twa_api.COORDINATOR_REF = SimpleNamespace(
            snapshots=[snapshot],
            treatment_fetch_state="degraded",
        )
        state = await twa_api.get_hud_data()
        self.assertEqual(state.state, "degraded")
        self.assertFalse(state.ready)
        self.assertIn("treatment_provider_degraded", state.degraded_reasons)


class TestTreatmentState(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from diabetic.coordinator import Coordinator

        self._previous = Coordinator._instance
        Coordinator._instance = None
        self.coordinator = Coordinator()
        self.coordinator.logger = MagicMock()
        self.coordinator.last_meal = None
        self.coordinator.last_provider_meal = None
        self.coordinator.last_provider_insulin = None
        self.coordinator.treatment_fetch_state = "waiting"
        self.coordinator.treatment_source = None
        self.coordinator.treatment_fetched_at = None
        self.coordinator.treatment_degraded_reason = None

    def tearDown(self):
        from diabetic.coordinator import Coordinator

        Coordinator._instance = self._previous

    @staticmethod
    def _snapshot() -> MetabolicSnapshot:
        return MetabolicSnapshot(
            glucose=GlucoseReading(
                timestamp=datetime.now(timezone.utc),
                value=7.0,
                trend="Flat",
            )
        )

    async def test_mongo_degradation_falls_back_to_nightscout(self):
        fallback = TreatmentFetchResult(source="nightscout", state="ok")
        self.coordinator.mongo = SimpleNamespace(
            treatments=object(),
            fetch_recent_treatments=AsyncMock(
                return_value=TreatmentFetchResult(
                    source="mongo",
                    state="degraded",
                    error_reason="TimeoutError",
                )
            ),
        )
        self.coordinator.client = SimpleNamespace(
            fetch_recent_treatments=AsyncMock(return_value=fallback)
        )

        result = await self.coordinator._fetch_recent_treatments()

        self.assertIs(result, fallback)
        self.coordinator.client.fetch_recent_treatments.assert_awaited_once()

    async def test_degraded_fetch_retains_only_active_last_known_good(self):
        now = datetime.now(timezone.utc)
        insulin = InsulinDose(timestamp=now - timedelta(minutes=30), units=2.0, type="RAPID")
        meal = MealEvent(timestamp=now - timedelta(minutes=30), carbs=25.0)
        initial = self._snapshot()
        self.coordinator._apply_treatment_result(
            initial,
            TreatmentFetchResult(
                source="mongo",
                state="ok",
                insulin=[insulin],
                meals=[meal],
            ),
        )

        degraded = self._snapshot()
        self.coordinator._apply_treatment_result(
            degraded,
            TreatmentFetchResult(
                source="mongo+nightscout",
                state="degraded",
                error_reason="all_treatment_providers_degraded",
            ),
        )

        self.assertEqual(degraded.last_insulin, insulin)
        self.assertEqual(degraded.last_meal, meal)
        self.assertEqual(self.coordinator.treatment_fetch_state, "degraded")

        self.coordinator.last_provider_insulin = insulin.model_copy(
            update={
                "timestamp": now
                - timedelta(
                    minutes=medical_constants.INSULIN_ACTION_WINDOW_MINS + 1
                )
            }
        )
        self.coordinator.last_provider_meal = meal.model_copy(
            update={
                "timestamp": now
                - timedelta(minutes=medical_constants.MEAL_WINDOW_MINS + 1)
            }
        )
        expired = self._snapshot()
        self.coordinator._apply_treatment_result(
            expired,
            TreatmentFetchResult(source="nightscout", state="degraded"),
        )
        self.assertIsNone(expired.last_insulin)
        self.assertIsNone(expired.last_meal)

    async def test_valid_empty_result_clears_provider_cache(self):
        now = datetime.now(timezone.utc)
        self.coordinator.last_provider_insulin = InsulinDose(
            timestamp=now, units=1.0, type="RAPID"
        )
        self.coordinator.last_provider_meal = MealEvent(timestamp=now, carbs=10.0)
        snapshot = self._snapshot()

        self.coordinator._apply_treatment_result(
            snapshot,
            TreatmentFetchResult(source="nightscout", state="ok"),
        )

        self.assertIsNone(snapshot.last_insulin)
        self.assertIsNone(snapshot.last_meal)


class TestRuntimeReadiness(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        from diabetic.coordinator import Coordinator

        Coordinator._instance = None

    async def _health(
        self,
        temporary: str,
        timestamp: datetime,
        *,
        loaded: bool,
        size: int,
        nightscout: str = "ok",
        mongodb: str = "ok",
        weight_age_days: int = 0,
    ):
        from diabetic.config import config
        from diabetic.coordinator import Coordinator
        from diabetic.utils import health as health_module

        weight = Path(temporary) / "weights.pth"
        weight.write_bytes(b"verified-weight")
        modified = datetime.now(timezone.utc) - timedelta(days=weight_age_days)
        os.utime(weight, (modified.timestamp(), modified.timestamp()))
        digest = hashlib.sha256(weight.read_bytes()).hexdigest()
        snapshot = MetabolicSnapshot(
            glucose=GlucoseReading(timestamp=timestamp, value=7.0, trend="Flat")
        )
        Coordinator._instance = SimpleNamespace(
            _initialized=True,
            snapshots=[snapshot] * size,
            neural_runner=SimpleNamespace(weights_loaded=loaded),
            treatment_fetch_state="ok",
            treatment_source="mongo",
            treatment_fetched_at=datetime.now(timezone.utc),
            treatment_degraded_reason=None,
        )
        with (
            patch.object(config, "ML_WEIGHTS_PATH", str(weight)),
            patch.object(config, "TRAIN_STALE_DAYS", 30),
            patch.object(
                health_module,
                "_nightscout_status",
                AsyncMock(return_value=nightscout),
            ),
            patch.object(
                health_module,
                "_mongo_status",
                AsyncMock(return_value=mongodb),
            ),
            patch(
                "diabetic.ml_engine.training_service.read_training_manifest",
                return_value={"sha256": digest},
            ),
        ):
            return await health_module.get_system_health()

    async def test_core_ready_does_not_require_neural_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            health = await self._health(
                temporary,
                datetime.now(timezone.utc),
                loaded=False,
                size=1,
            )
        self.assertTrue(health["ready"])
        self.assertFalse(health["neural_ready"])
        self.assertIn(
            "inference_weights_not_loaded", health["neural_readiness_reasons"]
        )

    async def test_stale_snapshot_blocks_core_and_neural_readiness(self):
        from diabetic.config import config

        timestamp = datetime.now(timezone.utc) - timedelta(
            seconds=config.HUD_STALE_AFTER_SECS + 1
        )
        with tempfile.TemporaryDirectory() as temporary:
            health = await self._health(
                temporary,
                timestamp,
                loaded=True,
                size=30,
            )
        self.assertFalse(health["ready"])
        self.assertFalse(health["neural_ready"])
        self.assertIn("stale_metabolic_snapshot", health["readiness_reasons"])

    async def test_provider_failure_blocks_core_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            health = await self._health(
                temporary,
                datetime.now(timezone.utc),
                loaded=True,
                size=30,
                nightscout="unreachable",
            )
        self.assertFalse(health["ready"])
        self.assertIn("nightscout_unreachable", health["readiness_reasons"])

    async def test_stale_verified_weights_only_block_neural_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            health = await self._health(
                temporary,
                datetime.now(timezone.utc),
                loaded=True,
                size=30,
                weight_age_days=31,
            )
        self.assertTrue(health["ready"])
        self.assertFalse(health["neural_ready"])
        self.assertIn("ml_weights_stale", health["neural_readiness_reasons"])

    async def test_no_in_process_reading_blocks_core_readiness(self):
        from diabetic.config import config
        from diabetic.coordinator import Coordinator
        from diabetic.utils import health as health_module

        Coordinator._instance = SimpleNamespace(
            _initialized=True,
            snapshots=[],
            neural_runner=SimpleNamespace(weights_loaded=False),
        )
        with (
            patch.object(config, "ML_WEIGHTS_PATH", "/missing/weights.pth"),
            patch.object(
                health_module, "_nightscout_status", AsyncMock(return_value="ok")
            ),
            patch.object(health_module, "_mongo_status", AsyncMock(return_value="ok")),
            patch(
                "diabetic.utils.audit_logger.AuditLogger.get_last_reading_timestamp",
                AsyncMock(return_value=None),
            ),
        ):
            health = await health_module.get_system_health()
        self.assertFalse(health["ready"])
        self.assertIn(
            "coordinator_reading_unavailable", health["readiness_reasons"]
        )

    async def test_readyz_uses_shared_core_readiness(self):
        from diabetic.telegram_bot import twa_api

        with patch(
            "diabetic.utils.health.get_system_health",
            AsyncMock(return_value={"ready": True}),
        ):
            self.assertEqual(await twa_api.readyz(), {"status": "ready"})

        with patch(
            "diabetic.utils.health.get_system_health",
            AsyncMock(return_value={"ready": False}),
        ):
            with self.assertRaises(twa_api.HTTPException) as raised:
                await twa_api.readyz()
        self.assertEqual(raised.exception.status_code, 503)


class TestTemporalNeutrality(unittest.TestCase):
    def test_calendar_context_is_always_neutral(self):
        from diabetic.utils.temporal import temporal_engine

        for timestamp in [
            datetime(2026, 7, 20, tzinfo=timezone.utc),
            datetime(2026, 7, 25, tzinfo=timezone.utc),
            datetime(2026, 9, 25, tzinfo=timezone.utc),
        ]:
            with self.subTest(timestamp=timestamp):
                self.assertEqual(temporal_engine.get_multiplier(timestamp), 1.0)

    def test_static_model_shape_is_preserved_with_neutral_feature(self):
        from diabetic.utils.scaling_engine import scaling_engine

        vector = scaling_engine.assemble_static_vector(
            datetime(2026, 7, 25, tzinfo=timezone.utc)
        )
        self.assertEqual(vector.shape, (15,))
        self.assertEqual(float(vector[11]), 1.0)


class TestAtomicTrainingPromotion(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _fake_training_result(candidate: Path) -> TrainingResult:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(b"new-candidate")
        return TrainingResult(
            model=object(),
            best_validation_loss=0.5,
            sample_count=128,
            artifact_path=candidate,
        )

    async def test_valid_candidate_replaces_deployed_artifact(self):
        from diabetic.config import config
        from diabetic.ml_engine import training_service

        with tempfile.TemporaryDirectory() as temporary:
            deployed = Path(temporary) / "weights.pth"
            deployed.write_bytes(b"old")

            async def fake_train(**kwargs):
                return self._fake_training_result(kwargs["output_path"])

            with (
                patch.object(config, "ML_WEIGHTS_PATH", str(deployed)),
                patch.object(training_service, "train_metabolic_cnn", AsyncMock(side_effect=fake_train)),
            ):
                result = await training_service.run_training_pipeline(
                    source="mongo",
                    epochs=1,
                )

            self.assertEqual(result["status"], "promoted")
            self.assertEqual(deployed.read_bytes(), b"new-candidate")
            self.assertTrue((deployed.parent / ".training" / "manifest.json").exists())

    async def test_failed_reload_restores_last_known_good(self):
        from diabetic.config import config
        from diabetic.coordinator import Coordinator
        from diabetic.ml_engine import training_service

        with tempfile.TemporaryDirectory() as temporary:
            deployed = Path(temporary) / "weights.pth"
            deployed.write_bytes(b"last-known-good")
            runner = SimpleNamespace(reload_weights=lambda _path: False)
            previous_instance = Coordinator._instance
            Coordinator._instance = SimpleNamespace(neural_runner=runner)

            async def fake_train(**kwargs):
                return self._fake_training_result(kwargs["output_path"])

            try:
                with (
                    patch.object(config, "ML_WEIGHTS_PATH", str(deployed)),
                    patch.object(
                        training_service,
                        "train_metabolic_cnn",
                        AsyncMock(side_effect=fake_train),
                    ),
                ):
                    result = await training_service.run_training_pipeline(
                        source="mongo",
                        epochs=1,
                    )
            finally:
                Coordinator._instance = previous_instance

            self.assertEqual(result["status"], "failed")
            self.assertEqual(deployed.read_bytes(), b"last-known-good")


if __name__ == "__main__":
    unittest.main()
