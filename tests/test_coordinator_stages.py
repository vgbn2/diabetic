import unittest
from datetime import datetime, timezone, timedelta
from diabetic.coordinator import Coordinator
from diabetic.registry import GlucoseReading
from diabetic.utils.audit_logger import AuditLogger
from diabetic.ui.visualizer import MetabolicVisualizer
from diabetic.telegram_bot.handlers import TelegramNotifier

class TestCoordinatorStagesAndLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_coordinator_lifecycle_and_stage_seams(self):
        """Verify coordinator creation, stage methods, and clean shutdown draining."""
        audit = AuditLogger()
        coordinator = await Coordinator.create(audit_logger=audit, allow_synthetic=True)

        self.assertTrue(coordinator._initialized)
        self.assertTrue(hasattr(coordinator, "_check_signal_quality_and_freshness"))
        self.assertTrue(hasattr(coordinator, "_collect_metabolic_context"))
        self.assertTrue(hasattr(coordinator, "_compute_features_and_forecasts"))
        self.assertTrue(hasattr(coordinator, "_evaluate_and_dispatch_alerts"))
        self.assertTrue(hasattr(coordinator, "_update_state_and_visualizations"))

        now = datetime.now(timezone.utc)
        reading = GlucoseReading(timestamp=now, value=6.5, trend="Flat")

        # Stage 1: Freshness and Signal Quality
        proceed, reading_ts = coordinator._check_signal_quality_and_freshness(reading)
        self.assertTrue(proceed)
        self.assertEqual(reading_ts, now)

        # Stale reading rejection (>60m per STALE_DATA_TIMEOUT_SECS)
        stale_reading = GlucoseReading(timestamp=now - timedelta(minutes=75), value=6.5, trend="Flat")
        proceed_stale, _ = coordinator._check_signal_quality_and_freshness(stale_reading)
        self.assertFalse(proceed_stale)

        # Stage 2 & 3: Kalman & Metabolic Context
        snapshot = coordinator.filter.update(reading)
        await coordinator._collect_metabolic_context(snapshot, now, is_backfill=True)
        self.assertEqual(snapshot.glucose.value, 6.5)

        # Stage 4: Feature extraction & Forecasting
        prediction_30m = coordinator._compute_features_and_forecasts(snapshot, now)
        self.assertGreater(prediction_30m, 0)
        self.assertEqual(snapshot.predict_30m, prediction_30m)

        # Stage 5: Alert evaluation
        await coordinator._evaluate_and_dispatch_alerts(snapshot, prediction_30m, reading, is_backfill=True)

        # Stage 6: Update state
        initial_len = len(coordinator.snapshots)
        await coordinator._update_state_and_visualizations(snapshot, reading, prediction_30m)
        self.assertEqual(len(coordinator.snapshots), initial_len + 1)

        # Component lifecycle draining
        await coordinator.shutdown()
        self.assertEqual(len(coordinator.background_tasks), 0)

    async def test_visualizer_and_notifier_drain(self):
        """Verify explicit drain & close contracts on visualizer, notifier, and audit logger."""
        viz = MetabolicVisualizer(output_dir="charts")
        self.assertTrue(hasattr(viz, "drain"))
        self.assertTrue(hasattr(viz, "close"))
        await viz.close()
        self.assertEqual(len(viz._render_tasks), 0)

        notifier = TelegramNotifier()
        self.assertTrue(hasattr(notifier, "drain"))
        self.assertTrue(hasattr(notifier, "close"))
        await notifier.close()
        self.assertEqual(len(notifier.pending_tasks), 0)

        audit = AuditLogger()
        self.assertTrue(hasattr(audit, "close"))
        await audit.close()
        self.assertEqual(len(audit.background_tasks), 0)

if __name__ == "__main__":
    unittest.main()
