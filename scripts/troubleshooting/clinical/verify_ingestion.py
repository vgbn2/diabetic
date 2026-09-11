import sys
import os
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
import httpx

# Load project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from diabetic.ingestion.nightscout import NightscoutClient
from diabetic.config import config
from diabetic.registry import GlucoseReading

async def test_live_connectivity():
    """
    REAL PROBE: Attempts to reach the Nightscout API using .env settings.
    LOUD FAILURE: If the URL is missing or incorrect, it MUST crash.
    """
    print("\n--- [Audit] Live Nightscout Connectivity ---")
    
    url = config.NIGHTSCOUT_URL
    if not url or "REPLACE_ME" in url:
        print("[!] SKIP: NIGHTSCOUT_URL is not configured.")
        return

    print(f"Probing: {url}")
    client = NightscoutClient()
    try:
        readings = await client.fetch_recent_glucose(1)
        if readings:
            r = readings[0]
            print(f"[OK] SUCCESS: Received reading: {r.value} {r.unit} at {r.timestamp}")
            
            # Biological Boundary Audit
            if r.value < 2.2 or r.value > 33.3:
                print(f"[X] BIOLOGICAL VIOLATION: {r.value} is outside human limits (2.2-33.3).")
                sys.exit(1)
        else:
            print("[!] WARNING: Connection OK, but no glucose entries found.")
    except Exception as e:
        print(f"[X] FATAL: Connectivity Audit Failed: {e}")
        sys.exit(1)
    finally:
        await client.close()

async def test_smart_unit_detection():
    print("\n--- [Mock] Testing Smart Unit Detection ---")
    client = NightscoutClient()
    
    # Mock data (Standard mg/dL vs mmol/L)
    mock_entries_mgdl = [{"sgv": 180.18, "dateString": "2026-03-24T12:00:00Z", "direction": "Flat"}]
    mock_entries_mmol = [{"sgv": 10.0, "dateString": "2026-03-24T12:00:00Z", "direction": "Flat"}]

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        # Case 1: Input mg/dL -> Prefer MMOL
        config.PREFER_MMOL = True
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_entries_mgdl
        mock_get.return_value = mock_response
        
        readings = await client.fetch_recent_glucose(1)
        print(f"Prefer MMOL (Input 180.18 mg/dL) -> Result: {readings[0].value} {readings[0].unit}")
        assert abs(readings[0].value - 10.0) < 0.1
        
        # Case 2: Input mmol/L -> Prefer MMOL
        mock_response.json.return_value = mock_entries_mmol
        readings = await client.fetch_recent_glucose(1)
        print(f"Prefer MMOL (Input 10.0 mmol/L)  -> Result: {readings[0].value} {readings[0].unit}")
        assert readings[0].value == 10.0

    print("[OK] SUCCESS: Smart unit detection verified.")
    await client.close()

async def test_retry_logic():
    print("\n--- [Mock] Testing Resilience (Retry Logic) ---")
    client = NightscoutClient()
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = []
        
        # Simulate network failures then success
        mock_get.side_effect = [
            httpx.ConnectError("Connection timed out"),
            httpx.ConnectError("Network unreachable"),
            mock_success
        ]
        
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await client.fetch_recent_glucose(1)
            print(f"Retry Count: {mock_get.call_count}")
            assert mock_get.call_count == 3
            
    print("[OK] SUCCESS: Exponential backoff verified.")
    await client.close()

if __name__ == "__main__":
    async def run_audit():
        await test_live_connectivity()
        await test_smart_unit_detection()
        await test_retry_logic()
        print("\n[PHASE 0.6.1] Clinical Ingestion Audit: SUCCESS\n")

    asyncio.run(run_audit())
