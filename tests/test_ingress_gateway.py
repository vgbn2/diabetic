import unittest
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch
import httpx
from diabetic.coordinator import Coordinator
from diabetic.telegram_bot import twa_api


class TestIngressGateway(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.coordinator = await Coordinator.create(allow_synthetic=True)
        twa_api.COORDINATOR_REF = self.coordinator
        self.transport = httpx.ASGITransport(app=twa_api.app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.coordinator.shutdown()

    async def test_ingress_entries_and_tenant_hud(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        auth_params = {"secret": "bioquant_tam2026"}

        # 1. Ingest for custom slug tenant 'tam' (array payload with ISO dateString)
        payload_tam = [
            {
                "sgv": 126, # ~7.0 mmol/L
                "direction": "Flat",
                "dateString": now_iso,
            }
        ]

        resp = await self.client.post("/t/tam/api/v1/entries", params=auth_params, json=payload_tam)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["tenant"], "tam")
        self.assertEqual(data["inserted"], 1)

        # 2. Ingest single object with epoch ms date (xDrip+ style) on root endpoint
        payload_single = {
            "sgv": 110,
            "direction": "Flat",
            "date": now_ms,
        }
        resp_single = await self.client.post("/api/v1/entries", params=auth_params, json=payload_single)
        self.assertEqual(resp_single.status_code, 200)
        self.assertEqual(resp_single.json()["tenant"], "default")
        self.assertEqual(resp_single.json()["inserted"], 1)

        # 3. Ingest with 'mbg' alias for tenant 'bob'
        payload_bob = [
            {
                "mbg": 144, # 8.0 mmol/L
                "direction": "SingleUp",
                "date": now_ms,
            }
        ]
        resp_bob = await self.client.post("/t/bob/api/v1/entries", params=auth_params, json=payload_bob)
        self.assertEqual(resp_bob.status_code, 200)
        self.assertEqual(resp_bob.status_code, 200)
        self.assertEqual(resp_bob.json()["tenant"], "bob")

        # Query isolated HUD for 'tam'
        hud_resp = await self.client.get("/t/tam/api/v1/hud")
        self.assertEqual(hud_resp.status_code, 200)
        hud_data = hud_resp.json()
        self.assertEqual(hud_data["state"], "live")
        self.assertAlmostEqual(hud_data["glucose"], 7.0, delta=0.5)

        # Query isolated HUD for 'bob'
        hud_bob_resp = await self.client.get("/t/bob/api/v1/hud")
        self.assertEqual(hud_bob_resp.status_code, 200)
        hud_bob_data = hud_bob_resp.json()
        self.assertEqual(hud_bob_data["state"], "live")
        self.assertAlmostEqual(hud_bob_data["glucose"], 8.0, delta=0.5)

        # Ensure unseeded tenant remains waiting
        other_hud_resp = await self.client.get("/t/alice/api/v1/hud")
        self.assertEqual(other_hud_resp.status_code, 200)
        other_data = other_hud_resp.json()
        self.assertEqual(other_data["state"], "waiting")

        # 4. Verify cgm_config endpoint output
        cfg_resp = await self.client.get("/t/tam/api/v1/client/cgm_config")
        self.assertEqual(cfg_resp.status_code, 200)
        cfg_data = cfg_resp.json()
        self.assertEqual(cfg_data["tenant_slug"], "tam")
        import hashlib
        from diabetic.config import config
        expected_hash = hashlib.sha1((config.API_SECRET or "bioquant123").encode()).hexdigest()
        self.assertIn(expected_hash, cfg_data["direct_upload_url"])

        # 5. Verify GET /api/v1/entries and /t/tam/api/v1/entries return readings
        get_entries_resp = await self.client.get("/t/tam/api/v1/entries", params=auth_params)
        self.assertEqual(get_entries_resp.status_code, 200)
        entries_data = get_entries_resp.json()
        self.assertTrue(isinstance(entries_data, list))
        self.assertGreaterEqual(len(entries_data), 1)
        self.assertEqual(entries_data[0]["type"], "sgv")

    async def test_ingress_auth_enforcement(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = [{"sgv": 120, "direction": "Flat", "dateString": now_iso}]

        with patch("diabetic.config.config.API_SECRET", "test_secret_123"):
            # 1. Unauthenticated push rejected with 401
            r_unauth = await self.client.post("/t/tam/api/v1/entries", json=payload)
            self.assertEqual(r_unauth.status_code, 401)

            # 2. Wrong secret rejected with 401
            r_wrong = await self.client.post("/t/tam/api/v1/entries?secret=wrong", json=payload)
            self.assertEqual(r_wrong.status_code, 401)

            # 3. Valid raw secret in query param accepted
            r_raw = await self.client.post("/t/tam/api/v1/entries?secret=test_secret_123", json=payload)
            self.assertEqual(r_raw.status_code, 200)

            # 4. Valid SHA-1 in query param accepted
            import hashlib
            sha1_sec = hashlib.sha1("test_secret_123".encode()).hexdigest()
            r_sha1 = await self.client.post(f"/t/tam/api/v1/entries?secret={sha1_sec}", json=payload)
            self.assertEqual(r_sha1.status_code, 200)

            # 5. Valid api-secret header accepted
            r_hdr = await self.client.post("/t/tam/api/v1/entries", json=payload, headers={"api-secret": sha1_sec})
            self.assertEqual(r_hdr.status_code, 200)

            # 6. Tenant-specific dedicated device secret accepted
            reg = twa_api._get_registry()
            user_da = await reg.upsert_user(telegram_id=999002, name="Duc Anh Test")
            await reg.bind_device(
                telegram_id=999002,
                device_name="iphone12-promax",
                custom_url_slug="ducanh_test",
                api_secret_hash="5aff4eb03c7be0cecd038d60e620a23850920cbf"
            )
            r_tenant_sec = await self.client.post("/t/ducanh_test/api/v1/entries?secret=bioquant_ducanh2026", json=payload)
            self.assertEqual(r_tenant_sec.status_code, 200)


if __name__ == "__main__":
    unittest.main()
