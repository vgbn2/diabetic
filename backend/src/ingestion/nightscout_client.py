import httpx
import hashlib
from datetime import datetime
from typing import List
from backend.src.registry import GlucoseReading
from backend.src.config import config

class NightscoutClient:
    """
    Resilient bridge to the Nightscout API.
    Handles authentication and conversion to internal Pydantic types.
    """
    def __init__(self):
        self.url = config.NIGHTSCOUT_URL.rstrip('/')
        self.secret = config.API_SECRET
        self.hashed_secret = hashlib.sha1(self.secret.encode()).hexdigest()
        
    async def fetch_recent_glucose(self, count: int = 20) -> List[GlucoseReading]:
        """Fetches the last N glucose entries from Nightscout."""
        endpoint = f"{self.url}/api/v1/entries.json"
        params = {"count": count}
        headers = {
            "api-secret": self.hashed_secret,
            "Accept": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            
            entries = response.json()
            readings = []
            for entry in entries:
                # Nightscout usually returns 'sgv' for sensor glucose value
                # DateString is the ISO timestamp
                if 'sgv' in entry:
                    val = float(entry['sgv'])
                    unit = "mg/dL" # Nightscout default
                    
                    # Convert to mmol/L if preferred
                    if config.PREFER_MMOL:
                        val /= 18.018
                        unit = "mmol/L"
                        
                    readings.append(GlucoseReading(
                        timestamp=datetime.fromisoformat(entry['dateString'].replace('Z', '+00:00')),
                        value=val,
                        trend=entry.get('direction', 'Flat'),
                        source="nightscout",
                        unit=unit
                    ))
            return readings

if __name__ == "__main__":
    # Simple manual test utility
    import asyncio
    async def test():
        client = NightscoutClient()
        try:
            data = await client.fetch_recent_glucose(5)
            for d in data:
                print(f"[{d.timestamp}] {d.value} {d.unit} - {d.trend}")
        except Exception as e:
            print(f"Connection failed: {e}")
            
    asyncio.run(test())
