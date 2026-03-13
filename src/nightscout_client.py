import requests
from abc import ABC, abstractmethod
from typing import List, Optional
import datetime
from .config import Config
from .data_models import GlucoseRecord
from .logger import logger

class GlucoseDataSource(ABC):
    """Abstract Base Class for any glucose data source to future-proof the system."""
    @abstractmethod
    def fetch_latest_readings(self, count: int = 10) -> List[GlucoseRecord]:
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

    def fetch_latest_readings(self, count: int = 10) -> List[GlucoseRecord]:
        """
        Fetch recent Sensor Glucose Values (SGV) and return them as GlucoseRecord objects.
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
                    # Parse timestamp (Nightscout uses ms)
                    ts = datetime.datetime.fromtimestamp(entry.get("date", 0) / 1000.0)
                    
                    records.append(GlucoseRecord(
                        timestamp=ts,
                        sgv=float(entry.get("sgv")),
                        direction=entry.get("direction", "NONE"),
                        source="Nightscout"
                    ))
            
            logger.info(f"Successfully retrieved {len(records)} records.")
            return records
            
        except Exception as e:
            logger.error(f"Failed to fetch data from Nightscout: {str(e)}")
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
