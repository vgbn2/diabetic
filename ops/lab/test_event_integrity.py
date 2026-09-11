"""Regression gates for live event identity, warm-up, and queue reconciliation."""

import asyncio
import tempfile
import unittest
from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from diabetic import medical_constants
from diabetic.coordinator import Coordinator
from diabetic.dsp.kalman import GlucoseFilter
from diabetic.ingestion.event_integrity import (
    GlucoseEventBuffer,
    prepare_warmup_readings,
)
from diabetic.registry import GlucoseReading
from diabetic.utils.audit_logger import AuditLogger


def _reading(
    event_id: str | None,
    minute: int,
    *,
    value: float = 7.0,
    source: str = "nightscout",
    base: datetime | None = None,
) -> GlucoseReading:
    anchor = base or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return GlucoseReading(
        timestamp=anchor + timedelta(minutes=minute),
        value=value,
        trend="Flat",
        source=source,
        source_event_id=event_id,
    )


class TestWarmupSelection(unittest.TestCase):
    def test_selects_latest_ordered_unique_events_across_transport_aliases(self):
        readings = [
            _reading("b", 10, value=7.0, source="mongodb"),
            _reading("a", 5),
            _reading("b", 10, value=7.2, source="nightscout"),
            _reading("c", 15),
        ]

        selected = prepare_warmup_readings(readings, limit=2)

        self.assertEqual([reading.source_event_id for reading in selected], ["b", "c"])
        self.assertEqual(selected[0].value, 7.2)
        self.assertLess(selected[0].timestamp, selected[1].timestamp)

    def test_missing_source_identity_is_not_admitted_to_warmup(self):
        selected = prepare_warmup_readings(
            [_reading(None, 0), _reading("known", 5)],
            limit=35,
        )

        self.assertEqual([reading.source_event_id for reading in selected], ["known"])


