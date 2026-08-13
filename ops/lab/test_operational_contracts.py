"""Regression gates for freshness, timestamps, and atomic model promotion."""

import tempfile
import unittest
import hashlib
import json
import os
from contextlib import ExitStack
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

    async def test_hud_and_forecast_convert_only_at_presentation(self):
        from diabetic.config import config
        from diabetic.telegram_bot import twa_api

        timestamp = datetime.now(timezone.utc)
        snapshot = MetabolicSnapshot(
            glucose=GlucoseReading(timestamp=timestamp, value=5.5, trend="Flat"),
            filtered_value=5.5,
            velocity=-0.1,
        )
        twa_api.COORDINATOR_REF = SimpleNamespace(
            snapshots=[snapshot],
            treatment_fetch_state="ok",
            last_prediction_4h=[5.5, 6.0],
            last_prediction_1d=[5.0],
        )

        with patch.object(config, "PREFER_MMOL", False):
            state = await twa_api.get_hud_data()
            forecast = await twa_api.get_forecast()

        self.assertEqual(state.unit, "mg/dL")
        self.assertEqual(state.decimal_places, 0)
        self.assertAlmostEqual(state.glucose, 5.5 * medical_constants.MMOL_TO_MGDL)
        self.assertAlmostEqual(state.velocity, -0.1 * medical_constants.MMOL_TO_MGDL)
        self.assertEqual(state.range_state, "in_range")
        self.assertFalse(state.haptic_warning)
        self.assertEqual(forecast["unit"], "mg/dL")
        self.assertEqual(
            forecast["horizon"],
            [
                5.5 * medical_constants.MMOL_TO_MGDL,
                6.0 * medical_constants.MMOL_TO_MGDL,
            ],
        )
        self.assertEqual(snapshot.filtered_value, 5.5)
        self.assertEqual(snapshot.glucose.unit, "mmol/L")

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


