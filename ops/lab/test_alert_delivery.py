"""Direct alert-delivery, cooldown, and feedback compatibility contracts."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import Forbidden, RetryAfter, TimedOut

from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic.telegram_bot.decision_matrix import (
    Alert,
    AlertSeverity,
    CircuitBreaker,
)
from diabetic.telegram_bot.handlers import (
    AlertDeliveryResult,
    TelegramNotifier,
    parse_feedback_callback,
)
from diabetic.utils.audit_logger import AuditWriteResult


def _alert(alert_type: str = "CRITICAL_HYPO") -> Alert:
    return Alert(
        timestamp=datetime.now(timezone.utc),
        type=alert_type,
        severity=AlertSeverity.EMERGENCY,
        message="Synthetic test alert",
        glucose_value=2.2,
    )


class TestCircuitBreakerReservations(unittest.TestCase):
    def test_failed_attempt_releases_without_cooldown(self):
        breaker = CircuitBreaker()
        alert = _alert()
        reservation = breaker.reserve(alert.type, alert.alert_id, alert.severity)

        self.assertIsNotNone(reservation)
        self.assertIsNone(
            breaker.reserve(alert.type, "concurrent", alert.severity)
        )
        self.assertTrue(breaker.release(reservation))
        self.assertIsNotNone(
            breaker.reserve(alert.type, "retry", alert.severity)
        )

    def test_accepted_attempt_commits_normal_cooldown(self):
        breaker = CircuitBreaker()
        alert = _alert("WARNING_HYPO").model_copy(
            update={"severity": AlertSeverity.HIGH}
        )
        reservation = breaker.reserve(alert.type, alert.alert_id, alert.severity)

        self.assertTrue(breaker.commit(reservation))
        self.assertFalse(breaker.can_alert(alert.type, alert.severity))
        self.assertIsNone(
            breaker.reserve(alert.type, "too-soon", alert.severity)
        )

    def test_stale_reservation_expires(self):
        breaker = CircuitBreaker(reservation_mins=1)
        alert = _alert()
        reservation = breaker.reserve(alert.type, alert.alert_id, alert.severity)
        breaker._reservations[alert.type] = reservation.__class__(
            reservation.alert_type,
            reservation.alert_id,
            reservation.severity,
            datetime.now(timezone.utc) - timedelta(minutes=2),
        )

        self.assertIsNotNone(
            breaker.reserve(alert.type, "replacement", alert.severity)
        )


class TestTelegramDelivery(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.notifier = TelegramNotifier()
        self.notifier.chat_id = 123
        self.notifier.bot = AsyncMock()

    async def asyncTearDown(self):
        for task in self.notifier.pending_tasks.values():
            task.cancel()
        if self.notifier.pending_tasks:
            await asyncio.gather(
                *self.notifier.pending_tasks.values(), return_exceptions=True
            )

    async def test_accepted_send_returns_message_id_and_starts_review(self):
        self.notifier.bot.send_message.return_value = SimpleNamespace(message_id=77)

        result = await self.notifier.send_alert(_alert())

        self.assertTrue(result.accepted)
        self.assertEqual(result.message_id, 77)
        self.assertIn(77, self.notifier.pending_tasks)

    async def test_permanent_rejection_is_not_retried(self):
        self.notifier.bot.send_message.side_effect = Forbidden("denied")

        result = await self.notifier.send_alert(_alert())

        self.assertEqual(result.state, "rejected")
        self.assertEqual(result.reason, "Forbidden")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(self.notifier.bot.send_message.await_count, 1)
        self.assertFalse(self.notifier.pending_tasks)

    async def test_short_rate_limit_retries_then_accepts(self):
        self.notifier.bot.send_message.side_effect = [
            RetryAfter(0),
            SimpleNamespace(message_id=88),
        ]

        with patch("diabetic.telegram_bot.handlers.asyncio.sleep", AsyncMock()):
            result = await self.notifier.send_alert(_alert(), max_attempts=2)

        self.assertTrue(result.accepted)
        self.assertEqual(result.attempts, 2)
        self.assertIn(88, self.notifier.pending_tasks)

    async def test_long_rate_limit_is_not_slept_in_worker(self):
        self.notifier.bot.send_message.side_effect = RetryAfter(30)

        result = await self.notifier.send_alert(
            _alert(), max_attempts=2, max_retry_delay_seconds=5
        )

        self.assertEqual(result.state, "rate_limited")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.retry_after_seconds, 30)

    async def test_timeout_exhaustion_is_explicitly_ambiguous(self):
        self.notifier.bot.send_message.side_effect = TimedOut("timeout")

        result = await self.notifier.send_alert(_alert(), max_attempts=2)

        self.assertEqual(result.state, "ambiguous")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(self.notifier.bot.send_message.await_count, 2)
        self.assertFalse(self.notifier.pending_tasks)

    async def test_cancellation_propagates(self):
        self.notifier.bot.send_message.side_effect = asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await self.notifier.send_alert(_alert())


class TestCoordinatorDeliveryLifecycle(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from diabetic.coordinator import Coordinator

        self._previous = Coordinator._instance
        Coordinator._instance = None
        self.coordinator = Coordinator()
        self.coordinator.logger = MagicMock()
        self.coordinator.audit = AsyncMock()
        self.coordinator.audit.log_event.return_value = AuditWriteResult(
            local_persisted=True,
            mongo_persisted=False,
        )
        self.coordinator.notifier = AsyncMock()
        self.coordinator.circuit_breaker = CircuitBreaker()

    def tearDown(self):
        from diabetic.coordinator import Coordinator

        Coordinator._instance = self._previous

    async def test_accepted_delivery_commits_and_audits_delivered(self):
        alert = _alert("WARNING_HYPO").model_copy(
            update={"severity": AlertSeverity.HIGH}
        )
        reservation = self.coordinator.circuit_breaker.reserve(
            alert.type, alert.alert_id, alert.severity
        )
        self.coordinator.notifier.send_alert.return_value = AlertDeliveryResult(
            state="accepted", attempts=1, message_id=77
        )

        await self.coordinator._dispatch_alert(alert, reservation)

        self.assertFalse(
            self.coordinator.circuit_breaker.can_alert(
                alert.type, alert.severity
            )
        )
        events = [call.args[0] for call in self.coordinator.audit.log_event.await_args_list]
        self.assertEqual(events, ["ALERT_ATTEMPTED", "ALERT_DELIVERED"])

    async def test_attempt_audit_failure_does_not_block_delivery(self):
        alert = _alert()
        reservation = self.coordinator.circuit_breaker.reserve(
            alert.type, alert.alert_id, alert.severity
        )
        self.coordinator.audit.log_event.side_effect = [
            RuntimeError("synthetic audit failure"),
            AuditWriteResult(local_persisted=True, mongo_persisted=False),
        ]
        self.coordinator.notifier.send_alert.return_value = AlertDeliveryResult(
            state="accepted", attempts=1, message_id=77
        )

        await self.coordinator._dispatch_alert(alert, reservation)

        self.coordinator.notifier.send_alert.assert_awaited_once_with(alert)
        self.assertIn(alert.type, self.coordinator.circuit_breaker.last_alerts)

    async def test_delivered_audit_failure_does_not_duplicate_delivery(self):
        alert = _alert()
        reservation = self.coordinator.circuit_breaker.reserve(
            alert.type, alert.alert_id, alert.severity
        )
        self.coordinator.audit.log_event.side_effect = [
            AuditWriteResult(local_persisted=True, mongo_persisted=False),
            RuntimeError("synthetic delivered audit failure"),
        ]
        self.coordinator.notifier.send_alert.return_value = AlertDeliveryResult(
            state="accepted", attempts=1, message_id=77
        )

        result = await self.coordinator._dispatch_alert(alert, reservation)

        self.assertTrue(result.accepted)
        self.coordinator.notifier.send_alert.assert_awaited_once_with(alert)
        self.assertIn(alert.type, self.coordinator.circuit_breaker.last_alerts)

    async def test_cancellation_releases_reservation(self):
        alert = _alert()
        reservation = self.coordinator.circuit_breaker.reserve(
            alert.type, alert.alert_id, alert.severity
        )
        self.coordinator.notifier.send_alert.side_effect = asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await self.coordinator._dispatch_alert(alert, reservation)

        self.assertIsNotNone(
            self.coordinator.circuit_breaker.reserve(
                alert.type, "retry-after-cancel", alert.severity
            )
        )

    async def test_failed_delivery_releases_and_audits_undelivered(self):
        alert = _alert()
        reservation = self.coordinator.circuit_breaker.reserve(
            alert.type, alert.alert_id, alert.severity
        )
        self.coordinator.notifier.send_alert.return_value = AlertDeliveryResult(
            state="ambiguous", attempts=2, reason="TimedOut"
        )

        await self.coordinator._dispatch_alert(alert, reservation)

        self.assertIsNotNone(
            self.coordinator.circuit_breaker.reserve(
                alert.type, "retry", alert.severity
            )
        )
        events = [call.args[0] for call in self.coordinator.audit.log_event.await_args_list]
        self.assertEqual(events, ["ALERT_ATTEMPTED", "ALERT_UNDELIVERED"])


class TestFeedbackCallbackCompatibility(unittest.TestCase):
    def test_current_callback_preserves_alert_id(self):
        self.assertEqual(
            parse_feedback_callback("confirm|CRITICAL_HYPO|abc123"),
            ("confirm", "CRITICAL_HYPO", "abc123"),
        )

    def test_legacy_callback_remains_supported(self):
        self.assertEqual(
            parse_feedback_callback("false_WARNING_HYPO"),
            ("false", "WARNING_HYPO", None),
        )

    def test_malformed_or_unknown_callback_fails_closed(self):
        self.assertIsNone(parse_feedback_callback("confirm||missing"))
        self.assertIsNone(parse_feedback_callback("malformed"))
        self.assertIsNone(parse_feedback_callback("delete|CRITICAL_HYPO|abc"))
        self.assertIsNone(parse_feedback_callback("delete_CRITICAL_HYPO"))


if __name__ == "__main__":
    unittest.main()
