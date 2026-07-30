"""Clinical boundary contracts introduced by the 2026-07 safety pass."""

import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from diabetic import medical_constants
from diabetic.config import config
from diabetic.ingestion.cardiac import HeartRateIngestor
from diabetic.ingestion.mongo import MongoDBClient
from diabetic.ingestion.normalization import normalize_nightscout_sgv
from diabetic.ingestion.weather import WeatherIngestor
from diabetic.registry import (
    CardiacReading,
    EnvironmentReading,
    GlucoseReading,
    MetabolicSnapshot,
)
from diabetic.telegram_bot.decision_matrix import DecisionMatrix


class TestNightscoutUnitContract(unittest.TestCase):
    def test_unlabelled_sgv_defaults_to_mgdl(self):
        self.assertAlmostEqual(normalize_nightscout_sgv(39), 39 / 18.018, places=5)
        self.assertAlmostEqual(normalize_nightscout_sgv(40), 40 / 18.018, places=5)
        self.assertAlmostEqual(normalize_nightscout_sgv(41), 41 / 18.018, places=5)
        self.assertAlmostEqual(normalize_nightscout_sgv(70), 70 / 18.018, places=5)

    def test_explicit_units_are_authoritative(self):
        self.assertEqual(normalize_nightscout_sgv(5.5, "mmol/L"), 5.5)
        self.assertAlmostEqual(
            normalize_nightscout_sgv(99, "mg/dL"), 99 / 18.018, places=5
        )

    def test_unknown_and_invalid_values_are_rejected(self):
        for raw, units in [
            (100, "bananas"),
            (0, None),
            (-1, "mg/dL"),
            (math.inf, "mmol/L"),
            ("not-a-number", None),
        ]:
            with self.subTest(raw=raw, units=units):
                with self.assertRaises(ValueError):
                    normalize_nightscout_sgv(raw, units)


class TestCriticalHypoPropagation(unittest.IsolatedAsyncioTestCase):
    async def test_39_mgdl_reaches_critical_hypo_path(self):
        mmol = normalize_nightscout_sgv(39)
        reading = GlucoseReading(
            timestamp=datetime.now(timezone.utc),
            value=mmol,
            trend="Flat",
        )
        snapshot = MetabolicSnapshot(glucose=reading, filtered_value=mmol)

        alert = await DecisionMatrix().evaluate(snapshot, prediction_30m=mmol)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.type, "CRITICAL_HYPO")


class TestAlertSuppressionSafety(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _snapshot(
        *,
        glucose: float = 5.0,
        velocity: float = -0.2,
        cardiac: CardiacReading | None = None,
        predicted_hr: float = 0.0,
    ) -> MetabolicSnapshot:
        return MetabolicSnapshot(
            glucose=GlucoseReading(
                timestamp=datetime.now(timezone.utc),
                value=glucose,
                trend="Flat",
            ),
            filtered_value=glucose,
            velocity=velocity,
            cardiac=cardiac,
            predicted_hr=predicted_hr,
        )

    async def test_predicted_hr_cannot_suppress_warning_hypo(self):
        snapshot = self._snapshot(predicted_hr=180)
        alert = await DecisionMatrix().evaluate(snapshot, prediction_30m=3.5)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.type, "WARNING_HYPO")

    async def test_synthetic_or_stale_cardiac_cannot_suppress_warning_hypo(self):
        for cardiac in [
            CardiacReading(
                timestamp=datetime.now(timezone.utc),
                bpm=180,
                hrv=40,
                provenance="synthetic",
            ),
            CardiacReading(
                timestamp=datetime.now(timezone.utc)
                - timedelta(seconds=medical_constants.STALE_DATA_TIMEOUT_SECS + 1),
                bpm=180,
                hrv=40,
                provenance="real",
            ),
        ]:
            with self.subTest(provenance=cardiac.provenance):
                alert = await DecisionMatrix().evaluate(
                    self._snapshot(cardiac=cardiac),
                    prediction_30m=3.5,
                )
                self.assertIsNotNone(alert)
                self.assertEqual(alert.type, "WARNING_HYPO")

    async def test_fresh_real_exercise_cardiac_can_suppress_warning_hypo(self):
        cardiac = CardiacReading(
            timestamp=datetime.now(timezone.utc),
            bpm=180,
            hrv=40,
            provenance="real",
        )
        alert = await DecisionMatrix().evaluate(
            self._snapshot(cardiac=cardiac),
            prediction_30m=3.5,
        )
        self.assertIsNone(alert)

    async def test_feedback_cannot_suppress_current_critical_hyper(self):
        audit = AsyncMock()
        audit.get_recent_feedback.return_value = [
            {"is_false_alarm": True},
            {"is_false_alarm": True},
            {"is_false_alarm": True},
        ]
        glucose = medical_constants.HYPER_CRITICAL + 0.1
        alert = await DecisionMatrix().evaluate(
            self._snapshot(glucose=glucose, velocity=0.0),
            prediction_30m=glucose,
            audit_logger=audit,
        )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.type, "CRITICAL_HYPER")
        audit.get_recent_feedback.assert_not_awaited()


class TestTelemetryProvenance(unittest.IsolatedAsyncioTestCase):
    async def test_mock_cardiac_is_explicit_and_live_mode_rejects_it(self):
        with (
            patch.object(config, "CARDIAC_ENABLED", True),
            patch.object(config, "HEART_RATE_SENSOR_ADDRESS", "MOCK"),
        ):
            live = HeartRateIngestor(allow_synthetic=False)
            simulation = HeartRateIngestor(allow_synthetic=True)
            self.assertIsNone(await live.fetch_latest())
            reading = await simulation.fetch_latest()
        self.assertEqual(reading.source, "simulation")
        self.assertEqual(reading.provenance, "synthetic")

    async def test_mock_weather_is_explicit(self):
        with (
            patch.object(config, "WEATHER_ENABLED", True),
            patch.object(config, "WEATHER_MOCK_MODE", True),
            patch.object(config, "OPENWEATHER_API_KEY", ""),
        ):
            ingestor = WeatherIngestor(allow_synthetic=True)
            reading = await ingestor.fetch_current(0, 0)
            await ingestor.close()
        self.assertEqual(reading.source, "hanoi_baseline")
        self.assertEqual(reading.provenance, "synthetic")

    async def test_synthetic_environment_is_not_persisted(self):
        client = MongoDBClient()
        client.environment_history = AsyncMock()
        reading = EnvironmentReading(
            timestamp=datetime.now(timezone.utc),
            temperature=26.5,
            humidity=80,
            source="simulation",
            provenance="synthetic",
        )
        await client.save_environment_reading(reading)
        client.environment_history.insert_one.assert_not_awaited()
