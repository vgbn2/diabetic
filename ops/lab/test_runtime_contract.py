"""Clean-checkout contracts for runtime artifacts and dependency manifests."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_SOURCE = (ROOT / "diabetic" / "config.py").read_text(encoding="utf-8")
RESTORE_WRAPPER = ROOT / "scripts" / "ops" / "stage_restore_local_nightscout.sh"
MIGRATION_SCRIPT = ROOT / "scripts" / "ops" / "migrate_nightscout.py"
ARCHIVE_FIXTURE = ROOT / "ops" / "lab" / "fixtures" / "historical_archive"


def _requirement_names(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-", "http://", "https://")):
            continue
        name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0]
        names.add(name.lower().replace("_", "-"))
    return names


class TestRuntimeArtifactContract(unittest.TestCase):
    def test_configured_weight_artifact_exists_and_is_a_torch_archive(self):
        version_match = re.search(r'ML_WEIGHTS_VERSION:\s*str\s*=\s*"([^"]+)"', CONFIG_SOURCE)
        path_match = re.search(r'"(diabetic/ml_engine/weights/diabetic_cnn_[^"]+\.pth)"', CONFIG_SOURCE)

        self.assertIsNotNone(version_match, "ML_WEIGHTS_VERSION declaration missing")
        self.assertIsNotNone(path_match, "ML_WEIGHTS_PATH artifact declaration missing")
        version = version_match.group(1)
        weight_path = ROOT / path_match.group(1)

        self.assertEqual(weight_path.name, f"diabetic_cnn_{version}.pth")
        self.assertTrue(weight_path.is_file(), f"Configured weights missing: {weight_path}")
        self.assertGreater(weight_path.stat().st_size, 0)
        self.assertTrue(zipfile.is_zipfile(weight_path), "Expected torch state_dict zip archive")


class TestDependencyContract(unittest.TestCase):
    def test_direct_runtime_dependencies_are_declared(self):
        declared = _requirement_names(ROOT / "requirements.txt")
        required = {"fastapi", "psutil", "uvicorn"}

        self.assertSetEqual(required - declared, set())

    def test_test_runner_dependencies_are_declared(self):
        declared = _requirement_names(ROOT / "requirements-dev.txt")
        required = {"pytest", "pytest-asyncio"}

        self.assertSetEqual(required - declared, set())


class TestLocalStageRestoreContract(unittest.TestCase):
    def _fake_docker_environment(self, root: Path) -> tuple[dict[str, str], Path]:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        arguments = root / "docker-arguments"
        docker = bin_dir / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "printf '%s\\n' \"$@\" > \"$DOCKER_ARGUMENTS\"\n",
            encoding="utf-8",
        )
        docker.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
        environment["DOCKER_ARGUMENTS"] = str(arguments)
        return environment, arguments

    def test_wrapper_mounts_only_selected_archive_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, arguments = self._fake_docker_environment(root)
            archive = root / "archive with spaces"
            archive.mkdir()
            (archive / "manifest.json").write_text("{}", encoding="utf-8")

            result = subprocess.run(
                [str(RESTORE_WRAPPER), str(archive)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(
                arguments.read_text(encoding="utf-8").splitlines(),
                [
                    "compose",
                    "--profile",
                    "migration",
                    "run",
                    "--rm",
                    "--build",
                    "--no-deps",
                    "--volume",
                    f"{archive.resolve()}:/archive:ro",
                    "nightscout-stage-restore",
                ],
            )

    def test_wrapper_rejects_missing_inputs_before_docker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, arguments = self._fake_docker_environment(root)
            cases = [root / "missing", root / "archive"]
            cases[1].mkdir()

            for archive in cases:
                with self.subTest(archive=archive.name):
                    result = subprocess.run(
                        [str(RESTORE_WRAPPER), str(archive)],
                        cwd=ROOT,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(arguments.exists())

    def test_wrapper_rejects_argument_count_and_unsafe_volume_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, arguments = self._fake_docker_environment(root)
            unsafe_archive = root / "archive:unsafe"
            unsafe_archive.mkdir()
            (unsafe_archive / "manifest.json").write_text("{}", encoding="utf-8")
            cases = [[], [str(root), str(root)], [str(unsafe_archive)]]

            for arguments_list in cases:
                with self.subTest(arguments=arguments_list):
                    result = subprocess.run(
                        [str(RESTORE_WRAPPER), *arguments_list],
                        cwd=ROOT,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(arguments.exists())

    def test_stage_restore_requires_explicit_target_uri(self):
        environment = os.environ.copy()
        environment["TARGET_MONGODB_URI"] = ""

        result = subprocess.run(
            [
                sys.executable,
                str(MIGRATION_SCRIPT),
                "stage-restore",
                "--source",
                str(ARCHIVE_FIXTURE),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("TARGET_MONGODB_URI is required", result.stderr)
        self.assertNotIn("mongodb://", result.stderr)


if __name__ == "__main__":
    unittest.main()
