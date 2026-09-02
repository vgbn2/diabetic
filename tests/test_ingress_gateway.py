import unittest
import asyncio
from datetime import datetime, timezone
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

        # 1. Ingest for custom slug tenant 'tam' (array payload with ISO dateString)
        payload_tam = [
            {
                "sgv": 126, # ~7.0 mmol/L
                "direction": "Flat",
                "dateString": now_iso,
            }
        ]

        resp = await self.client.post("/t/tam/api/v1/entries", json=payload_tam)
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
        resp_single = await self.client.post("/api/v1/entries", json=payload_single)
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
        resp_bob = await self.client.post("/t/bob/api/v1/entries", json=payload_bob)
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
        self.assertIn("326cb029ba1a2c0e9452e050e16cc31d0e658da1", cfg_data["direct_upload_url"])


if __name__ == "__main__":
    unittest.main()
