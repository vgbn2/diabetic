"""Runtime startup, failure propagation, and idempotent shutdown contracts."""

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from diabetic.coordinator import Coordinator


class TestCoordinatorStartClaim(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.previous = Coordinator._instance
        Coordinator._instance = None
        self.coordinator = Coordinator()
        self.coordinator.logger = MagicMock()

    def tearDown(self):
        Coordinator._instance = self.previous

    async def test_start_claim_is_required_and_single_owner(self):
        self.coordinator.is_running = False

        with self.assertRaisesRegex(RuntimeError, "startup claim"):
            await self.coordinator.start_live_mode()

        await self.coordinator.begin_start()
        with self.assertRaisesRegex(RuntimeError, "already"):
            await self.coordinator.begin_start()

    async def test_stopped_runtime_cannot_be_started_again(self):
        self.coordinator._lifecycle_state = "stopped"

        with self.assertRaisesRegex(RuntimeError, "process replacement"):
            await self.coordinator.begin_start()


class TestMainLiveFailure(unittest.IsolatedAsyncioTestCase):
    async def test_twa_thread_failure_reaches_async_supervisor(self):
        from diabetic import main

        coordinator = SimpleNamespace()

        class ImmediateThread:
            def __init__(self, *, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        with patch("diabetic.main.threading.Thread", ImmediateThread):
            main._start_twa_thread(
                coordinator,
                MagicMock(side_effect=RuntimeError("synthetic TWA failure")),
            )
            await asyncio.sleep(0)

        with self.assertRaisesRegex(RuntimeError, "synthetic TWA failure"):
            await coordinator._twa_failure

    async def test_twa_thread_normal_return_is_a_runtime_failure(self):
        from diabetic import main

        coordinator = SimpleNamespace()

        class ImmediateThread:
            def __init__(self, *, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        with patch("diabetic.main.threading.Thread", ImmediateThread):
            main._start_twa_thread(coordinator, MagicMock())
            await asyncio.sleep(0)

        with self.assertRaisesRegex(RuntimeError, "stopped unexpectedly"):
            await coordinator._twa_failure

    async def test_supervisor_cancellation_cancels_live_task(self):
        from diabetic import main

        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def run_live():
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        coordinator = SimpleNamespace(
            start_live_mode=run_live,
            _twa_failure=asyncio.get_running_loop().create_future(),
        )
        supervisor = asyncio.create_task(
            main._run_live_with_twa_supervision(coordinator)
        )
        await started.wait()
        supervisor.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await supervisor
        self.assertTrue(cancelled.is_set())
        self.assertTrue(coordinator._twa_failure.cancelled())

    async def test_live_failure_propagates_once_without_reconstruction(self):
        from diabetic import main

        coordinator = SimpleNamespace(
            begin_start=AsyncMock(),
            start_live_mode=AsyncMock(side_effect=RuntimeError("synthetic live failure")),
            mark_failed=AsyncMock(),
            _scheduler_task=None,
            _twa_thread=None,
        )
        thread = MagicMock()
        with (
            patch.object(sys, "argv", ["diabetic.main", "live"]),
            patch.object(main.Coordinator, "create", AsyncMock(return_value=coordinator)) as create,
            patch("diabetic.main.threading.Thread", return_value=thread),
            patch.object(main.config, "AUTO_TRAIN_ENABLED", False),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic live failure"):
                await main._run_command_loop()

        create.assert_awaited_once()
        coordinator.begin_start.assert_awaited_once()
        thread.start.assert_called_once()
        coordinator.start_live_mode.assert_awaited_once()

    async def test_startup_claim_happens_before_twa_thread_creation(self):
        from diabetic import main

        order = []
        coordinator = SimpleNamespace(
            begin_start=AsyncMock(side_effect=lambda: order.append("claim")),
            start_live_mode=AsyncMock(side_effect=lambda: order.append("live")),
            mark_failed=AsyncMock(),
            _scheduler_task=None,
            _twa_thread=None,
        )
        thread = MagicMock()
        thread.start.side_effect = lambda: order.append("thread")
        with (
            patch.object(sys, "argv", ["diabetic.main", "live"]),
            patch.object(main.Coordinator, "create", AsyncMock(return_value=coordinator)),
            patch("diabetic.main.threading.Thread", return_value=thread),
            patch.object(main.config, "AUTO_TRAIN_ENABLED", False),
        ):
            await main._run_command_loop()

        self.assertEqual(order, ["claim", "thread", "live"])

    async def test_standalone_failure_marks_failed_and_shuts_down(self):
        from diabetic import coordinator as coordinator_module

        coordinator = SimpleNamespace(
            begin_start=AsyncMock(),
            start_live_mode=AsyncMock(
                side_effect=RuntimeError("synthetic standalone failure")
            ),
            mark_failed=AsyncMock(),
            shutdown=AsyncMock(),
        )
        with patch.object(
            Coordinator,
            "create",
            AsyncMock(return_value=coordinator),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic standalone failure"):
                await coordinator_module._run_standalone()

        coordinator.begin_start.assert_awaited_once()
        coordinator.start_live_mode.assert_awaited_once()
        coordinator.mark_failed.assert_awaited_once()
        coordinator.shutdown.assert_awaited_once()


class TestCoordinatorShutdown(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.previous = Coordinator._instance
        Coordinator._instance = None
        self.coordinator = Coordinator()
        self.coordinator.logger = MagicMock()
        self.coordinator._initialized = True
        self.coordinator._lifecycle_state = "running"
        self.coordinator.is_running = True
        self.coordinator.background_tasks = set()
        self.coordinator._scheduler_task = None
        self.coordinator.bot_app = None
        self.coordinator.client = SimpleNamespace(close=AsyncMock())
        self.coordinator.mongo = SimpleNamespace(close=AsyncMock())
        self.coordinator.weather_client = SimpleNamespace(close=AsyncMock())

    def tearDown(self):
        Coordinator._instance = self.previous

    async def test_shutdown_is_idempotent_and_clears_twa_projection_first(self):
        order = []
        self.coordinator.client.close.side_effect = lambda: order.append("client")
        self.coordinator.mongo.close.side_effect = lambda: order.append("mongo")
        self.coordinator.weather_client.close.side_effect = lambda: order.append("weather")

        with (
            patch(
                "diabetic.telegram_bot.twa_api.clear_api_coordinator",
                side_effect=lambda owner: order.append("projection"),
            ) as clear,
            patch("diabetic.coordinator.close_storage_db", AsyncMock(side_effect=lambda: order.append("storage"))) as close_storage,
        ):
            await self.coordinator.shutdown()
            await self.coordinator.shutdown()

        self.assertEqual(order[0], "projection")
        clear.assert_called_once_with(self.coordinator)
        self.coordinator.client.close.assert_awaited_once()
        self.coordinator.mongo.close.assert_awaited_once()
        self.coordinator.weather_client.close.assert_awaited_once()
        close_storage.assert_awaited_once()
        self.assertEqual(self.coordinator._lifecycle_state, "stopped")
        self.assertFalse(self.coordinator.is_running)

    async def test_partial_initialization_shutdown_tolerates_missing_resources(self):
        partial = Coordinator()
        partial.logger = MagicMock()
        partial._initialized = False
        partial._lifecycle_state = "initialized"
        for name in (
            "background_tasks",
            "_scheduler_task",
            "bot_app",
            "client",
            "mongo",
            "weather_client",
        ):
            if hasattr(partial, name):
                delattr(partial, name)

        with (
            patch("diabetic.telegram_bot.twa_api.clear_api_coordinator") as clear,
            patch("diabetic.coordinator.close_storage_db", AsyncMock()) as close_storage,
        ):
            await partial.shutdown()

        clear.assert_called_once_with(partial)
        close_storage.assert_awaited_once()
        self.assertEqual(partial._lifecycle_state, "stopped")

    async def test_stop_then_finalizer_shutdown_closes_once(self):
        with (
            patch("diabetic.telegram_bot.twa_api.clear_api_coordinator"),
            patch("diabetic.coordinator.close_storage_db", AsyncMock()),
        ):
            await self.coordinator.stop()
            await self.coordinator.shutdown()

        self.coordinator.client.close.assert_awaited_once()

    async def test_shutdown_closes_only_owned_audit_logger(self):
        self.coordinator.audit = SimpleNamespace(close=AsyncMock())
        self.coordinator._owns_audit_logger = True
        with (
            patch("diabetic.telegram_bot.twa_api.clear_api_coordinator"),
            patch("diabetic.coordinator.close_storage_db", AsyncMock()),
        ):
            await self.coordinator.shutdown()
        self.coordinator.audit.close.assert_awaited_once()

        Coordinator._instance = None
        injected = Coordinator()
        injected.logger = MagicMock()
        injected._initialized = True
        injected._lifecycle_state = "running"
        injected.is_running = True
        injected.background_tasks = set()
        injected._scheduler_task = None
        injected.bot_app = None
        injected.client = SimpleNamespace(close=AsyncMock())
        injected.mongo = SimpleNamespace(close=AsyncMock())
        injected.weather_client = SimpleNamespace(close=AsyncMock())
        injected.audit = SimpleNamespace(close=AsyncMock())
        injected._owns_audit_logger = False
        with (
            patch("diabetic.telegram_bot.twa_api.clear_api_coordinator"),
            patch("diabetic.coordinator.close_storage_db", AsyncMock()),
        ):
            await injected.shutdown()
        injected.audit.close.assert_not_awaited()


class TestTwaProjection(unittest.TestCase):
    def test_clear_only_removes_the_current_owner(self):
        from diabetic.telegram_bot import twa_api

        owner = object()
        other = object()
        twa_api.COORDINATOR_REF = owner
        self.assertFalse(twa_api.clear_api_coordinator(other))
        self.assertIs(twa_api.COORDINATOR_REF, owner)
        self.assertTrue(twa_api.clear_api_coordinator(owner))
        self.assertIsNone(twa_api.COORDINATOR_REF)


if __name__ == "__main__":
    unittest.main()
