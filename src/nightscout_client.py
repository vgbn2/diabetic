import requests
from abc import ABC, abstractmethod
from typing import List, Optional
import datetime
from .config import Config
from .data_models import GlucoseReading, TreatmentEvent
from .logger import logger

class GlucoseDataSource(ABC):
    """Abstract Base Class for any glucose data source to future-proof the system."""
    @abstractmethod
    def fetch_latest_readings(self, count: int = 10) -> List[GlucoseReading]:
        pass

class NightscoutClient(GlucoseDataSource):
    """
    Client for fetching data from the Nightscout API.
    Implements the GlucoseDataSource interface.
    """
    
    def __init__(self, url: str = Config.NIGHTSCOUT_URL, secret: str = Config.NIGHTSCOUT_API_SECRET):
        self.url = url
        self.secret = secret
        self.session = requests.Session()
        
        self.headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        if self.secret:
            self.headers['API-SECRET'] = self.secret

    def fetch_latest_readings(self, count: int = 10) -> List[GlucoseReading]:
        """
        Fetch recent Sensor Glucose Values (SGV) and return them as GlucoseReading objects.
        """
        endpoint = f"{self.url}/api/v1/entries.json"
        params = {'count': count}
        
        logger.info(f"Fetching last {count} entries from Nightscout...")
        
        try:
            response = self.session.get(endpoint, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            records = []
            
            for entry in data:
                if entry.get("type") == "sgv" or "sgv" in entry:
                    ts = datetime.datetime.fromtimestamp(entry.get("date", 0) / 1000.0)
                    records.append(GlucoseReading(
                        timestamp=ts,
                        sgv=float(entry.get("sgv")),
                        direction=entry.get("direction", "NONE"),
                        source="Nightscout"
                    ))
            
            logger.info(f"Successfully retrieved {len(records)} readings.")
            return records
        except Exception as e:
            logger.error(f"Failed to fetch data from Nightscout: {str(e)}")
            return []

    def fetch_treatments(self, days: int = 1) -> List[TreatmentEvent]:
        """Fetch insulin and carb events from Nightscout."""
        endpoint = f"{self.url}/api/v1/treatments.json"
        # Calculate time window
        since = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        params = {'find[created_at][$gte]': since}
        
        try:
            response = self.session.get(endpoint, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            treatments = []
            for t in data:
                insulin = float(t.get("insulin", 0) or 0)
                carbs = float(t.get("carbs", 0) or 0)
                if insulin > 0 or carbs > 0:
                    # Nightscout format can vary
                    ts_str = t.get("created_at")
                    try:
                        ts = datetime.datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                    except:
                        ts = datetime.datetime.now() # Fallback
                        
                    treatments.append(TreatmentEvent(
                        timestamp=ts,
                        insulin=insulin,
                        carbs=carbs,
                        event_type=t.get("eventType", "Meal"),
                        source="Nightscout"
                    ))
            return treatments
        except Exception as e:
            logger.error(f"Failed to fetch treatments: {e}")
            return []

if __name__ == "__main__":
    # Test execution with logging
    client = NightscoutClient()
    latest = client.fetch_latest_readings(count=3)
    
    if latest:
        for rec in latest:
            print(f"[{rec.timestamp}] {rec.sgv} mg/dL | Direction: {rec.direction}")
    else:
        print("No records found. Check your configuration.")
