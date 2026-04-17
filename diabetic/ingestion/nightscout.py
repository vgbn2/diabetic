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
        
        # Wave 3 Hardening: Persistent AsyncClient to prevent connection exhaustion
        self.client = httpx.AsyncClient(timeout=15.0)

    async def close(self):
        """Closes the underlying HTTP client."""
        await self.client.aclose()
        
    def _get_headers(self, use_plain: bool = False) -> dict:
        """Determines the correct authentication header."""
        headers = {"Accept": "application/json"}
        # If explicitly told to use plain, or if it's already a token
        if use_plain or self.secret.startswith("subject-") or len(self.secret) > 32:
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
                response = await self.client.get(endpoint, params=params, headers=headers)
                response.raise_for_status()
                return self._parse_entries(response.json())
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)

    async def fetch_since(self, since_dt: datetime) -> List[GlucoseReading]:
        """
        Fetches all glucose entries since since_dt.
        Uses Nightscout find query syntax.
        """
        endpoint = f"{self.url}/api/v1/entries.json"
        # Format: find[dateString][$gt]=2026-03-29T00:00:00.000Z
        iso_str = since_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        params = {"find[dateString][$gt]": iso_str, "count": 1000} # High count to capture the gap
        headers = self._get_headers()
        
        try:
            response = await self.client.get(endpoint, params=params, headers=headers)
            response.raise_for_status()
            # Nightscout returns most recent first, we reverse to process chronologically
            readings = self._parse_entries(response.json())
            readings.reverse() 
            return readings
        except Exception as e:
            # Task 8.2.1: Non-fatal, live polling will take over.
            print(f"Backfill fetch failed: {e}")
            return []

    def _parse_entries(self, entries: List[dict]) -> List[GlucoseReading]:
        """Shared logic for parsing Nightscout entry JSON."""
        readings = []
        for entry in entries:
            if 'sgv' in entry:
                raw = float(entry['sgv'])
                units_in_entry = entry.get('units', '').lower()
                # Safe check: Nightscout uses 'mmol' or 'mmol/L'. 
                # Floor for mg/dL is typically 40. Values below 30 are almost certainly mmol.
                is_already_mmol = ("mmol" in units_in_entry or (not units_in_entry and raw < 40))
                
                if config.PREFER_MMOL:
                    value = raw if is_already_mmol else raw / medical_constants.MMOL_TO_MGDL
                    unit = "mmol/L"
                else:
                    value = raw * medical_constants.MMOL_TO_MGDL if is_already_mmol else raw
                    unit = "mg/dL"
                
                # Robust timestamp parsing
                ts_str = entry['dateString'].replace('Z', '+00:00')
                try:
                    # Try isoformat first (standard)
                    ts = datetime.fromisoformat(ts_str)
                except ValueError:
                    # Fallback for non-standard precision or older Python
                    try:
                        ts = datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                    except Exception:
                        continue # Skip unparseable reading
                    
                readings.append(GlucoseReading(
                    timestamp=ts,
                    value=round(value, 2),
                    trend=entry.get('direction', 'Flat'),
                    source="nightscout",
                    unit=unit
                ))
        return readings

    async def fetch_recent_treatments(self, count: int = 10) -> Tuple[Optional[InsulinDose], Optional[MealEvent]]:
        """Fetches the latest insulin and carb events from Nightscout."""
        endpoint = f"{self.url}/api/v1/treatments.json"
        params = {"count": count}
        headers = self._get_headers()
        
        try:
            response = await self.client.get(endpoint, params=params, headers=self._get_headers())
            
            # C3 Fix: Fallback to plain secret if 401 (Handles Heroku v3+ issues)
            if response.status_code == 401:
                response = await self.client.get(endpoint, params=params, headers=self._get_headers(use_plain=True))
            
            response.raise_for_status()
            treatments = response.json()
            now = datetime.now(timezone.utc)
            
            latest_insulin: Optional[InsulinDose] = None
            latest_meal: Optional[MealEvent] = None
            
            for t in treatments:
                # Parse timestamp (created_at is standard for treatments)
                if 'created_at' not in t:
                    continue
                
                try:
                    ts = datetime.fromisoformat(t['created_at'].replace('Z', '+00:00'))
                except ValueError:
                    continue
                
                # C3 Fix: Verify treatment is within 4-hour metabolic window
                if (now - ts).total_seconds() > medical_constants.MEAL_WINDOW_MINS * 60:
                    continue

                # Parse Insulin
                if 'insulin' in t and not latest_insulin:
                    ev_type = t.get('eventType', 'correction').lower()
                    # Map Nightscout types to Twin types (RAPID/LONG)
                    # Rule: Most Nightscout events are rapid (Bolus, correction).
                    # Basal/Long tags are long-acting.
                    insulin_type = "RAPID"
                    if any(x in ev_type for x in ["long", "basal", "levermir", "lantus", "tresiba"]):
                        insulin_type = "LONG"

                    latest_insulin = InsulinDose(
                        timestamp=ts,
                        units=float(t['insulin']),
                        type=insulin_type
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
