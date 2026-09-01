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

        # Ingest for custom slug tenant 'tam'
        payload = [
            {
                "sgv": 126, # ~7.0 mmol/L
                "direction": "Flat",
                "dateString": now_iso,
            }
        ]

        resp = await self.client.post("/t/tam/api/v1/entries", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["tenant"], "tam")
        self.assertEqual(data["inserted"], 1)

        # Query isolated HUD for 'tam'
        hud_resp = await self.client.get("/t/tam/api/v1/hud")
        self.assertEqual(hud_resp.status_code, 200)
        hud_data = hud_resp.json()
        self.assertEqual(hud_data["state"], "live")
        self.assertAlmostEqual(hud_data["glucose"], 7.0, delta=0.5)

        # Ensure other tenants do not have data
        other_hud_resp = await self.client.get("/t/alice/api/v1/hud")
        self.assertEqual(other_hud_resp.status_code, 200)
        other_data = other_hud_resp.json()
        self.assertEqual(other_data["state"], "waiting")


if __name__ == "__main__":
    unittest.main()
