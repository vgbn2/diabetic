import sys
import os
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
import httpx

# Add project root to path
PROJECT_ROOT = r"c:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor"
sys.path.append(PROJECT_ROOT)

from diabetic.ingestion.nightscout import NightscoutClient
from diabetic.config import config

async def test_smart_unit_detection():
    print("\n--- Testing Smart Unit Detection ---")
    client = NightscoutClient()
    
    # Mock response for mg/dL
    mock_entries_mgdl = [{"sgv": 180.18, "dateString": "2026-03-24T12:00:00Z", "direction": "Flat"}]
    # Mock response for mmol/L
    mock_entries_mmol = [{"sgv": 10.0, "dateString": "2026-03-24T12:00:00Z", "direction": "Flat"}]

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # Case 1: Input mg/dL -> Prefer MMOL
        config.PREFER_MMOL = True
        mock_response_mgdl = MagicMock()
        mock_response_mgdl.status_code = 200
        mock_response_mgdl.json.return_value = mock_entries_mgdl
        mock_get.return_value = mock_response_mgdl
        
        readings = await client.fetch_recent_glucose(1)
        print(f"Prefer MMOL (Input 180.18 mg/dL) -> Result: {readings[0].value} {readings[0].unit}")
        assert abs(readings[0].value - 10.0) < 0.1
        
        # Case 2: Input mmol/L -> Prefer MMOL
        mock_response_mmol = MagicMock()
        mock_response_mmol.status_code = 200
        mock_response_mmol.json.return_value = mock_entries_mmol
        mock_get.return_value = mock_response_mmol
        
        readings = await client.fetch_recent_glucose(1)
        print(f"Prefer MMOL (Input 10.0 mmol/L)  -> Result: {readings[0].value} {readings[0].unit}")
        assert readings[0].value == 10.0

        # Case 3: Input mmol/L -> Prefer MGDL
        config.PREFER_MMOL = False
        readings = await client.fetch_recent_glucose(1)
        print(f"Prefer MGDL (Input 10.0 mmol/L) -> Result: {readings[0].value} {readings[0].unit}")
        assert abs(readings[0].value - 180.18) < 0.1

    print("SUCCESS: Smart unit detection works for all cases.")

async def test_retry_logic():
    print("\n--- Testing Retry Logic ---")
    client = NightscoutClient()
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # Create successful mock response
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = []
        
        # Fail twice, then succeed
        mock_get.side_effect = [
            httpx.ConnectError("Connection timed out"),
            httpx.ConnectError("Network is unreachable"),
            mock_success
        ]
        
        # We need to mock asyncio.sleep to make the test fast
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            readings = await client.fetch_recent_glucose(1)
            print(f"Call count: {mock_get.call_count}")
            assert mock_get.call_count == 3
    print("SUCCESS: Exponential backoff retries worked.")

if __name__ == "__main__":
    asyncio.run(test_smart_unit_detection())
    asyncio.run(test_retry_logic())
    print("\nALL INGESTION TESTS PASSED.\n")
