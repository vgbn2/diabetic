"""Historical archive integrity and replay contracts."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diabetic import medical_constants
from diabetic.config import config
from diabetic.ingestion.offline.historical import (
    HistoricalDataError,
    HistoricalReplayReader,
    verify_csv_directory,
    verify_nightscout_archive,
)


FIXTURES = Path(__file__).parent / "fixtures"
ARCHIVE_FIXTURE = FIXTURES / "historical_archive"
CSV_FIXTURE = FIXTURES / "historical_chapter.csv"


class TestHistoricalArchiveVerification(unittest.TestCase):
    def test_valid_synthetic_archive(self):
        report = verify_nightscout_archive(ARCHIVE_FIXTURE)

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["collections"]["entries"]["count"], 2)
        self.assertTrue(report["collections"]["entries"]["hash_ok"])
        self.assertTrue(
            report["collections"]["entries"]["timestamps_monotonic"]
        )

    def test_hash_mismatch_fails_without_count_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            entries = archive / "entries.jsonl"
            entries.write_text(
                entries.read_text(encoding="utf-8").replace(
                    '"FortyFiveUp"', '"Flat"'
                ),
                encoding="utf-8",
            )

            report = verify_nightscout_archive(archive)

        self.assertFalse(report["ok"])
        self.assertEqual(report["collections"]["entries"]["count"], 2)
        self.assertIn("entries: sha256 mismatch", report["errors"])

    def test_manifest_count_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            manifest_path = archive / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["collections"]["entries"]["count"] = 3
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = verify_nightscout_archive(archive)

        self.assertFalse(report["ok"])
        self.assertIn("entries: expected 3 records, found 2", report["errors"])

    def test_malformed_extended_json_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            (archive / "entries.jsonl").write_text("{not-json}\n", encoding="utf-8")

            report = verify_nightscout_archive(archive)

        self.assertFalse(report["ok"])
        self.assertEqual(report["collections"]["entries"]["parse_errors"], 1)


class TestHistoricalReplay(unittest.TestCase):
    def test_archive_replay_uses_production_unit_normalization(self):
        with patch.object(config, "PREFER_MMOL", True):
            readings = list(
                HistoricalReplayReader.from_archive(ARCHIVE_FIXTURE).stream()
            )

        self.assertEqual(len(readings), 2)
        self.assertAlmostEqual(
            readings[0].value,
            39 / medical_constants.MMOL_TO_MGDL,
            places=5,
        )
        self.assertEqual(readings[0].unit, "mmol/L")
        self.assertLess(readings[0].timestamp, readings[1].timestamp)

    def test_canonical_csv_replay_preserves_explicit_mmol(self):
        with patch.object(config, "PREFER_MMOL", True):
            readings = list(
                HistoricalReplayReader.from_csvs([CSV_FIXTURE]).stream()
            )

        self.assertEqual([reading.value for reading in readings], [5.5, 6.0])
        self.assertTrue(all(reading.unit == "mmol/L" for reading in readings))

    def test_mixed_schema_csv_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "consolidated_training.csv"
            path.write_text(
                "timestamp,glucose,timestamp_utc,glucose_mmol_l\n"
                "2026-01-01T00:00:00+00:00,5.5,,\n",
                encoding="utf-8",
            )
            with self.assertRaises(HistoricalDataError):
                HistoricalReplayReader.from_csvs([path])

    def test_csv_directory_profile_is_aggregate_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "exports"
            directory.mkdir()
            shutil.copy2(CSV_FIXTURE, directory / "[01-01-26_to_01-02-26].csv")

            report = verify_csv_directory(directory)

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["unique_records"], 2)
        self.assertNotIn("5.5", json.dumps(report))


class TestStageRestoreIntegrity(unittest.TestCase):
    def test_corruption_fails_before_database_connection(self):
        from scripts.ops import migrate_nightscout

        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            entries = archive / "entries.jsonl"
            entries.write_text(
                entries.read_text(encoding="utf-8").replace(
                    '"FortyFiveUp"', '"Flat"'
                ),
                encoding="utf-8",
            )

            with patch.object(migrate_nightscout, "_database") as database:
                with self.assertRaises(RuntimeError):
                    migrate_nightscout.stage_restore(
                        "mongodb://localhost/test", archive
                    )

        database.assert_not_called()


if __name__ == "__main__":
    unittest.main()
