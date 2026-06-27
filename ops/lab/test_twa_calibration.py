"""
Integration test for the TWA calibration write path (R7 regression gate).

`POST /api/v1/calibration` -> `VesselRegistry.update_user_traits`. This drives
the real SQLAlchemy async stack against a throwaway SQLite file (no mock DB, per
repo rule) and asserts three things the auth-only probes never reached:
  1. round-trip persistence of whitelisted bio-traits,
  2. the mass-assignment whitelist (unknown keys are dropped, not forwarded to
     update_biometrics where they would raise TypeError),
  3. the empty / unknown-only no-op contract (returns False, no phantom success).
"""
import os
import tempfile
import unittest

from diabetic.storage import engine as E
from diabetic.storage.engine import close_db, init_db
from diabetic.storage.vessel_registry import VesselRegistry

PATIENT_ID = 555111


class TestCalibrationWrite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Throwaway DB file so the real vessel_registry.db is never touched.
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._prev_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{self._tmp.name}"
        # Force the engine singletons to rebuild against the temp DB.
        await close_db()
        E._engine = None
        E._session_factory = None
        await init_db()
        self.registry = VesselRegistry()
        await self.registry.upsert_user(PATIENT_ID, name="Test Patient")

    async def asyncTearDown(self):
        await close_db()
        E._engine = None
        E._session_factory = None
        if self._prev_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self._prev_url
        os.unlink(self._tmp.name)

    async def test_round_trip_persists_whitelisted_fields(self):
        ok = await self.registry.update_user_traits(
            PATIENT_ID, {"age": 30, "weight_kg": 70, "height_cm": 175}
        )
        self.assertTrue(ok)
        traits = await self.registry.get_biometrics(PATIENT_ID)
        self.assertIsNotNone(traits)
        self.assertEqual(traits.age, 30)
        self.assertEqual(traits.weight_kg, 70)
        self.assertEqual(traits.height_cm, 175)
        self.assertEqual(traits.bmi, 22.9)  # 70 / 1.75**2

    async def test_unknown_keys_dropped_no_mass_assignment(self):
        # insulin_sensitivity is not a BioTraits column; if it leaked past the
        # whitelist into update_biometrics(**...) the call would raise TypeError.
        ok = await self.registry.update_user_traits(
            PATIENT_ID, {"insulin_sensitivity": 5, "id": 999, "age": 41}
        )
        self.assertTrue(ok)
        traits = await self.registry.get_biometrics(PATIENT_ID)
        self.assertEqual(traits.age, 41)
        self.assertFalse(hasattr(traits, "insulin_sensitivity"))

    async def test_empty_or_unknown_only_is_noop(self):
        self.assertFalse(await self.registry.update_user_traits(PATIENT_ID, {}))
        self.assertFalse(
            await self.registry.update_user_traits(PATIENT_ID, {"insulin_sensitivity": 5})
        )


if __name__ == "__main__":
    unittest.main()
