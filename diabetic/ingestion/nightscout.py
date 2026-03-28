import httpx
import hashlib
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from diabetic.registry import GlucoseReading, InsulinDose, MealEvent
from diabetic.config import config
from diabetic import medical_constants

class NightscoutClient:
    """
    Resilient bridge to the Nightscout API.
    Handles authentication, units detection, and automatic retries.
    """
    def __init__(self):
        self.url = config.NIGHTSCOUT_URL.rstrip('/')
        self.secret = config.API_SECRET
        self.hashed_secret = hashlib.sha1(self.secret.encode()).hexdigest()
        
    def _get_headers(self) -> dict:
        """Determines the correct authentication header."""
        headers = {"Accept": "application/json"}
        # Check if secret is a Bearer token (subject-...) or raw secret
        if self.secret.startswith("subject-") or len(self.secret) > 32:
            headers["Authorization"] = f"Bearer {self.secret}"
        else:
            headers["api-secret"] = self.hashed_secret
        return headers

    async def fetch_recent_glucose(self, count: int = 20) -> List[GlucoseReading]:
        """Fetches the last N glucose entries from Nightscout with exponential backoff."""
        endpoint = f"{self.url}/api/v1/entries.json"
        params = {"count": count}
        headers = self._get_headers()
        
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(endpoint, params=params, headers=headers)
                    response.raise_for_status()
                    
                    entries = response.json()
                    readings = []
                    for entry in entries:
                        if 'sgv' in entry:
                            raw = float(entry['sgv'])
                            
                            # Smart Unit Detection:
                            # 1. Use 'units' field if provided in Nightscout metadata.
                            # 2. Heuristic: if raw < 30, it is physiologically likely to be mmol/L.
                            units_in_entry = entry.get('units', '').lower()
                            is_already_mmol = (units_in_entry == 'mmol' or 
                                              (not units_in_entry and raw < 30))
                            
                            if config.PREFER_MMOL:
                                value = raw if is_already_mmol else raw / medical_constants.MMOL_TO_MGDL
                                unit = "mmol/L"
                            else:
                                value = raw * medical_constants.MMOL_TO_MGDL if is_already_mmol else raw
                                unit = "mg/dL"
                                
                            readings.append(GlucoseReading(
                                timestamp=datetime.fromisoformat(entry['dateString'].replace('Z', '+00:00')),
                                value=round(value, 2),
                                trend=entry.get('direction', 'Flat'),
                                source="nightscout",
                                unit=unit
                            ))
                    return readings
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)

    async def fetch_recent_treatments(self, count: int = 10) -> Tuple[Optional[InsulinDose], Optional[MealEvent]]:
        """Fetches the latest insulin and carb events from Nightscout."""
        endpoint = f"{self.url}/api/v1/treatments.json"
        params = {"count": count}
        headers = self._get_headers()
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(endpoint, params=params, headers=headers)
                response.raise_for_status()
                
                treatments = response.json()
                latest_insulin = None
                latest_meal = None
                
                for t in treatments:
                    # Parse timestamp (created_at is standard for treatments)
                    if 'created_at' not in t:
                        continue
                    ts = datetime.fromisoformat(t['created_at'].replace('Z', '+00:00'))
                    
                    # Parse Insulin
                    if 'insulin' in t and not latest_insulin:
                        latest_insulin = InsulinDose(
                            timestamp=ts,
                            units=float(t['insulin']),
                            type=t.get('eventType', 'correction')
                        )
                    
                    # Parse Carbs
                    if 'carbs' in t and not latest_meal:
                        latest_meal = MealEvent(
                            timestamp=ts,
                            carbs=float(t['carbs'])
                        )
                        
                    if latest_insulin and latest_meal:
                        break
                        
                return latest_insulin, latest_meal
                
        except Exception:
            # Treatments are non-critical for the core smoothed loop
            return None, None

if __name__ == "__main__":
    import asyncio
    async def test():
        client = NightscoutClient()
        try:
            print("Fetching glucose...")
            data = await client.fetch_recent_glucose(5)
            for d in data: print(f"  {d}")
            print("\nFetching treatments...")
            ins, meal = await client.fetch_recent_treatments()
            print(f"  Latest Insulin: {ins}")
            print(f"  Latest Meal: {meal}")
        except Exception as e:
            print(f"Test failed: {e}")
            
    asyncio.run(test())
