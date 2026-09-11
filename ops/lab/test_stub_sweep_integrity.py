"""
Contract tests for subsystem stub sweep hardenings and mathematical integrity.
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from diabetic.dsp.kalman import GlucoseFilter
from diabetic.ingestion.cardiac import HeartRateIngestor
from diabetic.ingestion.weather import WeatherIngestor
from diabetic.ml_engine.oracle import BasalOracle
from diabetic.ml_engine.twin import DigitalTwin
from diabetic.registry import GlucoseReading, MetabolicSnapshot


class TestStubSweepIntegrity(unittest.IsolatedAsyncioTestCase):
    def test_basal_oracle_handles_curve_fit_failure_gracefully(self):
        oracle = BasalOracle()
        # Feed sparse/unfittable history
        snapshots = [
            MetabolicSnapshot(
                glucose=GlucoseReading(
                    timestamp=datetime(2026, 9, 11, 10, i * 5, tzinfo=timezone.utc),
                    value=6.0,
                    trend="Flat",
                ),
                filtered_value=6.0,
                active_carbs=0.0,
                active_insulin=0.0,
            )
            for i in range(10)
        ]
        oracle.fit(snapshots)
        self.assertIsNone(oracle.params)
        expected = oracle.get_expected_basal(
            datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(expected, 6.5)

    def test_kalman_filter_clamps_covariance_floor(self):
        kf = GlucoseFilter(dt=5.0)
        reading = GlucoseReading(
            timestamp=datetime.now(timezone.utc),
            value=7.0,
            trend="Flat",
        )
        # Initialize
        snapshot1 = kf.update(reading)
        self.assertEqual(snapshot1.filtered_value, 7.0)

        # Force degenerate zero covariance
        kf.kf.P = np.zeros((3, 3))
        reading2 = GlucoseReading(
            timestamp=datetime.now(timezone.utc),
            value=8.0,
            trend="Flat",
        )
        snapshot2 = kf.update(reading2)
        self.assertFalse(np.isnan(snapshot2.filtered_value))

    def test_digital_twin_guards_zero_resolution_mins(self):
        twin = DigitalTwin()
        curve = twin.simulate_carb_impact(carbs_g=45.0, resolution_mins=0.0)
        self.assertIsInstance(curve, np.ndarray)
        self.assertGreater(len(curve), 0)

        insulin_curve = twin.simulate_insulin_impact(units=3.0, resolution_mins=-1.0)
        self.assertIsInstance(insulin_curve, np.ndarray)
        self.assertGreater(len(insulin_curve), 0)

    async def test_cardiac_ingestor_snapshot_isolation(self):
        ingestor = HeartRateIngestor(allow_synthetic=True)
        reading1 = await ingestor.fetch_latest(reset=True)
        if reading1:
            self.assertIsNotNone(reading1.bpm)
            reading2 = await ingestor.fetch_latest(reset=True)
            self.assertIsNotNone(reading2)

    async def test_weather_forecast_mock_mode_fallback(self):
        ingestor = WeatherIngestor(allow_synthetic=True)
        forecast = await ingestor.fetch_forecast_5d(lat=21.0285, lon=105.8542)
        self.assertIsInstance(forecast, list)
        if ingestor.mock_mode:
            self.assertEqual(len(forecast), 40)
            self.assertEqual(forecast[0].provenance, "synthetic")


if __name__ == "__main__":
    unittest.main()