class TestGlucoseEventBuffer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.markers = []

        async def write_gap(payload):
            self.markers.append(payload)
            return True

        self.write_gap = write_gap
        self.buffer = GlucoseEventBuffer(maxsize=2, processed_capacity=8)

    async def test_same_nightscout_event_from_mongo_and_rest_is_duplicate(self):
        first = _reading("same", 0, source="mongodb")
        duplicate = _reading("same", 0, source="nightscout")

        admitted = await self.buffer.offer(first, write_gap=self.write_gap)
        repeated = await self.buffer.offer(duplicate, write_gap=self.write_gap)

        self.assertTrue(admitted.enqueued)
        self.assertEqual(repeated.action, "duplicate_pending")
        self.assertEqual(self.buffer.qsize(), 1)
        self.assertEqual(self.markers, [])

    async def test_pending_correction_replaces_before_clinical_processing(self):
        await self.buffer.offer(_reading("event", 5, value=7.0), write_gap=self.write_gap)
        corrected = await self.buffer.offer(
            _reading("event", 5, value=7.4),
            write_gap=self.write_gap,
        )
        event = await self.buffer.get()

        self.assertEqual(corrected.action, "corrected_pending")
        self.assertEqual(event.reading.value, 7.4)
        self.assertEqual(self.markers, [])

    async def test_processed_correction_is_quarantined_for_reconciliation(self):
        await self.buffer.offer(_reading("event", 5), write_gap=self.write_gap)
        event = await self.buffer.get()
        await self.buffer.complete(event)

        correction = await self.buffer.offer(
            _reading("event", 5, value=8.0),
            write_gap=self.write_gap,
        )

        self.assertEqual(correction.action, "quarantined")
        self.assertTrue(correction.marker_durable)
        self.assertEqual(self.markers[-1]["reason"], "correction_after_processing")
        self.assertEqual(self.buffer.qsize(), 0)

    async def test_out_of_order_event_after_watermark_is_quarantined(self):
        await self.buffer.offer(_reading("new", 10), write_gap=self.write_gap)
        event = await self.buffer.get()
        await self.buffer.complete(event)

        older = await self.buffer.offer(
            _reading("old", 5),
            write_gap=self.write_gap,
        )

        self.assertEqual(older.action, "quarantined")
        self.assertEqual(self.markers[-1]["reason"], "out_of_order_after_watermark")

    async def test_event_older_than_inflight_work_is_quarantined(self):
        await self.buffer.offer(_reading("new", 10), write_gap=self.write_gap)
        inflight = await self.buffer.get()

        older = await self.buffer.offer(
            _reading("old", 5),
            write_gap=self.write_gap,
        )
        await self.buffer.complete(inflight)

        self.assertEqual(older.action, "quarantined")
        self.assertEqual(self.markers[-1]["reason"], "out_of_order_after_watermark")

    async def test_pending_events_are_processed_in_timestamp_order(self):
        await self.buffer.offer(_reading("later", 10), write_gap=self.write_gap)
        await self.buffer.offer(_reading("earlier", 5), write_gap=self.write_gap)

        first = await self.buffer.get()
        await self.buffer.complete(first)
        second = await self.buffer.get()

        self.assertEqual(first.key.event_id, "earlier")
        self.assertEqual(second.key.event_id, "later")

    async def test_overflow_marks_gap_before_bounded_reconciliation(self):
        buffer = GlucoseEventBuffer(
            maxsize=1,
            processed_capacity=8,
            reconciliation_capacity=1,
        )
        await buffer.offer(_reading("oldest", 0), write_gap=self.write_gap)
        admitted = await buffer.offer(_reading("latest", 5), write_gap=self.write_gap)

        self.assertTrue(admitted.enqueued)
        self.assertEqual(self.markers[-1]["reason"], "queue_coalesced")
        self.assertEqual(self.markers[-1]["from_event_id"], "oldest")
        self.assertEqual(self.markers[-1]["through_event_id"], "latest")

        reconciliation = await buffer.get()
        await buffer.complete(reconciliation)
        latest = await buffer.get()
        self.assertIsNotNone(reconciliation.gap_id)
        self.assertEqual(reconciliation.key.event_id, "oldest")
        self.assertEqual(latest.key.event_id, "latest")

    async def test_failed_quarantine_marker_fails_closed(self):
        await self.buffer.offer(_reading("new", 10), write_gap=self.write_gap)
        event = await self.buffer.get()
        await self.buffer.complete(event)

        async def failed_gap(_payload):
            return False

        with self.assertRaisesRegex(RuntimeError, "durable reconciliation"):
            await self.buffer.offer(_reading("old", 5), write_gap=failed_gap)

    async def test_processing_failure_is_removed_only_after_durable_marker(self):
        reading = _reading("failed", 5)
        await self.buffer.offer(reading, write_gap=self.write_gap)
        event = await self.buffer.get()

        result = await self.buffer.fail(
            event,
            reason="processing_failed",
            write_gap=self.write_gap,
        )

        self.assertTrue(result.marker_durable)
        self.assertEqual(result.reason, "processing_failed")
        self.assertEqual(self.markers[-1]["from_event_id"], "failed")
        self.assertEqual(self.buffer.qsize(), 0)
        repeat = await self.buffer.offer(reading, write_gap=self.write_gap)
        self.assertTrue(repeat.enqueued)

    async def test_failed_processing_marker_keeps_event_inflight(self):
        await self.buffer.offer(_reading("failed", 5), write_gap=self.write_gap)
        event = await self.buffer.get()

        with self.assertRaisesRegex(RuntimeError, "durable reconciliation"):
            await self.buffer.fail(
                event,
                reason="processing_failed",
                write_gap=AsyncMock(return_value=False),
            )

        duplicate = await self.buffer.offer(
            event.reading,
            write_gap=self.write_gap,
        )
        self.assertEqual(duplicate.action, "duplicate_inflight")

    async def test_failed_gap_write_never_discards_oldest_event(self):
        allow_write = asyncio.Event()

        async def delayed_gap(payload):
            if not allow_write.is_set():
                return False
            self.markers.append(payload)
            return True

        buffer = GlucoseEventBuffer(maxsize=1, processed_capacity=8)
        await buffer.offer(_reading("oldest", 0), write_gap=delayed_gap)
        pending_offer = asyncio.create_task(
            buffer.offer(_reading("latest", 5), write_gap=delayed_gap)
        )
        await asyncio.sleep(0)
        self.assertFalse(pending_offer.done())

        oldest = await buffer.get()
        await buffer.complete(oldest)
        allow_write.set()
        admitted = await asyncio.wait_for(pending_offer, timeout=1)

        self.assertTrue(admitted.enqueued)
        self.assertEqual(oldest.key.event_id, "oldest")


class TestDurableGapProjection(unittest.IsolatedAsyncioTestCase):
    async def test_pending_gap_survives_query_and_replay_transition(self):
        with tempfile.TemporaryDirectory() as temporary:
            audit = AuditLogger(f"{temporary}/audit.db")
            payload = {
                "gap_id": "gap-1",
                "source": "nightscout",
                "state": "replay_pending",
                "reason": "queue_coalesced",
                "from_event_id": "a",
                "through_event_id": "b",
                "from_timestamp": "2026-01-01T00:00:00+00:00",
                "through_timestamp": "2026-01-01T00:05:00+00:00",
            }

            result = await audit.record_glucose_gap(payload)
            pending = await audit.get_pending_glucose_gaps()
            replayed = await audit.record_glucose_gap(
                {
                    "gap_id": "gap-1",
                    "source": "nightscout",
                    "state": "replayed",
                }
            )
            after = await audit.get_pending_glucose_gaps()
            stored_range = audit.local_conn.execute(
                "SELECT from_event_id, through_event_id FROM glucose_gaps WHERE gap_id = ?",
                ("gap-1",),
            ).fetchone()
            audit.local_conn.close()

        self.assertTrue(result.durable)
        self.assertTrue(replayed.durable)
        self.assertEqual(pending[0]["gap_id"], "gap-1")
        self.assertEqual(after, [])
        self.assertEqual(stored_range, ("a", "b"))


