"""Synthetic contract tests for the local Nightscout backup wrapper."""

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "backup_local_nightscout.sh"


class TestBackupWrapper(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.backups = self.root / "backups"
        self.bin.mkdir()
        self.backups.mkdir()
        self._write_executable(
            "docker",
            """#!/usr/bin/env bash
set -euo pipefail
mode="${FAKE_DOCKER_MODE:-success}"
case " $* " in
  *" mongodump "*)
    case "$mode" in
      empty) exit 0 ;;
      partial_failure) printf 'partial-archive'; exit 28 ;;
      *) printf 'synthetic-valid-archive' ;;
    esac
    ;;
  *" mongorestore "*)
    cat >/dev/null
    case "$mode" in
      corrupt|truncated) printf 'invalid archive\n' >&2; exit 2 ;;
      wrong_namespace) printf 'dry-run test.other\n' ;;
      *) printf 'dry-run nightscout.entries\n' ;;
    esac
    ;;
  *) exit 64 ;;
esac
""",
        )
        self._write_executable(
            "mv",
            """#!/usr/bin/env bash
set -euo pipefail
destination="${@: -1}"
if [[ "${FAIL_ARCHIVE_MV:-0}" == "1" && "$(basename "$destination")" == nightscout-*.archive.gz ]]; then
  exit 5
fi
exec /usr/bin/mv "$@"
""",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _write_executable(self, name: str, content: str) -> None:
        path = self.bin / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _run(self, mode: str, **extra_environment: str):
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.bin}:{environment['PATH']}",
                "FAKE_DOCKER_MODE": mode,
                "BACKUP_RETENTION_DAYS": "30",
            }
        )
        environment.update(extra_environment)
        return subprocess.run(
            ["bash", str(SCRIPT), str(self.backups)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def _published(self) -> list[Path]:
        return sorted(
            path
            for path in self.backups.iterdir()
            if not path.name.startswith(".")
        )

    def _assert_no_output_or_temporary_residue(self) -> None:
        self.assertEqual(self._published(), [])
        self.assertEqual(list(self.backups.glob(".nightscout-*")), [])

    def test_empty_archive_is_rejected_without_checksum_or_metadata(self):
        result = self._run("empty")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty archive", result.stderr)
        self._assert_no_output_or_temporary_residue()

    def test_partial_disk_style_failure_cleans_incomplete_output(self):
        result = self._run("partial_failure")

        self.assertNotEqual(result.returncode, 0)
        self._assert_no_output_or_temporary_residue()

    def test_corrupt_and_truncated_archives_are_rejected_by_dry_run(self):
        for mode in ("corrupt", "truncated"):
            with self.subTest(mode=mode):
                result = self._run(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("dry-run was rejected", result.stderr)
                self._assert_no_output_or_temporary_residue()

    def test_archive_without_nightscout_namespace_is_rejected(self):
        result = self._run("wrong_namespace")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no nightscout.entries namespace", result.stderr)
        self._assert_no_output_or_temporary_residue()

    def test_interrupted_archive_publish_removes_orphan_companions(self):
        result = self._run("success", FAIL_ARCHIVE_MV="1")

        self.assertNotEqual(result.returncode, 0)
        self._assert_no_output_or_temporary_residue()

    def test_success_publishes_validated_private_bundle(self):
        result = self._run("success")

        self.assertEqual(result.returncode, 0, result.stderr)
        archives = list(self.backups.glob("nightscout-*.archive.gz"))
        self.assertEqual(len(archives), 1)
        archive = archives[0]
        checksum = Path(f"{archive}.sha256")
        metadata_path = Path(f"{archive}.json")
        self.assertTrue(checksum.exists())
        self.assertTrue(metadata_path.exists())
        self.assertEqual(archive.read_bytes(), b"synthetic-valid-archive")

        expected_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        checksum_hash, checksum_name = checksum.read_text(encoding="utf-8").split()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(checksum_hash, expected_hash)
        self.assertEqual(checksum_name, archive.name)
        self.assertEqual(metadata["sha256"], expected_hash)
        self.assertEqual(metadata["bytes"], archive.stat().st_size)
        self.assertEqual(metadata["database"], "nightscout")
        self.assertEqual(metadata["validated_with"], "mongorestore_dry_run")
        for path in (archive, checksum, metadata_path):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(list(self.backups.glob(".nightscout-*")), [])

    def test_retention_removes_only_expired_complete_backup_bundle(self):
        old_archive = self.backups / "nightscout-20200101T000000Z.archive.gz"
        old_archive.write_bytes(b"old")
        Path(f"{old_archive}.sha256").write_text("old", encoding="utf-8")
        Path(f"{old_archive}.json").write_text("{}", encoding="utf-8")
        unrelated = self.backups / "notes.txt"
        unrelated.write_text("keep", encoding="utf-8")
        old_time = (datetime.now() - timedelta(days=3)).timestamp()
        for path in (old_archive, Path(f"{old_archive}.sha256"), Path(f"{old_archive}.json")):
            os.utime(path, (old_time, old_time))

        result = self._run("success", BACKUP_RETENTION_DAYS="0")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(old_archive.exists())
        self.assertFalse(Path(f"{old_archive}.sha256").exists())
        self.assertFalse(Path(f"{old_archive}.json").exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(len(list(self.backups.glob("nightscout-*.archive.gz"))), 1)

    def test_invalid_retention_fails_before_invoking_backup(self):
        result = self._run("success", BACKUP_RETENTION_DAYS="never")

        self.assertEqual(result.returncode, 2)
        self.assertIn("non-negative integer", result.stderr)
        self._assert_no_output_or_temporary_residue()


if __name__ == "__main__":
    unittest.main()
