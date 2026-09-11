"""Persistence and Compose contracts for the current Vessel Registry."""

import os
import tempfile
import unittest
from pathlib import Path

from diabetic.storage.engine import close_db, init_db
from diabetic.storage.vessel_registry import VesselRegistry

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
PATIENT_ID = 771122


def _service_block(source: str, service: str, next_service: str) -> str:
    start = source.index(f"  {service}:")
    end = source.index(f"  {next_service}:", start)
    return source[start:end]


class TestVesselRegistryPersistence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._temporary = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._temporary.close()
        self._previous_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = (
            f"sqlite+aiosqlite:///{self._temporary.name}"
        )
        await close_db()

    async def asyncTearDown(self):
        await close_db()
        if self._previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self._previous_url
        os.unlink(self._temporary.name)

    async def test_registry_row_survives_engine_disposal_and_reopen(self):
        await init_db()
        registry = VesselRegistry()
        await registry.upsert_user(PATIENT_ID, name="Persistence Patient")
        await registry.update_user_traits(
            PATIENT_ID,
            {"age": 41, "weight_kg": 72, "height_cm": 174},
        )

        await close_db()
        await init_db()
        reopened_registry = VesselRegistry()

        user = await reopened_registry.get_user(PATIENT_ID)
        traits = await reopened_registry.get_biometrics(PATIENT_ID)
        self.assertIsNotNone(user)
        self.assertEqual(user.name, "Persistence Patient")
        self.assertIsNotNone(traits)
        self.assertEqual(traits.age, 41)
        self.assertEqual(traits.weight_kg, 72)
        self.assertEqual(traits.height_cm, 174)


class TestComposeRegistryContract(unittest.TestCase):
    def test_core_registry_database_is_inside_durable_storage_mount(self):
        source = COMPOSE_PATH.read_text(encoding="utf-8")
        core = _service_block(source, "bio-quant-core", "nightscout-stage-restore")

        self.assertIn(
            "DATABASE_URL: sqlite+aiosqlite:////app/storage/vessel_registry.db",
            core,
        )
        self.assertIn("bio_quant_storage:/app/storage", core)
        self.assertNotIn("vessel_registry.db:/", core)


if __name__ == "__main__":
    unittest.main()
