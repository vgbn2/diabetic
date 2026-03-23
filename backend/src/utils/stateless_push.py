import httpx
import logging
import asyncio
from typing import Dict, Any
from backend.src.config import config

class StatelessPush:
    """
    Handles proactive data pushing from Backend to Frontend (Render).
    Implements the 'Stateless Push' model to keep the cloud hub updated.
    """
    def __init__(self):
        self.push_url = config.FRONTEND_PUSH_URL
        self.logger = logging.getLogger("Bio-Quant.Push")

    async def push_update(self, data: Dict[str, Any]):
        """Sends a metabolic update or alert to the frontend."""
        if not self.push_url:
            return

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(self.push_url, json=data)
                # We don't block on failure, just log it.
                if response.status_code != 200:
                    self.logger.warning(f"Push failed with status {response.status_code}")
        except Exception as e:
            self.logger.error(f"Failed to push data to frontend: {e}")

    async def heartbeat(self):
        """Self-pinging mechanism to keep the Render server alive."""
        if not self.push_url:
            return
            
        while True:
            try:
                # Ping the base URL (Render root) to prevent sleeping
                base_url = "/".join(self.push_url.split("/")[:3])
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.get(base_url)
            except Exception:
                pass
            # Ping every 10 minutes
            await asyncio.sleep(600)

if __name__ == "__main__":
    # Test standalone
    push = StatelessPush()
    # asyncio.run(push.push_update({"status": "ready"}))
