"""Clean-checkout contracts for runtime artifacts and dependency manifests."""

import re
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_SOURCE = (ROOT / "diabetic" / "config.py").read_text(encoding="utf-8")


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


if __name__ == "__main__":
    unittest.main()