class TestPresentationOwnership(unittest.TestCase):
    def test_browser_uses_server_range_and_unit_contract(self):
        root = Path(__file__).resolve().parents[2]
        dashboard = (root / "twa" / "assets" / "dashboard.js").read_text(
            encoding="utf-8"
        )
        history = (root / "twa" / "assets" / "history.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("data.range_state", dashboard)
        self.assertIn("data.haptic_warning", dashboard)
        self.assertIn("data.unit", dashboard)
        self.assertLess(
            dashboard.index('document.getElementById("glucose-unit")'),
            dashboard.index("if (!data.ready"),
        )
        self.assertIn("data.unit", history)
        self.assertNotIn("data.glucose < 4.0", dashboard)
        self.assertNotIn("data.glucose > 13.0", dashboard)
        self.assertNotIn("18.018", dashboard)
        self.assertNotIn("18.018", history)


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
    async def asyncSetUp(self):
        from diabetic.coordinator import Coordinator

        self.previous_coordinator = Coordinator._instance
        Coordinator._instance = None

    async def asyncTearDown(self):
        from diabetic.coordinator import Coordinator

        Coordinator._instance = self.previous_coordinator

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

    @staticmethod
    def _promoted_manifest(content: bytes) -> dict:
        return {
            "status": "promoted",
            "sha256": hashlib.sha256(content).hexdigest(),
            "version": "v15",
        }

    async def _run_pipeline(self, deployed: Path, *, patches=()):
        from diabetic.config import config
        from diabetic.ml_engine import training_service

        async def fake_train(**kwargs):
            return self._fake_training_result(kwargs["output_path"])

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(config, "ML_WEIGHTS_PATH", str(deployed))
            )
            stack.enter_context(
                patch.object(
                    training_service,
                    "train_metabolic_cnn",
                    AsyncMock(side_effect=fake_train),
                )
            )
            for patcher in patches:
                stack.enter_context(patcher)
            return await training_service.run_training_pipeline(
                source="mongo",
                epochs=1,
            )

    def _assert_authoritative_old(self, deployed: Path, old_manifest: dict):
        state_dir = deployed.parent / ".training"
        self.assertEqual(deployed.read_bytes(), b"last-known-good")
        self.assertEqual(
            json.loads((state_dir / "manifest.json").read_text(encoding="utf-8")),
            old_manifest,
        )
        self.assertFalse((state_dir / "promotion.json").exists())

    async def test_valid_candidate_commits_matching_artifact_and_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            deployed = Path(temporary) / "weights.pth"
            deployed.write_bytes(b"last-known-good")
            old_manifest = self._promoted_manifest(b"last-known-good")
            state_dir = deployed.parent / ".training"
            state_dir.mkdir()
            (state_dir / "manifest.json").write_text(
                json.dumps(old_manifest), encoding="utf-8"
            )

            result = await self._run_pipeline(deployed)

            manifest = json.loads(
                (state_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result["status"], "promoted")
            self.assertEqual(deployed.read_bytes(), b"new-candidate")
            self.assertEqual(manifest["sha256"], hashlib.sha256(b"new-candidate").hexdigest())
            self.assertFalse((state_dir / "promotion.json").exists())

    async def test_backup_failure_leaves_authoritative_version_unchanged(self):
        from diabetic.ml_engine import training_service

        with tempfile.TemporaryDirectory() as temporary:
            deployed = Path(temporary) / "weights.pth"
            deployed.write_bytes(b"last-known-good")
            old_manifest = self._promoted_manifest(b"last-known-good")
            state_dir = deployed.parent / ".training"
            state_dir.mkdir()
            (state_dir / "manifest.json").write_text(
                json.dumps(old_manifest), encoding="utf-8"
            )
            original_copy = training_service._atomic_copy

            def fail_artifact_backup(source, destination):
                if destination.name == "last_known_good.pth":
                    raise OSError("synthetic backup failure")
                return original_copy(source, destination)

            result = await self._run_pipeline(
                deployed,
                patches=(patch.object(training_service, "_atomic_copy", side_effect=fail_artifact_backup),),
            )

            self.assertEqual(result["status"], "failed")
            self._assert_authoritative_old(deployed, old_manifest)

    async def test_prepare_journal_failure_leaves_authoritative_version_unchanged(self):
        from diabetic.ml_engine import training_service

        with tempfile.TemporaryDirectory() as temporary:
            deployed = Path(temporary) / "weights.pth"
            deployed.write_bytes(b"last-known-good")
            old_manifest = self._promoted_manifest(b"last-known-good")
            state_dir = deployed.parent / ".training"
            state_dir.mkdir()
            (state_dir / "manifest.json").write_text(
                json.dumps(old_manifest), encoding="utf-8"
            )
            original_json = training_service._atomic_json

            def fail_journal(path, payload):
                if path.name == "promotion.json":
                    raise OSError("synthetic journal failure")
                return original_json(path, payload)

            result = await self._run_pipeline(
                deployed,
                patches=(patch.object(training_service, "_atomic_json", side_effect=fail_journal),),
            )

            self.assertEqual(result["status"], "failed")
            self._assert_authoritative_old(deployed, old_manifest)

    async def test_replace_reload_and_manifest_boundaries_restore_old_version(self):
        from diabetic.coordinator import Coordinator
        from diabetic.ml_engine import training_service

        boundaries = ("replace", "reload", "manifest_write", "manifest_replace")
        for boundary in boundaries:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temporary:
                deployed = Path(temporary) / "weights.pth"
                deployed.write_bytes(b"last-known-good")
                old_manifest = self._promoted_manifest(b"last-known-good")
                state_dir = deployed.parent / ".training"
                state_dir.mkdir()
                (state_dir / "manifest.json").write_text(
                    json.dumps(old_manifest), encoding="utf-8"
                )
                runner = SimpleNamespace(
                    weights_loaded=True,
                    reload_weights=MagicMock(return_value=True),
                )
                Coordinator._instance = SimpleNamespace(neural_runner=runner)
                patches = []
                if boundary == "replace":
                    patches.append(
                        patch.object(
                            training_service,
                            "_promote_candidate",
                            side_effect=OSError("synthetic replace failure"),
                        )
                    )
                elif boundary == "reload":
                    runner.reload_weights.side_effect = [False, True]
                elif boundary == "manifest_write":
                    original_json = training_service._atomic_json

                    def fail_manifest_write(path, payload):
                        if path.name == "manifest.json":
                            raise OSError("synthetic manifest write failure")
                        return original_json(path, payload)

                    patches.append(
                        patch.object(
                            training_service,
                            "_atomic_json",
                            side_effect=fail_manifest_write,
                        )
                    )
                else:
                    original_replace = os.replace
                    failed = False

                    def fail_manifest_replace(source, destination):
                        nonlocal failed
                        if Path(destination).name == "manifest.json" and not failed:
                            failed = True
                            raise OSError("synthetic manifest rename failure")
                        return original_replace(source, destination)

                    patches.append(patch("os.replace", side_effect=fail_manifest_replace))

                entered = [item.__enter__() for item in patches]
                try:
                    result = await self._run_pipeline(deployed)
                finally:
                    for item in reversed(patches):
                        item.__exit__(None, None, None)

                self.assertEqual(result["status"], "failed")
                self._assert_authoritative_old(deployed, old_manifest)
                self.assertTrue(runner.weights_loaded)

    async def test_first_promotion_failure_restores_no_model_state(self):
        from diabetic.coordinator import Coordinator

        with tempfile.TemporaryDirectory() as temporary:
            deployed = Path(temporary) / "weights.pth"
            runner = SimpleNamespace(
                weights_loaded=True,
                reload_weights=MagicMock(return_value=False),
            )
            Coordinator._instance = SimpleNamespace(neural_runner=runner)

            result = await self._run_pipeline(deployed)

            state_dir = deployed.parent / ".training"
            self.assertEqual(result["status"], "failed")
            self.assertFalse(deployed.exists())
            self.assertFalse((state_dir / "manifest.json").exists())
            self.assertFalse((state_dir / "promotion.json").exists())
            self.assertFalse(runner.weights_loaded)

    async def test_manifest_fsync_and_commit_journal_failure_restore_old_version(self):
        from diabetic.ml_engine import training_service

        boundaries = ("manifest_fsync", "commit_journal")
        for boundary in boundaries:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temporary:
                deployed = Path(temporary) / "weights.pth"
                deployed.write_bytes(b"last-known-good")
                old_manifest = self._promoted_manifest(b"last-known-good")
                state_dir = deployed.parent / ".training"
                state_dir.mkdir()
                (state_dir / "manifest.json").write_text(
                    json.dumps(old_manifest), encoding="utf-8"
                )
                original_json = training_service._atomic_json

                if boundary == "manifest_fsync":
                    original_fsync_dir = training_service._fsync_directory

                    def fail_manifest_fsync(path):
                        if (
                            path == state_dir
                            and (state_dir / "manifest.json").exists()
                            and json.loads((state_dir / "manifest.json").read_text())["sha256"]
                            == hashlib.sha256(b"new-candidate").hexdigest()
                        ):
                            raise OSError("synthetic manifest fsync failure")
                        return original_fsync_dir(path)

                    patcher = patch.object(
                        training_service,
                        "_fsync_directory",
                        side_effect=fail_manifest_fsync,
                    )
                else:
                    calls = 0

                    def fail_commit_journal(path, payload):
                        nonlocal calls
                        if path.name == "promotion.json":
                            calls += 1
                            if calls == 2:
                                raise OSError("synthetic commit journal failure")
                        return original_json(path, payload)

                    patcher = patch.object(
                        training_service,
                        "_atomic_json",
                        side_effect=fail_commit_journal,
                    )

                with patcher:
                    result = await self._run_pipeline(deployed)

                self.assertEqual(result["status"], "failed")
                self._assert_authoritative_old(deployed, old_manifest)

    async def test_cleanup_failure_reports_committed_promotion(self):
        from diabetic.ml_engine import training_service

        with tempfile.TemporaryDirectory() as temporary:
            deployed = Path(temporary) / "weights.pth"
            deployed.write_bytes(b"last-known-good")
            state_dir = deployed.parent / ".training"
            state_dir.mkdir()
            (state_dir / "manifest.json").write_text(
                json.dumps(self._promoted_manifest(b"last-known-good")),
                encoding="utf-8",
            )

            result = await self._run_pipeline(
                deployed,
                patches=(
                    patch.object(
                        training_service,
                        "_cleanup_transaction",
                        side_effect=OSError("synthetic cleanup failure"),
                    ),
                ),
            )

            manifest = json.loads((state_dir / "manifest.json").read_text())
            self.assertEqual(result["status"], "promoted")
            self.assertEqual(deployed.read_bytes(), b"new-candidate")
            self.assertEqual(manifest["sha256"], result["sha256"])
            self.assertTrue((state_dir / "promotion.json").exists())

    async def test_restart_rolls_back_prepared_transaction(self):
        from diabetic.ml_engine import training_service

        with tempfile.TemporaryDirectory() as temporary:
            deployed = Path(temporary) / "weights.pth"
            deployed.write_bytes(b"new-candidate")
            paths = training_service.PromotionPaths.for_deployed(deployed)
            paths.state_dir.mkdir()
            paths.backup.write_bytes(b"last-known-good")
            old_manifest = self._promoted_manifest(b"last-known-good")
            paths.manifest_backup.write_text(json.dumps(old_manifest), encoding="utf-8")
            paths.manifest.write_text(
                json.dumps(self._promoted_manifest(b"new-candidate")), encoding="utf-8"
            )
            paths.journal.write_text(
                json.dumps(
                    {
                        "state": "prepared",
                        "candidate_sha256": hashlib.sha256(b"new-candidate").hexdigest(),
                        "previous_exists": True,
                        "previous_sha256": hashlib.sha256(b"last-known-good").hexdigest(),
                        "previous_manifest_exists": True,
                    }
                ),
                encoding="utf-8",
            )

            state = training_service.recover_training_state(deployed)

            self.assertEqual(state, "rolled_back")
            self._assert_authoritative_old(deployed, old_manifest)

    async def test_restart_keeps_durably_committed_transaction(self):
        from diabetic.ml_engine import training_service

        with tempfile.TemporaryDirectory() as temporary:
            deployed = Path(temporary) / "weights.pth"
            deployed.write_bytes(b"new-candidate")
            paths = training_service.PromotionPaths.for_deployed(deployed)
            paths.state_dir.mkdir()
            manifest = self._promoted_manifest(b"new-candidate")
            paths.manifest.write_text(json.dumps(manifest), encoding="utf-8")
            paths.journal.write_text(
                json.dumps(
                    {
                        "state": "committed",
                        "candidate_sha256": manifest["sha256"],
                        "previous_exists": False,
                        "previous_manifest_exists": False,
                    }
                ),
                encoding="utf-8",
            )

            state = training_service.recover_training_state(deployed)

            self.assertEqual(state, "committed")
            self.assertEqual(deployed.read_bytes(), b"new-candidate")
            self.assertEqual(json.loads(paths.manifest.read_text()), manifest)
            self.assertFalse(paths.journal.exists())

    async def test_inference_startup_fails_closed_when_recovery_fails(self):
        from diabetic.config import config
        from diabetic.ml_engine import inference, training_service

        with tempfile.TemporaryDirectory() as temporary:
            deployed = Path(temporary) / "weights.pth"
            deployed.write_bytes(b"untrusted")
            with (
                patch.object(config, "ML_WEIGHTS_PATH", str(deployed)),
                patch.object(
                    training_service,
                    "recover_training_state",
                    side_effect=RuntimeError("synthetic recovery failure"),
                ),
                patch.object(inference.torch, "load") as load,
            ):
                runner = inference.MetabolicInferenceRunner()

        self.assertFalse(runner.weights_loaded)
        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
