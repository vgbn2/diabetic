"""Regression gates for freshness, timestamps, and atomic model promotion."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from diabetic.ingestion.timestamps import treatment_timestamp
from diabetic.ml_engine.train import TrainingResult
from diabetic.registry import GlucoseReading, MetabolicSnapshot


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
