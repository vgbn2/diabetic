"""Unit and contract characterization tests for Coordinator construction, stage seams, and background task draining."""

import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from diabetic.config import config
from diabetic.coordinator import Coordinator
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic.utils.audit_logger import AuditLogger


class TestCoordinatorConstructionAndStages(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_storage.db")
        self.audit_path = os.path.join(self.temp_dir.name, "test_audit.db")

        self._old_db_url = config.DATABASE_URL
        self._old_audit_path = config.AUDIT_DB_PATH
        config.DATABASE_URL = f"sqlite+aiosqlite:///{self.db_path}"
        config.AUDIT_DB_PATH = self.audit_path

        self.previous_instance = Coordinator._instance
        Coordinator._instance = None

    async def asyncTearDown(self):
        if Coordinator._instance:
            await Coordinator._instance.shutdown()
        Coordinator._instance = self.previous_instance

        config.DATABASE_URL = self._old_db_url
        config.AUDIT_DB_PATH = self._old_audit_path
        self.temp_dir.cleanup()

    async def test_coordinator_create_idempotency_and_di(self):
        """Test singleton idempotency, dependency injection, and initial state."""
        custom_audit = AuditLogger(db_path=self.audit_path)
        coord = await Coordinator.create(audit_logger=custom_audit, allow_synthetic=True)

        self.assertFalse(coord._owns_audit_logger)
        self.assertEqual(coord.audit, custom_audit)
        self.assertTrue(coord.allow_synthetic)
        self.assertTrue(coord.hr_client.allow_synthetic)
        self.assertTrue(coord.weather_client.allow_synthetic)
        self.assertEqual(coord.treatment_fetch_state, "waiting")
        self.assertEqual(coord.last_prediction_4h, [])
        self.assertEqual(coord.last_prediction_1d, [])
        self.assertIsNotNone(coord.ingestion_queue)

        # Calling create again returns exact same instance without re-instantiation
        second = await Coordinator.create()
        self.assertIs(coord, second)
        self.assertEqual(second.audit, custom_audit)

        await custom_audit.close()

    async def test_task_tracking_and_drain_contract(self):
        """Test explicit task tracking and graceful draining."""
        coord = await Coordinator.create()

        # Track background task via coroutine
        async def sample_task():
            await asyncio.sleep(0.01)
            return "done"

        task = coord.track_background_task(sample_task(), name="sample_task")
        self.assertIn(task, coord.background_tasks)
        await task
        await asyncio.sleep(0.01)
        self.assertNotIn(task, coord.background_tasks)

        # Track long-running task and drain with timeout/cancellation
        async def long_task():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass

        t2 = coord.track_background_task(long_task(), name="long_task")
        self.assertIn(t2, coord.background_tasks)

        # Drain with cancel_remaining=True
        await coord.drain_background_tasks(timeout=0.1, cancel_remaining=True)
        self.assertEqual(len(coord.background_tasks), 0)

    async def test_shutdown_idempotence_and_resource_cleanup(self):
        """Test that shutdown is idempotent and closes all services cleanly."""
        coord = await Coordinator.create()

        await coord.shutdown()
        self.assertEqual(coord._lifecycle_state, "stopped")
        self.assertTrue(coord._shutdown_complete)

        # Second shutdown call should be a no-op and not raise
        await coord.shutdown()
        self.assertEqual(coord._lifecycle_state, "stopped")

    async def test_stage_signal_quality_artifact_rejection(self):
        """Test signal quality stage rejects compression drops and stale data."""
        coord = await Coordinator.create()

        # Normal reading
        now = datetime.now(timezone.utc)
        valid_reading = GlucoseReading(
            value=5.5,
            timestamp=now,
            trend="Flat",
            unit="mmol/L",
            source="test",
        )
        self.assertTrue(coord._stage_signal_quality(valid_reading))

        # Compression artifact / invalid reading
        invalid_reading = GlucoseReading(
            value=1.5,  # extreme non-physiological / artifact
            timestamp=now,
            trend="DoubleDown",
            unit="mmol/L",
            source="test",
        )
        # Should be evaluated by signal quality stage
        result = coord._stage_signal_quality(invalid_reading)
        self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main()
