"""Historical archive integrity and replay contracts."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diabetic import medical_constants
from diabetic.config import config
from diabetic.ingestion.offline.historical import (
    NIGHTSCOUT_ARCHIVE_COLLECTIONS,
    HistoricalDataError,
    HistoricalReplayReader,
    verify_csv_directory,
    verify_nightscout_archive,
)


FIXTURES = Path(__file__).parent / "fixtures"
ARCHIVE_FIXTURE = FIXTURES / "historical_archive"
CSV_FIXTURE = FIXTURES / "historical_chapter.csv"


def _write_collection(archive: Path, name: str, documents: list[dict]) -> None:
    body = "".join(
        json.dumps(document, separators=(",", ":")) + "\n"
        for document in documents
    ).encode()
    (archive / f"{name}.jsonl").write_bytes(body)
    manifest_path = archive / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["collections"][name] = {
        "count": len(documents),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


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

    def test_non_object_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            (archive / "manifest.json").write_text("[]", encoding="utf-8")

            report = verify_nightscout_archive(archive)

        self.assertFalse(report["ok"])
        self.assertEqual(report["errors"], ["manifest must be an object"])

    def test_malformed_collection_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            manifest_path = archive / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["collections"]["entries"] = {"count": "2", "sha256": "bad"}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = verify_nightscout_archive(archive)

        self.assertFalse(report["ok"])
        self.assertIn(
            "entries: expected count must be a non-negative integer",
            report["errors"],
        )

    def test_malformed_sha256_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            manifest_path = archive / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["collections"]["entries"]["sha256"] = "BAD"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            report = verify_nightscout_archive(archive)

        self.assertFalse(report["ok"])
        self.assertIn(
            "entries: expected sha256 must be 64 lowercase hex characters",
            report["errors"],
        )

    def test_unsafe_collection_name_and_undeclared_file_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            manifest_path = archive / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["collections"]["../outside"] = {
                "count": 0,
                "sha256": "0" * 64,
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (archive / "unexpected.jsonl").write_text("", encoding="utf-8")

            report = verify_nightscout_archive(archive)

        self.assertFalse(report["ok"])
        self.assertIn(
            "manifest: invalid collection name '../outside'", report["errors"]
        )
        self.assertIn("unexpected.jsonl: undeclared JSONL file", report["errors"])

    def test_disallowed_collections_fail_without_undeclared_noise(self):
        for name in ("roles", "auth", "sessions", "tokens", "custom_safe"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "archive"
                shutil.copytree(ARCHIVE_FIXTURE, archive)
                _write_collection(archive, name, [{"_id": f"synthetic-{name}"}])

                report = verify_nightscout_archive(archive)

                self.assertFalse(report["ok"])
                self.assertIn(
                    f"manifest: unsupported collection '{name}'", report["errors"]
                )
                self.assertNotIn(
                    f"{name}.jsonl: undeclared JSONL file", report["errors"]
                )

    def test_missing_or_null_identity_fails(self):
        for identity in ("missing", None):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "archive"
                shutil.copytree(ARCHIVE_FIXTURE, archive)
                entries = archive / "entries.jsonl"
                documents = [
                    json.loads(line)
                    for line in entries.read_text(encoding="utf-8").splitlines()
                ]
                if identity == "missing":
                    documents[0].pop("_id")
                else:
                    documents[0]["_id"] = None
                body = "".join(
                    json.dumps(document, separators=(",", ":")) + "\n"
                    for document in documents
                ).encode()
                entries.write_bytes(body)
                manifest_path = archive / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["collections"]["entries"]["sha256"] = hashlib.sha256(
                    body
                ).hexdigest()
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                report = verify_nightscout_archive(archive)

                self.assertFalse(report["ok"])
                self.assertIn(
                    "entries: missing record identity at line 1", report["errors"]
                )

    def test_all_canonical_collection_names_are_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            for name in NIGHTSCOUT_ARCHIVE_COLLECTIONS - {"entries"}:
                _write_collection(archive, name, [])

            report = verify_nightscout_archive(archive)

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(set(report["collections"]), NIGHTSCOUT_ARCHIVE_COLLECTIONS)


class TestHistoricalReplay(unittest.TestCase):
    def test_archive_replay_uses_production_unit_normalization(self):
        for prefer_mmol in (True, False):
            with self.subTest(prefer_mmol=prefer_mmol), patch.object(
                config, "PREFER_MMOL", prefer_mmol
            ):
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
            self.assertIsNotNone(readings[0].source_event_id)
            self.assertLess(readings[0].timestamp, readings[1].timestamp)

    def test_canonical_csv_replay_preserves_explicit_mmol(self):
        for prefer_mmol in (True, False):
            with self.subTest(prefer_mmol=prefer_mmol), patch.object(
                config, "PREFER_MMOL", prefer_mmol
            ):
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
    def test_disallowed_collections_fail_before_database_connection(self):
        from scripts.ops import migrate_nightscout

        for name in ("roles", "auth", "sessions", "tokens", "custom_safe"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "archive"
                shutil.copytree(ARCHIVE_FIXTURE, archive)
                _write_collection(archive, name, [{"_id": f"synthetic-{name}"}])

                with patch.object(migrate_nightscout, "_database") as database:
                    with self.assertRaises(RuntimeError):
                        migrate_nightscout.stage_restore(
                            "mongodb://localhost/test", archive
                        )

                database.assert_not_called()

    def test_missing_or_null_identity_fails_before_database_connection(self):
        from scripts.ops import migrate_nightscout

        for identity in ("missing", None):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "archive"
                shutil.copytree(ARCHIVE_FIXTURE, archive)
                entries = archive / "entries.jsonl"
                documents = [
                    json.loads(line)
                    for line in entries.read_text(encoding="utf-8").splitlines()
                ]
                if identity == "missing":
                    documents[0].pop("_id")
                else:
                    documents[0]["_id"] = None
                body = "".join(
                    json.dumps(document, separators=(",", ":")) + "\n"
                    for document in documents
                ).encode()
                entries.write_bytes(body)
                manifest_path = archive / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["collections"]["entries"]["sha256"] = hashlib.sha256(
                    body
                ).hexdigest()
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                with patch.object(migrate_nightscout, "_database") as database:
                    with self.assertRaises(RuntimeError):
                        migrate_nightscout.stage_restore(
                            "mongodb://localhost/test", archive
                        )

                database.assert_not_called()

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

    def test_symlinked_manifest_fails_before_database_connection(self):
        from scripts.ops import migrate_nightscout

        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            external = Path(temporary) / "manifest.json"
            external.write_bytes((archive / "manifest.json").read_bytes())
            (archive / "manifest.json").unlink()
            (archive / "manifest.json").symlink_to(external)

            with patch.object(migrate_nightscout, "_database") as database:
                with self.assertRaises(RuntimeError):
                    migrate_nightscout.stage_restore(
                        "mongodb://localhost/test", archive
                    )

        database.assert_not_called()

    def test_malformed_manifest_fails_before_database_connection(self):
        from scripts.ops import migrate_nightscout

        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            manifest_path = archive / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["collections"]["entries"]["count"] = -1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with patch.object(migrate_nightscout, "_database") as database:
                with self.assertRaises(RuntimeError):
                    migrate_nightscout.stage_restore(
                        "mongodb://localhost/test", archive
                    )

        database.assert_not_called()

    def test_undeclared_jsonl_fails_before_database_connection(self):
        from scripts.ops import migrate_nightscout

        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            (archive / "unexpected.jsonl").write_text("", encoding="utf-8")

            with patch.object(migrate_nightscout, "_database") as database:
                with self.assertRaises(RuntimeError):
                    migrate_nightscout.stage_restore(
                        "mongodb://localhost/test", archive
                    )

        database.assert_not_called()

    def test_symlinked_jsonl_fails_before_database_connection(self):
        from scripts.ops import migrate_nightscout

        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            shutil.copytree(ARCHIVE_FIXTURE, archive)
            external = Path(temporary) / "external.jsonl"
            external.write_bytes((archive / "entries.jsonl").read_bytes())
            (archive / "entries.jsonl").unlink()
            (archive / "entries.jsonl").symlink_to(external)

            with patch.object(migrate_nightscout, "_database") as database:
                with self.assertRaises(RuntimeError):
                    migrate_nightscout.stage_restore(
                        "mongodb://localhost/test", archive
                    )

        database.assert_not_called()


if __name__ == "__main__":
    unittest.main()
