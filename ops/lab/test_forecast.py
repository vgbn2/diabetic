"""
Unit tests for diabetic/ml_engine/forecast.py.

Uses real DigitalTwin + BasalOracle objects (no mocks). Synthetic history is
built with GlucoseFilter().update(_reading(...)), mirroring test_ingestion_pipeline.py.
"""
import math
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np

from diabetic.dsp.kalman import GlucoseFilter
from diabetic.ml_engine.forecast import build_basal_drift, build_horizons, project_24h, project_4h
from diabetic.ml_engine.oracle import BasalOracle
from diabetic.ml_engine.twin import DigitalTwin
from diabetic.registry import GlucoseReading
import diabetic.medical_constants as mc


def _reading(value: float, minutes_ago: float = 0.0) -> GlucoseReading:
    return GlucoseReading(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        value=value,
        trend="Flat",
    )


def _history(n: int = 10, base: float = 7.5) -> list:
    filt = GlucoseFilter()
    snaps = []
    for i in range(n):
        snaps.append(filt.update(_reading(base + i * 0.05, minutes_ago=float(n - 1 - i) * mc.SAMPLING_INTERVAL_MINS)))
    return snaps


class TestProject4h(unittest.TestCase):
    def setUp(self):
        self.twin = DigitalTwin()
        self.history = _history(10)

    def test_returns_correct_length(self):
        pts = project_4h(self.twin, self.history)
        expected = int(240 / mc.SAMPLING_INTERVAL_MINS) + 1
        self.assertEqual(len(pts), expected)

    def test_first_point_near_latest_filtered_value(self):
        latest = self.history[-1].filtered_value
        pts = project_4h(self.twin, self.history)
        self.assertAlmostEqual(pts[0], latest, delta=0.5)

    def test_all_finite(self):
        pts = project_4h(self.twin, self.history)
        self.assertTrue(all(math.isfinite(v) for v in pts))

    def test_empty_history_returns_empty(self):
        self.assertEqual(project_4h(self.twin, []), [])

    def test_with_oracle_drift(self):
        oracle = BasalOracle()
        oracle.params = np.array([1.5, 0.0, 7.0])
        pts = project_4h(self.twin, self.history, oracle=oracle)
        expected = int(240 / mc.SAMPLING_INTERVAL_MINS) + 1
        self.assertEqual(len(pts), expected)


class TestProject24h(unittest.TestCase):
    def setUp(self):
        self.oracle = BasalOracle()
        self.history = _history(10)

    def test_empty_when_oracle_unfit(self):
        self.assertIsNone(self.oracle.params)
        self.assertEqual(project_24h(self.oracle, self.history), [])

    def test_returns_25_points_when_fit(self):
        self.oracle.params = np.array([1.5, 0.0, 7.0])
        pts = project_24h(self.oracle, self.history)
        self.assertEqual(len(pts), 25)

    def test_values_in_physiological_range(self):
        self.oracle.params = np.array([1.5, 0.0, 7.0])
        pts = project_24h(self.oracle, self.history)
        for v in pts:
            self.assertGreater(v, 2.0)
            self.assertLess(v, 20.0)

    def test_empty_history_returns_empty(self):
        self.oracle.params = np.array([1.5, 0.0, 7.0])
        self.assertEqual(project_24h(self.oracle, []), [])


class TestBuildBasalDrift(unittest.TestCase):
    def test_returns_none_when_oracle_unfit(self):
        oracle = BasalOracle()
        ref = datetime.now(timezone.utc) - timedelta(hours=1)
        self.assertIsNone(build_basal_drift(oracle, ref, 97, mc.SAMPLING_INTERVAL_MINS))

    def test_returns_array_of_correct_shape_when_fit(self):
        oracle = BasalOracle()
        oracle.params = np.array([1.5, 0.0, 7.0])
        ref = datetime.now(timezone.utc) - timedelta(hours=1)
        drift = build_basal_drift(oracle, ref, 97, mc.SAMPLING_INTERVAL_MINS)
        self.assertIsInstance(drift, np.ndarray)
        self.assertEqual(len(drift), 97)

    def test_returns_none_for_none_oracle(self):
        self.assertIsNone(build_basal_drift(None, datetime.now(timezone.utc), 97, 2.5))


class TestBuildHorizons(unittest.TestCase):
    def setUp(self):
        self.twin = DigitalTwin()
        self.oracle = BasalOracle()
        self.history = _history(10)

    def test_keys_present(self):
        h = build_horizons(self.twin, self.oracle, self.history)
        self.assertIn("h4", h)
        self.assertIn("h1d", h)

    def test_h4_non_empty_h1d_empty_pre_fit(self):
        h = build_horizons(self.twin, self.oracle, self.history)
        self.assertGreater(len(h["h4"]), 0)
        self.assertEqual(h["h1d"], [])

    def test_h1d_populated_after_oracle_fit(self):
        self.oracle.params = np.array([1.5, 0.0, 7.0])
        h = build_horizons(self.twin, self.oracle, self.history)
        self.assertEqual(len(h["h1d"]), 25)


if __name__ == "__main__":
    unittest.main()
