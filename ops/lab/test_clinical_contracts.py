"""Clinical boundary contracts introduced by the 2026-07 safety pass."""

import math
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from diabetic.config import config
from diabetic.ingestion.cardiac import HeartRateIngestor
from diabetic.ingestion.mongo import MongoDBClient
from diabetic.ingestion.normalization import normalize_nightscout_sgv
from diabetic.ingestion.weather import WeatherIngestor
from diabetic.registry import EnvironmentReading, GlucoseReading, MetabolicSnapshot
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
