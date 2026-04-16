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
    
    # 1. Test Mock Mode
    print("Testing MOCK mode fidelity (Hanoi Baseline)...")
    mock_ingestor = WeatherIngestor(api_key=None)
    mock_reading = await mock_ingestor.fetch_current(21.0285, 105.8542)
    
    print(f"Mock Reading: {mock_reading.temperature}°C | {mock_reading.humidity}% Hum | AQI: {mock_reading.aqi}")
    assert mock_reading.temperature == 26.5
    assert mock_reading.aqi == 45.0
    
    # 2. Test Real Acquisition (If configured)
    api_key = os.getenv("OPENWEATHER_API_KEY") or config.OPENWEATHER_API_KEY
    if api_key:
        print("\n--- [Audit 2/2] Real-Time Climatology Acquisition ---")
        real_ingestor = WeatherIngestor(api_key=api_key)
        # Temporarily force real mode if key exists
        real_ingestor.mock_mode = False
        
        real_reading = await real_ingestor.fetch_current(config.LATITUDE, config.LONGITUDE)
        if real_reading:
            print(f"LIVE DATA: {real_reading.temperature}°C | {real_reading.humidity}% | AQI: {real_reading.aqi}")
            assert isinstance(real_reading, EnvironmentReading)
            assert real_reading.temperature != 0.0 # Basic sanity check
        else:
            print("FAILED: Live weather acquisition returned None.")
            sys.exit(1)
    else:
        print("\nSKIP: No OPENWEATHER_API_KEY found. Skipping live telemetry audit.")

if __name__ == "__main__":
    asyncio.run(test_weather_ingestion())
    print("\n[PHASE 19.1.B] Weather Telemetry Verification: SUCCESS\n")
