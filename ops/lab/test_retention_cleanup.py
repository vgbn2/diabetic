"""Retention input, deletion outcome, and command truth contracts."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from diabetic.config import Settings, config
from diabetic.ingestion.mongo import MongoDBClient
from diabetic.utils.audit_logger import AuditWriteResult


class _AsyncDocuments:
    def __init__(self, documents=(), error: Exception | None = None):
        self._documents = iter(documents)
        self._error = error

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        try:
            return next(self._documents)
        except StopIteration as error:
            raise StopAsyncIteration from error


def _delete_result(count: int):
    return SimpleNamespace(deleted_count=count)


def _mongo_client() -> MongoDBClient:
    client = MongoDBClient()
    client.entries = MagicMock()
    client.treatments = MagicMock()
    client.entries.delete_many = AsyncMock(return_value=_delete_result(2))
    client.treatments.find.return_value = _AsyncDocuments()
    client.treatments.delete_many = AsyncMock(return_value=_delete_result(0))
    return client


class TestRetentionConfiguration(unittest.TestCase):
    def test_configured_retention_must_be_within_safe_bounds(self):
        for days in (0, -1, 3651):
            with self.subTest(days=days), self.assertRaises(ValidationError):
                Settings(_env_file=None, BIO_RETENTION_DAYS=days)

        self.assertEqual(
            Settings(_env_file=None, BIO_RETENTION_DAYS=1).RETENTION_DAYS,
            1,
        )
        self.assertEqual(
            Settings(_env_file=None, BIO_RETENTION_DAYS=3650).RETENTION_DAYS,
            3650,
        )


class TestMongoRetentionOutcome(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_interval_fails_before_collection_calls(self):
        client = _mongo_client()

        result = await client.run_retention_cleanup(days=-1)

        self.assertEqual(result.state, "failed")
        self.assertEqual(result.failed_phase, "validation")
        client.entries.delete_many.assert_not_awaited()
        client.treatments.find.assert_not_called()

    async def test_missing_collection_is_explicitly_unavailable(self):
        client = _mongo_client()
        client.treatments = None

        result = await client.run_retention_cleanup(days=30)

        self.assertEqual(result.state, "unavailable")
        self.assertEqual(result.failed_phase, "availability")
        client.entries.delete_many.assert_not_awaited()

    async def test_entry_failure_reports_failed_without_committed_counts(self):
        client = _mongo_client()
        client.entries.delete_many.side_effect = RuntimeError("synthetic delete failure")

        result = await client.run_retention_cleanup(days=30)

        self.assertEqual(result.state, "failed")
        self.assertEqual(result.failed_phase, "entries")
        self.assertEqual(result.entries_deleted, 0)
        self.assertEqual(result.treatments_deleted, 0)
        self.assertEqual(result.reason, "RuntimeError")

    async def test_treatment_failure_reports_irreversible_partial_result(self):
        client = _mongo_client()
        client.treatments.find.return_value = _AsyncDocuments(
            error=RuntimeError("synthetic scan failure")
        )

        result = await client.run_retention_cleanup(days=30)

        self.assertEqual(result.state, "partial")
        self.assertEqual(result.failed_phase, "treatments")
        self.assertEqual(result.entries_deleted, 2)
        self.assertEqual(result.treatments_deleted, 0)
        self.assertEqual(result.reason, "RuntimeError")

    async def test_success_returns_aggregate_counts_only(self):
        client = _mongo_client()
        client.treatments.find.return_value = _AsyncDocuments(
            [{"_id": "private-a", "created_at": "2020-01-01T00:00:00+00:00"}]
        )
        client.treatments.delete_many.return_value = _delete_result(1)

        result = await client.run_retention_cleanup(days=30)

        self.assertEqual(result.state, "completed")
        self.assertEqual(result.entries_deleted, 2)
        self.assertEqual(result.treatments_deleted, 1)
        self.assertNotIn("private-a", repr(result))

    async def test_cancellation_before_any_commit_propagates(self):
        client = _mongo_client()
        client.entries.delete_many.side_effect = asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await client.run_retention_cleanup(days=30)

    async def test_cancellation_after_entry_commit_reports_partial_truth(self):
        client = _mongo_client()
        client.treatments.find.return_value = _AsyncDocuments(
            error=asyncio.CancelledError()
        )

        result = await client.run_retention_cleanup(days=30)

        self.assertEqual(result.state, "partial")
        self.assertEqual(result.entries_deleted, 2)
        self.assertEqual(result.failed_phase, "treatments")
        self.assertEqual(result.reason, "CancelledError")


class TestRetentionOperation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from diabetic.operations.retention import RetentionCleanupResult

        self.Result = RetentionCleanupResult
        self.audit = SimpleNamespace(log_admin_action=AsyncMock())
        self.audit.log_admin_action.return_value = AuditWriteResult(True, False)
        self.mongo = SimpleNamespace(run_retention_cleanup=AsyncMock())

    async def test_completed_deletion_requires_durable_start_and_outcome_audits(self):
        from diabetic.operations.retention import execute_retention_cleanup

        self.mongo.run_retention_cleanup.return_value = self.Result(
            state="completed",
            retention_days=30,
            entries_deleted=2,
            treatments_deleted=1,
        )

        result = await execute_retention_cleanup(30, mongo=self.mongo, audit=self.audit)

        self.assertTrue(result.successful)
        self.assertEqual(
            [call.args[0] for call in self.audit.log_admin_action.await_args_list],
            ["CLEANUP_START", "CLEANUP_COMPLETE"],
        )

    async def test_failed_start_audit_prevents_any_deletion(self):
        from diabetic.operations.retention import execute_retention_cleanup

        self.audit.log_admin_action.return_value = AuditWriteResult(False, False)

        result = await execute_retention_cleanup(30, mongo=self.mongo, audit=self.audit)

        self.assertEqual(result.state, "failed")
        self.assertEqual(result.failed_phase, "audit_start")
        self.assertFalse(result.audit_durable)
        self.mongo.run_retention_cleanup.assert_not_awaited()

    async def test_partial_deletion_keeps_database_truth_when_outcome_audit_fails(self):
        from diabetic.operations.retention import execute_retention_cleanup

        self.mongo.run_retention_cleanup.return_value = self.Result(
            state="partial",
            retention_days=30,
            entries_deleted=2,
            failed_phase="treatments",
            reason="RuntimeError",
        )
        self.audit.log_admin_action.side_effect = [
            AuditWriteResult(True, False),
            AuditWriteResult(False, False),
        ]

        result = await execute_retention_cleanup(30, mongo=self.mongo, audit=self.audit)

        self.assertEqual(result.state, "partial")
        self.assertEqual(result.entries_deleted, 2)
        self.assertFalse(result.audit_durable)
        self.assertFalse(result.successful)
        self.assertEqual(
            [call.args[0] for call in self.audit.log_admin_action.await_args_list],
            ["CLEANUP_START", "CLEANUP_PARTIAL"],
        )

    async def test_outcome_audit_exception_keeps_completed_database_truth(self):
        from diabetic.operations.retention import execute_retention_cleanup

        self.mongo.run_retention_cleanup.return_value = self.Result(
            state="completed",
            retention_days=30,
            entries_deleted=2,
            treatments_deleted=1,
        )
        self.audit.log_admin_action.side_effect = [
            AuditWriteResult(True, False),
            RuntimeError("synthetic audit failure"),
        ]

        result = await execute_retention_cleanup(30, mongo=self.mongo, audit=self.audit)

        self.assertEqual(result.state, "completed")
        self.assertEqual(result.entries_deleted, 2)
        self.assertEqual(result.treatments_deleted, 1)
        self.assertFalse(result.audit_durable)
        self.assertFalse(result.successful)

    async def test_invalid_interval_is_audited_and_never_reaches_repository(self):
        from diabetic.operations.retention import execute_retention_cleanup

        result = await execute_retention_cleanup(0, mongo=self.mongo, audit=self.audit)

        self.assertEqual(result.state, "failed")
        self.assertEqual(result.failed_phase, "validation")
        self.mongo.run_retention_cleanup.assert_not_awaited()
        self.assertEqual(
            [call.args[0] for call in self.audit.log_admin_action.await_args_list],
            ["CLEANUP_START", "CLEANUP_FAILED"],
        )


class TestRetentionCallers(unittest.IsolatedAsyncioTestCase):
    async def test_structured_cli_delegates_and_returns_nonzero_for_partial(self):
        from diabetic.cli.commands import admin
        from diabetic.operations.retention import RetentionCleanupResult

        outcome = RetentionCleanupResult(
            state="partial",
            retention_days=30,
            entries_deleted=2,
            failed_phase="treatments",
        )
        with patch(
            "diabetic.operations.retention.execute_retention_cleanup",
            AsyncMock(return_value=outcome),
        ) as execute:
            exit_code = await admin.cleanup({"--retention-days": "30"})

        self.assertEqual(exit_code, 1)
        execute.assert_awaited_once()

    async def test_structured_cli_rejects_non_numeric_input_without_traceback(self):
        from diabetic.cli.commands import admin

        self.assertEqual(await admin.cleanup({"--retention-days": "never"}), 2)

    async def test_legacy_cleanup_delegates_and_returns_nonzero(self):
        from diabetic import main
        from diabetic.operations.retention import RetentionCleanupResult

        outcome = RetentionCleanupResult(
            state="unavailable",
            retention_days=config.RETENTION_DAYS,
            failed_phase="availability",
        )
        with patch(
            "diabetic.operations.retention.execute_retention_cleanup",
            AsyncMock(return_value=outcome),
        ) as execute:
            exit_code = await main.handle_admin_commands("cleanup")

        self.assertEqual(exit_code, 1)
        execute.assert_awaited_once()

    async def test_scheduled_maintenance_uses_canonical_operation(self):
        from diabetic.coordinator import Coordinator
        from diabetic.operations.retention import RetentionCleanupResult

        coordinator = Coordinator()
        coordinator.is_running = True
        coordinator.logger = MagicMock()
        coordinator.audit = SimpleNamespace(log_admin_action=AsyncMock())
        coordinator.mongo = SimpleNamespace(sync_current_period=AsyncMock())
        failed = RetentionCleanupResult(
            state="partial",
            retention_days=config.RETENTION_DAYS,
            entries_deleted=2,
            failed_phase="treatments",
        )

        async def stop_after_cycle(_seconds):
            coordinator.is_running = False

        with (
            patch("diabetic.coordinator.asyncio.sleep", AsyncMock(side_effect=stop_after_cycle)),
            patch(
                "diabetic.operations.retention.execute_retention_cleanup",
                AsyncMock(return_value=failed),
            ) as execute,
        ):
            await coordinator._maintenance_loop()

        execute.assert_awaited_once()
        coordinator.audit.log_admin_action.assert_any_await(
            "AUTO_MAINTENANCE_FAILED",
            {"state": "partial", "failed_phase": "treatments"},
        )


if __name__ == "__main__":
    unittest.main()
