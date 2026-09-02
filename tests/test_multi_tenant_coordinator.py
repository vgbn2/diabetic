import unittest
import asyncio
from datetime import datetime, timezone, timedelta
from diabetic.coordinator import Coordinator
from diabetic.registry import GlucoseReading


class TestMultiTenantCoordinator(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.coordinator = await Coordinator.create(allow_synthetic=True)

    async def asyncTearDown(self):
        await self.coordinator.shutdown()

    async def test_tenant_pipeline_isolation(self):
        now = datetime.now(timezone.utc)

        # Patient 1 (Tam): Rapidly rising glucose
        reading_tam_1 = GlucoseReading(value=5.0, trend="Flat", timestamp=now - timedelta(minutes=10))
        reading_tam_2 = GlucoseReading(value=7.5, trend="SingleUp", timestamp=now - timedelta(minutes=5))
        reading_tam_3 = GlucoseReading(value=10.0, trend="DoubleUp", timestamp=now)

        # Patient 2 (Bob): Steadily falling glucose within physiological limits
        reading_bob_1 = GlucoseReading(value=10.0, trend="Flat", timestamp=now - timedelta(minutes=10))
        reading_bob_2 = GlucoseReading(value=9.0, trend="SingleDown", timestamp=now - timedelta(minutes=5))
        reading_bob_3 = GlucoseReading(value=8.0, trend="SingleDown", timestamp=now)

        # Interleave processing
        await self.coordinator._process_reading(reading_tam_1, tenant_id="tam")
        await self.coordinator._process_reading(reading_bob_1, tenant_id="bob")
        await self.coordinator._process_reading(reading_tam_2, tenant_id="tam")
        await self.coordinator._process_reading(reading_bob_2, tenant_id="bob")
        await self.coordinator._process_reading(reading_tam_3, tenant_id="tam")
        await self.coordinator._process_reading(reading_bob_3, tenant_id="bob")

        pipeline_tam = self.coordinator.get_pipeline("tam")
        pipeline_bob = self.coordinator.get_pipeline("bob")

        self.assertEqual(len(pipeline_tam.snapshots), 3)
        self.assertEqual(len(pipeline_bob.snapshots), 3)

        # Tam's Kalman velocity should be positive (rising)
        vel_tam = pipeline_tam.last_snapshot.velocity
        self.assertGreater(vel_tam, 0.0)

        # Bob's Kalman velocity should be negative (falling)
        vel_bob = pipeline_bob.last_snapshot.velocity
        self.assertLess(vel_bob, 0.0)

        # Ensure no cross-contamination between patient snapshots
        self.assertAlmostEqual(pipeline_tam.last_snapshot.glucose.value, 10.0)
        self.assertAlmostEqual(pipeline_bob.last_snapshot.glucose.value, 8.0)

        # Ensure predictions and confidence are computed on isolated tenant history
        self.assertIsNotNone(pipeline_tam.last_snapshot.predict_30m)
        self.assertIsNotNone(pipeline_bob.last_snapshot.predict_30m)
        self.assertGreater(pipeline_tam.last_snapshot.predict_30m, 10.0)
        self.assertLess(pipeline_bob.last_snapshot.predict_30m, 8.0)


if __name__ == "__main__":
    unittest.main()
