import math
import unittest
from datetime import datetime, timezone, timedelta

from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic.dsp.kalman import GlucoseFilter
from diabetic.dsp.signal_quality import SignalQuality
from diabetic.utils.data_factory import TacticalForecaster
import diabetic.medical_constants as mc


def _reading(value: float, minutes_ago: float = 0.0) -> GlucoseReading:
    return GlucoseReading(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        value=value,
        trend="Flat",
    )


class TestGlucoseFilter(unittest.TestCase):
    def test_snapshot_produced_after_update(self):
        """GlucoseFilter.update() must return a MetabolicSnapshot with a positive filtered value."""
        filt = GlucoseFilter()
        reading = _reading(8.0)
        snap = filt.update(reading)
        self.assertIsInstance(snap, MetabolicSnapshot)
        self.assertGreater(snap.filtered_value, 0.0)

    def test_velocity_present_after_second_reading(self):
        """Velocity should be non-None after the Kalman filter processes two readings."""
        filt = GlucoseFilter()
        filt.update(_reading(8.0, minutes_ago=5.0))
        snap = filt.update(_reading(8.2, minutes_ago=0.0))
        self.assertIsNotNone(snap.velocity)

    def test_filtered_value_finite(self):
        """filtered_value must be a finite float across a 10-reading sequence."""
        filt = GlucoseFilter()
        for i in range(10):
            snap = filt.update(_reading(7.5 + i * 0.1, minutes_ago=float(9 - i) * 5))
        self.assertTrue(math.isfinite(snap.filtered_value))


class TestSignalQuality(unittest.TestCase):
    def test_normal_readings_pass(self):
        """Stable glucose around 8 mmol/L should not be flagged as a compression artifact."""
        readings = [_reading(8.0, 10), _reading(8.1, 5), _reading(8.0, 0)]
        self.assertFalse(SignalQuality.is_compression_low(readings))

    def test_artifact_detected(self):
        """
        Sharp non-physiological drop followed by recovery must be flagged.
        Drop: 8.0 → 4.0 over 5 min = -0.8 mmol/L/min (exceeds COMPRESSION_DROP_LIMIT).
        Recovery: 4.0 → 5.5 (+1.5, exceeds COMPRESSION_RECOVERY_MIN).
        """
        readings = [_reading(8.0, 10), _reading(4.0, 5), _reading(5.5, 0)]
        self.assertTrue(SignalQuality.is_compression_low(readings))

    def test_single_reading_never_flagged(self):
        """With fewer than 2 readings the check must return False (guard against IndexError)."""
        self.assertFalse(SignalQuality.is_compression_low([_reading(8.0)]))

    def test_thresholds_used_are_from_constants(self):
        """Verify the constants the test relies on still match medical_constants."""
        self.assertGreater(mc.COMPRESSION_DROP_LIMIT, 0.0)
        self.assertGreater(mc.COMPRESSION_RECOVERY_MIN, 0.0)


class TestTacticalForecaster(unittest.TestCase):
    def test_compute_returns_three_horizons(self):
        """12 readings at 5-min intervals should produce p15m, p60m, velocity."""
        forecaster = TacticalForecaster(age=30, weight_kg=60)
        base = datetime.now(timezone.utc) - timedelta(minutes=55)
        readings = [
            (base + timedelta(minutes=5 * i), 7.5 + i * 0.05)
            for i in range(12)
        ]
        result = forecaster.compute(readings)
        self.assertIn("p15m", result)
        self.assertIn("p60m", result)
        self.assertIn("velocity", result)
        self.assertTrue(math.isfinite(result["p15m"]))
        self.assertTrue(math.isfinite(result["p60m"]))
        self.assertTrue(math.isfinite(result["velocity"]))

    def test_empty_input_returns_zeros(self):
        """Empty reading list must not raise and should return zero-valued dict."""
        forecaster = TacticalForecaster()
        result = forecaster.compute([])
        self.assertEqual(result["velocity"], 0.0)


if __name__ == "__main__":
    unittest.main()
