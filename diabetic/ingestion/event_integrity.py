"""Idempotent glucose-event admission, ordering, and bounded reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import timezone
from typing import Awaitable, Callable, Iterable, Literal, Optional
from uuid import uuid4

from diabetic.registry import GlucoseReading


AdmissionAction = Literal[
    "enqueued",
    "duplicate_pending",
    "corrected_pending",
    "duplicate_inflight",
    "duplicate_processed",
    "quarantined",
]
GapWriter = Callable[[dict], Awaitable[bool]]


@dataclass(frozen=True, order=True)
class GlucoseEventKey:
    source: str
    event_id: str


@dataclass(frozen=True)
class AdmissionResult:
    action: AdmissionAction
    key: Optional[GlucoseEventKey]
    marker_durable: Optional[bool] = None

    @property
    def enqueued(self) -> bool:
        return self.action == "enqueued"


@dataclass(frozen=True)
class BufferedGlucoseEvent:
    key: GlucoseEventKey
    reading: GlucoseReading
    gap_id: Optional[str] = None


@dataclass(frozen=True)
class ProcessingFailureDisposition:
    key: GlucoseEventKey
    reason: str
    gap_id: str
    marker_durable: bool


@dataclass
class _PendingEvent:
    reading: GlucoseReading
    fingerprint: str
    gap_id: Optional[str] = None


def canonical_event_source(source: str) -> str:
    """Collapse transport aliases that expose the same Nightscout event IDs."""
    if source in {"mongodb", "nightscout", "historical_archive"}:
        return "nightscout"
    return source


def glucose_event_key(reading: GlucoseReading) -> Optional[GlucoseEventKey]:
    if reading.source_event_id is None:
        return None
    event_id = str(reading.source_event_id).strip()
    if not event_id:
        return None
    return GlucoseEventKey(canonical_event_source(reading.source), event_id)


def _timestamp_utc(reading: GlucoseReading):
    timestamp = reading.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _fingerprint(reading: GlucoseReading) -> str:
    payload = {
        "timestamp": _timestamp_utc(reading).isoformat(),
        "value": reading.value,
        "trend": reading.trend,
        "unit": reading.unit,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def prepare_warmup_readings(
    readings: Iterable[GlucoseReading],
    *,
    limit: int,
) -> list[GlucoseReading]:
    """Return the latest chronological unique provider events for restart warm-up."""
    unique: dict[GlucoseEventKey, GlucoseReading] = {}
    for reading in readings:
        key = glucose_event_key(reading)
        if key is not None:
            unique[key] = reading
    ordered = sorted(
        unique.values(),
        key=lambda reading: (_timestamp_utc(reading), glucose_event_key(reading)),
    )
    return ordered[-limit:]


class GlucoseEventBuffer:
    """Bound live events while preserving idempotency and replay accountability."""

    def __init__(
        self,
        *,
        maxsize: int,
        processed_capacity: int,
        reconciliation_capacity: Optional[int] = None,
    ) -> None:
        if maxsize <= 0 or processed_capacity <= 0:
            raise ValueError("event buffer capacities must be positive")
        self.maxsize = maxsize
        self.reconciliation_capacity = reconciliation_capacity or maxsize
        self._condition = asyncio.Condition()
        self._realtime: deque[GlucoseEventKey] = deque()
        self._reconciliation: deque[GlucoseEventKey] = deque()
        self._pending: dict[GlucoseEventKey, _PendingEvent] = {}
        self._inflight: dict[GlucoseEventKey, _PendingEvent] = {}
        self._processed: OrderedDict[GlucoseEventKey, str] = OrderedDict()
        self._processed_capacity = processed_capacity
        self._watermark = None

    def qsize(self) -> int:
        return len(self._realtime) + len(self._reconciliation)

    async def offer(
        self,
        reading: GlucoseReading,
        *,
        write_gap: GapWriter,
    ) -> AdmissionResult:
        key = glucose_event_key(reading)
        fingerprint = _fingerprint(reading)
        if key is None:
            durable = await write_gap(
                self._gap_payload("missing_source_event_id", reading)
            )
            self._require_durable_marker(durable)
            return AdmissionResult("quarantined", None, durable)

        async with self._condition:
            pending = self._pending.get(key)
            if pending is not None:
                if pending.fingerprint == fingerprint:
                    return AdmissionResult("duplicate_pending", key)
                pending.reading = reading
                pending.fingerprint = fingerprint
                if key in self._realtime:
                    self._realtime.remove(key)
                    self._insert_realtime(key)
                return AdmissionResult("corrected_pending", key)

            inflight = self._inflight.get(key)
            if inflight is not None:
                if inflight.fingerprint == fingerprint:
                    return AdmissionResult("duplicate_inflight", key)
                durable = await write_gap(
                    self._gap_payload("correction_after_processing_started", reading)
                )
                self._require_durable_marker(durable)
                return AdmissionResult("quarantined", key, durable)

            processed_fingerprint = self._processed.get(key)
            if processed_fingerprint is not None:
                self._processed.move_to_end(key)
                if processed_fingerprint == fingerprint:
                    return AdmissionResult("duplicate_processed", key)
                durable = await write_gap(
                    self._gap_payload("correction_after_processing", reading)
                )
                self._require_durable_marker(durable)
                return AdmissionResult("quarantined", key, durable)

            timestamp = _timestamp_utc(reading)
            admission_floor = self._watermark
            if self._inflight:
                inflight_floor = max(
                    _timestamp_utc(event.reading)
                    for event in self._inflight.values()
                )
                if admission_floor is None or inflight_floor > admission_floor:
                    admission_floor = inflight_floor
            if admission_floor is not None and timestamp <= admission_floor:
                durable = await write_gap(
                    self._gap_payload("out_of_order_after_watermark", reading)
                )
                self._require_durable_marker(durable)
                return AdmissionResult("quarantined", key, durable)

            while len(self._realtime) >= self.maxsize:
                if len(self._reconciliation) >= self.reconciliation_capacity:
                    await self._condition.wait()
                    continue

                oldest_key = self._realtime[0]
                oldest = self._pending[oldest_key]
                gap_id = uuid4().hex
                durable = await write_gap(
                    self._gap_payload(
                        "queue_coalesced",
                        oldest.reading,
                        replacement=reading,
                        gap_id=gap_id,
                    )
                )
                if not durable:
                    await self._condition.wait()
                    continue

                self._realtime.popleft()
                oldest.gap_id = gap_id
                self._reconciliation.append(oldest_key)
                break

            self._pending[key] = _PendingEvent(reading, fingerprint)
            self._insert_realtime(key)
            self._condition.notify()
            return AdmissionResult("enqueued", key)

    def _insert_realtime(self, key: GlucoseEventKey) -> None:
        timestamp = _timestamp_utc(self._pending[key].reading)
        for index, queued_key in enumerate(self._realtime):
            queued = self._pending[queued_key].reading
            if timestamp < _timestamp_utc(queued):
                self._realtime.insert(index, key)
                return
        self._realtime.append(key)

    async def get(self) -> BufferedGlucoseEvent:
        async with self._condition:
            while not self._reconciliation and not self._realtime:
                await self._condition.wait()
            queue = self._reconciliation if self._reconciliation else self._realtime
            key = queue.popleft()
            event = self._pending.pop(key)
            self._inflight[key] = event
            self._condition.notify_all()
            return BufferedGlucoseEvent(key, event.reading, event.gap_id)

    async def complete(self, event: BufferedGlucoseEvent) -> None:
        async with self._condition:
            inflight = self._inflight.pop(event.key, None)
            if inflight is None:
                return
            self._remember_processed(event.key, inflight.fingerprint)
            timestamp = _timestamp_utc(event.reading)
            if self._watermark is None or timestamp > self._watermark:
                self._watermark = timestamp
            self._condition.notify_all()

    async def fail(
        self,
        event: BufferedGlucoseEvent,
        *,
        reason: Literal["processing_failed", "processing_cancelled"],
        write_gap: GapWriter,
    ) -> ProcessingFailureDisposition:
        """Durably quarantine unknown partial work without replaying it in-process."""
        async with self._condition:
            inflight = self._inflight.get(event.key)
            if inflight is None:
                raise RuntimeError("glucose event is no longer in-flight")
            gap_id = uuid4().hex
            payload = self._gap_payload(
                reason,
                inflight.reading,
                gap_id=gap_id,
            )
            durable = await write_gap(payload)
            self._require_durable_marker(durable)
            self._inflight.pop(event.key, None)
            self._condition.notify_all()
            return ProcessingFailureDisposition(
                key=event.key,
                reason=reason,
                gap_id=gap_id,
                marker_durable=True,
            )

    async def record_warmup(self, reading: GlucoseReading) -> bool:
        key = glucose_event_key(reading)
        if key is None:
            return False
        async with self._condition:
            self._remember_processed(key, _fingerprint(reading))
            timestamp = _timestamp_utc(reading)
            if self._watermark is None or timestamp > self._watermark:
                self._watermark = timestamp
        return True

    @staticmethod
    def _require_durable_marker(durable: bool) -> None:
        if not durable:
            raise RuntimeError("glucose event requires a durable reconciliation marker")

    def _remember_processed(self, key: GlucoseEventKey, fingerprint: str) -> None:
        self._processed[key] = fingerprint
        self._processed.move_to_end(key)
        while len(self._processed) > self._processed_capacity:
            self._processed.popitem(last=False)

    @staticmethod
    def _gap_payload(
        reason: str,
        reading: GlucoseReading,
        *,
        replacement: Optional[GlucoseReading] = None,
        gap_id: Optional[str] = None,
    ) -> dict:
        source = canonical_event_source(reading.source)
        return {
            "gap_id": gap_id or uuid4().hex,
            "reason": reason,
            "state": "replay_pending",
            "source": source,
            "from_event_id": reading.source_event_id,
            "from_timestamp": _timestamp_utc(reading).isoformat(),
            "through_event_id": (
                replacement.source_event_id if replacement is not None else reading.source_event_id
            ),
            "through_timestamp": (
                _timestamp_utc(replacement).isoformat()
                if replacement is not None
                else _timestamp_utc(reading).isoformat()
            ),
        }
