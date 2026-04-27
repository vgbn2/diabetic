import httpx
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any
from diabetic.config import config

# =============================================================================
# 🔗 [FRONTEND INTEGRATION]
# =Focus: Proactive Data Propagation to the heroku Cloud Hub
# =============================================================================
class StatelessPush:
    """
    Handles proactive data pushing from Backend to Frontend (heroku).
    Implements the 'Stateless Push' model to keep the cloud hub updated.
    """
    def __init__(self):
        self.push_url = config.FRONTEND_PUSH_URL
        self.logger = logging.getLogger("Bio-Quant.Push")
        
        # Wave 0 Hardening: Persistent client to prevent socket leaks
        self.client = httpx.AsyncClient(timeout=10.0)

    async def close(self):
        """Closes the underlying HTTP client."""
        await self.client.aclose()

    async def push_update(self, data: Dict[str, Any]):
        """Sends a metabolic update or alert to the frontend."""
        if not self.push_url:
            return

        try:
            # Task 7.1.8: Custom JSON encoder or model_dump for Pydantic/datetime
            import json
            from diabetic.registry import MetabolicSnapshot
            
            def default_converter(o):
                if isinstance(o, datetime):
                    return o.isoformat()
                if hasattr(o, "model_dump"):        # ← this first
                    return o.model_dump(mode='json')
                if hasattr(o, "dict"):              # ← fallback for pydantic v1
                    return o.dict()
            
            # We serialize manually to handle datetimes in the payload
            serialized_data = json.loads(json.dumps(data, default=default_converter))
            response = await self.client.post(self.push_url, json=serialized_data)
            # We don't block on failure, just log it.
            if response.status_code != 200:
                self.logger.debug(f"Telemetry sync skipped: status {response.status_code} (Endpoint: {self.push_url})")
        except (httpx.ConnectError, httpx.TimeoutException) as ce:
            self.logger.debug(f"Telemetry endpoint unreachable: {ce}. Continuing in headless mode.")
        except Exception as e:
            self.logger.error(f"Unexpected push failure: {e}")

# =============================================================================
# 💓 [INFRASTRUCTURE HEARTBEAT]
# =Focus: heroku service Persistence and Stay-Alive Pings (eco plan on heroku needs data polling every 30minutes)
# =============================================================================
    async def heartbeat(self):
        """Self-pinging mechanism to keep the heroku server alive."""
        if not self.push_url:
            return
            
        while True:
            try:
                # Ping the base URL (heroku root) to prevent sleeping
                base_url = "/".join(self.push_url.split("/")[:3])
                await self.client.get(base_url)
            except Exception:
                pass
            # Ping on metabolic interval (Wave 5)
            await asyncio.sleep(config.POLLING_INTERVAL_SECS)

if __name__ == "__main__":
    # Test standalone
    push = StatelessPush()
    # asyncio.run(push.push_update({"status": "ready"}))