class TestCoordinatorConfidenceOrdering(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous = Coordinator._instance
        Coordinator._instance = None
        self.coordinator = Coordinator()
        self.coordinator.logger = MagicMock()
        self.coordinator.regime_step_count = 0
        self.coordinator.background_tasks = set()
        self.coordinator.audit = SimpleNamespace(log_reading=AsyncMock())
        self.coordinator.filter = MagicMock()
        self.coordinator._fetch_recent_treatments = AsyncMock(
            return_value=SimpleNamespace(
                source="nightscout",
                state="degraded",
                fetched_at=datetime.now(timezone.utc),
                insulin=[],
                meals=[],
                error_reason="test",
            )
        )
        self.coordinator.hr_client = SimpleNamespace(fetch_latest=AsyncMock(return_value=None))
        self.coordinator.weather_client = SimpleNamespace(
            fetch_current=AsyncMock(return_value=None)
        )
        self.coordinator.vessel_registry = SimpleNamespace(
            get_medical_state=AsyncMock(return_value=None)
        )
        self.coordinator.allow_synthetic = False
        self.coordinator.mongo = SimpleNamespace(
            save_cardiac_reading=AsyncMock(),
            save_environment_reading=AsyncMock(),
        )
        self.coordinator.last_provider_insulin = None
        self.coordinator.last_provider_meal = None
        self.coordinator.last_meal = None
        self.coordinator.treatment_fetch_state = "waiting"
        self.coordinator.treatment_source = None
        self.coordinator.treatment_fetched_at = None
        self.coordinator.treatment_degraded_reason = None
        self.coordinator.twin = SimpleNamespace(detect_regime=MagicMock())
        self.coordinator.oracle = SimpleNamespace(params=None)
        self.coordinator.neural_runner = SimpleNamespace(
            run_inference_on_snapshots=MagicMock(
                return_value={"glucose": 11.0, "heart_rate": 80.0}
            )
        )
        self.coordinator.forecaster = SimpleNamespace(
            compute=MagicMock(
                return_value={"p15m": 7.0, "p60m": 7.0, "velocity": 0.0}
            )
        )
        self.coordinator.alert_guard = SimpleNamespace(evaluate=AsyncMock(return_value=None))
        self.coordinator.circuit_breaker = MagicMock()
        self.coordinator.last_prediction_4h = []
        self.coordinator.last_prediction_1d = []
        self.coordinator.meal_tune_pending = False
        self.coordinator.meal_window_start = None
        self.coordinator.visualizer = SimpleNamespace(update_continuous=MagicMock())

    async def asyncTearDown(self):
        if self.coordinator.background_tasks:
            await asyncio.gather(*self.coordinator.background_tasks)
        Coordinator._instance = self.previous

    async def _process_with_history(self, count: int):
        now = datetime.now(timezone.utc)
        history = [
            _reading(str(index), -(count - index) * 5, base=now)
            for index in range(count)
        ]
        self.coordinator.snapshots = deque(
            [
                SimpleNamespace(
                    glucose=reading,
                    filtered_value=7.0,
                )
                for reading in history
            ],
            maxlen=medical_constants.SNAPSHOT_CAP,
        )
        current = _reading("current", 0, base=now)
        self.coordinator.filter.update.return_value = SimpleNamespace(
            glucose=current,
            filtered_value=7.0,
            velocity=0.0,
            acceleration=0.0,
            atr_14=0.0,
            predicted_hr=0.0,
            last_meal=None,
            last_insulin=None,
            active_carbs=0.0,
            active_insulin=0.0,
            confidence_index=0.0,
            predict_30m=0.0,
            predict_15m=0.0,
            predict_60m=0.0,
            velocity_score=0.0,
            activity_label="UNKNOWN",
            cardiac=None,
            environment=None,
            is_sick=False,
            bpm=None,
            max_bpm=None,
            hrv=None,
        )
        with patch(
            "diabetic.coordinator.MetabolicMath.calculate_atr",
            return_value=0.0,
        ), patch("diabetic.coordinator.classify_context") as classify:
            classify.return_value.value = "STABLE"
            await self.coordinator._process_reading(current)
        return self.coordinator.alert_guard.evaluate.await_args.args

    async def test_dense_current_history_passes_divergent_cnn_to_alert_input(self):
        snapshot, prediction, _audit = await self._process_with_history(17)

        self.assertGreaterEqual(
            snapshot.confidence_index,
            medical_constants.ALPHA_GATE_CONFIDENCE_THRESHOLD,
        )
        self.assertEqual(prediction, 9.0)

    async def test_sparse_current_history_rejects_divergent_cnn_before_alert_input(self):
        snapshot, prediction, _audit = await self._process_with_history(0)

        self.assertLess(
            snapshot.confidence_index,
            medical_constants.ALPHA_GATE_CONFIDENCE_THRESHOLD,
        )
        self.assertEqual(prediction, 7.0)


class TestCoordinatorWarmup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous = Coordinator._instance
        Coordinator._instance = None
        self.coordinator = Coordinator()
        self.coordinator.logger = MagicMock()
        self.coordinator.snapshots = deque(maxlen=medical_constants.SNAPSHOT_CAP)
        self.coordinator.filter = GlucoseFilter()
        self.coordinator.regime_step_count = 0
        self.coordinator.ingestion_buffer = GlucoseEventBuffer(
            maxsize=120,
            processed_capacity=1000,
        )
        self.coordinator.audit = SimpleNamespace(
            log_reading=AsyncMock(side_effect=AssertionError("warm-up audited"))
        )
        self.coordinator._fetch_recent_treatments = AsyncMock(
            side_effect=AssertionError("warm-up fetched provider context")
        )
        self.coordinator.alert_guard = SimpleNamespace(
            evaluate=AsyncMock(side_effect=AssertionError("warm-up evaluated alert"))
        )

    async def asyncTearDown(self):
        Coordinator._instance = self.previous

    async def test_stale_history_warms_thirty_ordered_snapshots_without_side_effects(self):
        base = datetime.now(timezone.utc) - timedelta(hours=24)
        readings = [_reading(str(index), index * 5, base=base) for index in range(35)]

        for reading in prepare_warmup_readings(readings[::-1], limit=35):
            accepted = await self.coordinator._process_reading(
                reading,
                is_backfill=True,
            )
            self.assertTrue(accepted)

        self.assertEqual(len(self.coordinator.snapshots), 35)
        timestamps = [item.glucose.timestamp for item in self.coordinator.snapshots]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertEqual(self.coordinator.regime_step_count, 35)
        self.coordinator.audit.log_reading.assert_not_awaited()
        self.coordinator._fetch_recent_treatments.assert_not_awaited()
        self.coordinator.alert_guard.evaluate.assert_not_awaited()

    async def test_restart_closes_only_gaps_covered_by_verified_warmup(self):
        self.coordinator.audit.get_pending_glucose_gaps = AsyncMock(
            return_value=[
                {
                    "gap_id": "covered",
                    "source": "nightscout",
                    "from_event_id": "1",
                    "through_event_id": "2",
                },
                {
                    "gap_id": "missing",
                    "source": "nightscout",
                    "from_event_id": "1",
                    "through_event_id": "3",
                },
            ]
        )
        self.coordinator.audit.record_glucose_gap = AsyncMock(
            return_value=SimpleNamespace(durable=True)
        )

        await self.coordinator._reconcile_pending_gaps(
            [_reading("1", 0), _reading("2", 5)]
        )

        self.coordinator.audit.record_glucose_gap.assert_awaited_once()
        payload = self.coordinator.audit.record_glucose_gap.await_args.args[0]
        self.assertEqual(payload["gap_id"], "covered")
        self.assertEqual(payload["state"], "replayed")

    async def test_restart_keeps_fetched_but_unwarmed_gap_pending(self):
        self.coordinator.audit.get_pending_glucose_gaps = AsyncMock(
            return_value=[
                {
                    "gap_id": "outside-warmup",
                    "source": "nightscout",
                    "from_event_id": "old",
                    "through_event_id": "new",
                }
            ]
        )
        self.coordinator.audit.record_glucose_gap = AsyncMock(
            return_value=SimpleNamespace(durable=True)
        )
        fetched = [_reading("old", 0), _reading("new", 5)]
        warmed = prepare_warmup_readings([fetched[-1]], limit=35)

        await self.coordinator._reconcile_pending_gaps(warmed)

        self.coordinator.audit.record_glucose_gap.assert_not_awaited()

    async def test_restart_does_not_cross_sources_with_reused_event_ids(self):
        self.coordinator.audit.get_pending_glucose_gaps = AsyncMock(
            return_value=[
                {
                    "gap_id": "other-source",
                    "source": "synthetic",
                    "from_event_id": "1",
                    "through_event_id": "2",
                }
            ]
        )
        self.coordinator.audit.record_glucose_gap = AsyncMock(
            return_value=SimpleNamespace(durable=True)
        )

        await self.coordinator._reconcile_pending_gaps(
            [_reading("1", 0), _reading("2", 5)]
        )

        self.coordinator.audit.record_glucose_gap.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
