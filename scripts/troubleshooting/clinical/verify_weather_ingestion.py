import asyncio
import sys
import os
from datetime import datetime, timezone

# Add project root to path
PROJECT_ROOT = r"c:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor"
sys.path.append(PROJECT_ROOT)

from diabetic.ingestion.weather import WeatherIngestor
from diabetic.config import config
from diabetic.registry import EnvironmentReading

async def test_weather_ingestion():
    print("\n--- [Audit 1/2] Environmental Telemetry (L2) ---")
    
    # 1. Test Ingestor Integrity (Mock Baseline)
    print("Verifying Ingestor logic and data structure...")
    ingestor = WeatherIngestor(api_key=None)
    reading = await ingestor.fetch_current(21.0285, 105.8542)
    
    print(f"Reading: {reading.temperature}°C | {reading.humidity}% Hum | AQI: {reading.aqi}")
    
    # Fail Fast on Impossible Data (Biological Boundaries)
    if not (-30.0 < reading.temperature < 60.0):
        print(f"CRITICAL: Impossible temperature detected: {reading.temperature}")
        sys.exit(1)
        
    if not (0 <= reading.humidity <= 100):
        print(f"CRITICAL: Invalid humidity detected: {reading.humidity}")
        sys.exit(1)

    print("✅ Logic Check: Data structure and boundaries verified.")
    
    # 2. Test Real Acquisition (Strict Mode - Fail Fast)
    api_key = os.getenv("OPENWEATHER_API_KEY") or config.OPENWEATHER_API_KEY
    if api_key:
        print("\n--- [Audit 2/2] Real-Time Climatology (LOUD FAILURE MODE) ---")
        real_ingestor = WeatherIngestor(api_key=api_key)
        real_ingestor.mock_mode = False # Force live probe
        
        try:
            # Using strict=True to bypass fallbacks and expose real API/Network errors
            real_reading = await real_ingestor.fetch_current(
                config.LATITUDE, config.LONGITUDE, strict=True
            )
            print(f"LIVE DATA ACQUIRED: {real_reading.temperature}°C | {real_reading.humidity}%")
        except Exception as e:
            print(f"\nFATAL: Weather Audit Failed Fast. Root cause: {type(e).__name__} - {e}")
            print("Recommendation: Check OPENWEATHER_API_KEY or internet connectivity.\n")
            sys.exit(1)
    else:
        print("\nSKIP: No OPENWEATHER_API_KEY found. Skipping live telemetry audit.")

if __name__ == "__main__":
    asyncio.run(test_weather_ingestion())
    print("\n[PHASE 19.1.B] Weather Telemetry Verification: SUCCESS\n")
