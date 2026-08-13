"""Fail-stop contracts for unknown partial glucose-event processing."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from diabetic.coordinator import Coordinator
from diabetic.ingestion.event_integrity import GlucoseEventBuffer
from diabetic.registry import GlucoseReading


def _reading(event_id: str, minute: int = 0) -> GlucoseReading:
    return GlucoseReading(
        timestamp=datetime.now(timezone.utc) + timedelta(minutes=minute),
        value=7.0,
        trend="Flat",
        source="nightscout",
        source_event_id=event_id,
    )


class TestWorkerProcessingFailure(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.previous = Coordinator._instance
        Coordinator._instance = None
        self.coordinator = Coordinator()
        self.coordinator.logger = MagicMock()
        self.coordinator._lifecycle_state = "running"
        self.coordinator.is_running = True
        self.coordinator.ingestion_buffer = GlucoseEventBuffer(
            maxsize=4,
            processed_capacity=16,
        )
        self.markers = []

        async def record(payload):
            self.markers.append(payload)
            return True

        self.coordinator._record_gap_event = record

    def tearDown(self):
        Coordinator._instance = self.previous

    async def test_processing_failure_marks_once_and_never_retries(self):
        reading = _reading("poison")
        await self.coordinator.ingestion_buffer.offer(
            reading,
            write_gap=self.coordinator._record_gap_event,
        )
        self.coordinator._process_reading = AsyncMock(
            side_effect=RuntimeError("synthetic poison")
        )

        with self.assertRaisesRegex(RuntimeError, "synthetic poison"):
            await self.coordinator._worker_loop()

        self.coordinator._process_reading.assert_awaited_once_with(reading)
        self.assertEqual(len(self.markers), 1)
        self.assertEqual(self.markers[0]["reason"], "processing_failed")
        self.assertEqual(self.markers[0]["state"], "replay_pending")
        self.assertEqual(self.coordinator._lifecycle_state, "failed")
        self.assertFalse(self.coordinator.is_running)
        self.assertEqual(self.coordinator.ingestion_buffer.qsize(), 0)

    async def test_partial_mutation_failure_is_not_reexecuted(self):
        reading = _reading("partial")
        await self.coordinator.ingestion_buffer.offer(
            reading,
            write_gap=self.coordinator._record_gap_event,
        )
        mutations = []

        async def partially_process(_reading):
            mutations.append("filter-mutated")
            raise RuntimeError("after mutation")

        self.coordinator._process_reading = AsyncMock(side_effect=partially_process)

        with self.assertRaisesRegex(RuntimeError, "after mutation"):
            await self.coordinator._worker_loop()

        self.assertEqual(mutations, ["filter-mutated"])
        self.assertEqual(self.markers[0]["reason"], "processing_failed")

    async def test_marker_failure_is_fatal_and_keeps_event_inflight(self):
        reading = _reading("unmarked")

        async def fail_marker(_payload):
            return False

        self.coordinator._record_gap_event = fail_marker
        await self.coordinator.ingestion_buffer.offer(
            reading,
            write_gap=AsyncMock(return_value=True),
        )
        self.coordinator._process_reading = AsyncMock(
            side_effect=RuntimeError("synthetic poison")
        )

        with self.assertRaisesRegex(RuntimeError, "durable reconciliation"):
            await self.coordinator._worker_loop()

        duplicate = await self.coordinator.ingestion_buffer.offer(
            reading,
            write_gap=AsyncMock(return_value=True),
        )
        self.assertEqual(duplicate.action, "duplicate_inflight")
        self.assertEqual(self.coordinator._lifecycle_state, "failed")

    async def test_cancellation_before_event_writes_no_marker(self):
        worker = asyncio.create_task(self.coordinator._worker_loop())
        await asyncio.sleep(0)
        worker.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await worker

        self.assertEqual(self.markers, [])

    async def test_cancellation_during_processing_marks_unknown_work(self):
        reading = _reading("cancelled")
        await self.coordinator.ingestion_buffer.offer(
            reading,
            write_gap=self.coordinator._record_gap_event,
        )
        started = asyncio.Event()

        async def block(_reading):
            started.set()
            await asyncio.Future()

        self.coordinator._process_reading = block
        worker = asyncio.create_task(self.coordinator._worker_loop())
        await started.wait()
        worker.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await worker

        self.assertEqual(len(self.markers), 1)
        self.assertEqual(self.markers[0]["reason"], "processing_cancelled")
        self.assertNotEqual(self.coordinator._lifecycle_state, "failed")


class TestWorkerSupervision(unittest.IsolatedAsyncioTestCase):
    async def test_failed_runtime_rejects_late_poll_admission(self):
        previous = Coordinator._instance
        Coordinator._instance = None
        coordinator = Coordinator()
        coordinator.logger = MagicMock()
        coordinator.ingestion_buffer = SimpleNamespace(offer=AsyncMock())
        coordinator._lifecycle_state = "failed"
        coordinator.is_running = False

        try:
            with self.assertRaisesRegex(RuntimeError, "not accepting"):
                await coordinator._admit_live_reading(_reading("late"))
        finally:
            Coordinator._instance = previous

        coordinator.ingestion_buffer.offer.assert_not_awaited()

    async def test_worker_failure_interrupts_poll_interval(self):
        previous = Coordinator._instance
        Coordinator._instance = None
        coordinator = Coordinator()
        coordinator.logger = MagicMock()
        coordinator._lifecycle_state = "running"
        coordinator.is_running = True
        loop = asyncio.get_running_loop()
        coordinator._worker_failure = loop.create_future()
        error = RuntimeError("worker failed")
        coordinator._worker_failure.set_exception(error)

        try:
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                await coordinator._wait_for_poll_interval(3600)
        finally:
            Coordinator._instance = previous


class TestRestartReconciliation(unittest.IsolatedAsyncioTestCase):
    async def test_warmup_covers_failed_event_and_next_live_event_progresses(self):
        markers = []

        async def write_gap(payload):
            markers.append(payload)
            return True

        failed_buffer = GlucoseEventBuffer(maxsize=4, processed_capacity=16)
        poison = _reading("poison", 0)
        await failed_buffer.offer(poison, write_gap=write_gap)
        inflight = await failed_buffer.get()
        disposition = await failed_buffer.fail(
            inflight,
            reason="processing_failed",
            write_gap=write_gap,
        )

        restarted = GlucoseEventBuffer(maxsize=4, processed_capacity=16)
        self.assertTrue(await restarted.record_warmup(poison))
        duplicate = await restarted.offer(poison, write_gap=write_gap)
        next_result = await restarted.offer(
            _reading("next", 5),
            write_gap=write_gap,
        )
        next_event = await restarted.get()

        self.assertTrue(disposition.marker_durable)
        self.assertEqual(duplicate.action, "duplicate_processed")
        self.assertTrue(next_result.enqueued)
        self.assertEqual(next_event.key.event_id, "next")


if __name__ == "__main__":
    unittest.main()
