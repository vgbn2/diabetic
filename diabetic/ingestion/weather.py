import httpx
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict
from diabetic.registry import EnvironmentReading
from diabetic.config import config

class WeatherIngestor:
    """
    Ingests environmental data (Layer 2 - The Conditions).
    Fetches Temperature, Humidity, and PM2.5 (AQI) from OpenWeatherMap.
    """
    BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
    AIR_POLLUTION_URL = "https://api.openweathermap.org/data/2.5/air_pollution"
    FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.OPENWEATHER_API_KEY
        self.logger = logging.getLogger("Bio-Quant.Weather")
        self.mock_mode = not bool(self.api_key) or getattr(config, 'WEATHER_MOCK_MODE', True)
        
        # Wave 0 Hardening: Persistent client to prevent socket leaks
        self.client = httpx.AsyncClient(timeout=10.0)
        
        if self.mock_mode:
            self.logger.warning("WEATHER_MOCK_MODE is active. Using regional baseline (Hanoi) for environmental factors.")

    async def close(self):
        """Closes the underlying HTTP client."""
        await self.client.aclose()

    async def fetch_current(self, lat: float, lon: float, strict: bool = False) -> Optional[EnvironmentReading]:
        """
        Fetches current weather and AQI.
        If strict=True, raises exceptions on API failure instead of falling back to mock.
        """
        if self.mock_mode:
            return self._get_mock_reading()

        try:
            # 1. Fetch Weather
            weather_params = {
                "lat": lat, "lon": lon, 
                "appid": self.api_key, "units": "metric"
            }
            resp = await self.client.get(self.BASE_URL, params=weather_params)
            
            if strict:
                resp.raise_for_status()
            elif resp.status_code != 200:
                self.logger.error(f"Weather API Error: {resp.status_code}")
                return self._get_mock_reading()
            
            w_data = resp.json()

            # 2. Fetch Air Quality
            aqi_params = {"lat": lat, "lon": lon, "appid": self.api_key}
            resp_aqi = await self.client.get(self.AIR_POLLUTION_URL, params=aqi_params)
            
            if strict:
                resp_aqi.raise_for_status()
            
            aqi_val = None
            if resp_aqi.status_code == 200:
                a_data = resp_aqi.json()
                # OpenWeather AQI is 1-5. PM2.5 is more granular for metabolic stress.
                aqi_val = a_data['list'][0]['components']['pm2_5']

            return EnvironmentReading(
                timestamp=datetime.now(timezone.utc),
                temperature=w_data['main']['temp'],
                humidity=w_data['main']['humidity'],
                aqi=aqi_val
            )

        except Exception as e:
            if strict:
                raise e
            self.logger.error(f"Weather fetch failed: {e}")
            return self._get_mock_reading()

    async def fetch_forecast_5d(self, lat: float, lon: float) -> List[EnvironmentReading]:
        """Provides 5-day forecast for climatological simulation."""
        if self.mock_mode:
            now = datetime.now(timezone.utc)
            return [
                EnvironmentReading(
                    timestamp=now + timedelta(hours=i*3),
                    temperature=26.5 + (i % 8 - 4) * 0.5, # Simulating daily oscillation
                    humidity=80.0,
                    aqi=45.0 + (i % 5) * 5.0 # PM2.5 flux
                ) for i in range(40) # 5 days of 3-hour intervals
            ]
        
        # Real forecast logic would go here
        return []

    def _get_mock_reading(self) -> EnvironmentReading:
        """Returns a static regional baseline (Hanoi average) for testing."""
        return EnvironmentReading(
            timestamp=datetime.now(timezone.utc),
            temperature=26.5,
            humidity=80.0,
            aqi=45.0 # PM2.5 baseline
        )
