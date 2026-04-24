"""
Bio-Quant -- Supabase Connectivity Auditor (Mission Control)
============================================================
Performs a live async REST probe against the Supabase alerts table.
Fail-Fast: crashes with sys.exit(1) on any auth or network failure.

Principle: Never trust object initialization. Verify with an actual HTTP round-trip.
"""

import asyncio
import sys
import os

# -- Path Resolution --
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    import httpx
    from dotenv import load_dotenv
except ImportError as e:
    print(f"  [X] FAILED: Missing dependency: {e}")
    print("       Run: pip install httpx python-dotenv")
    sys.exit(1)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


async def run_audit():
    print("\n  Bio-Quant -- SUPABASE CONNECTIVITY AUDIT")
    print("  " + "=" * 50)

    # -- Probe 0: Env Var Check --
    print("\n  [0] Checking environment variables...")
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("  [X] FAILED: SUPABASE_URL or SUPABASE_KEY not set in .env")
        sys.exit(1)
    print(f"  [OK] SUPABASE_URL: {SUPABASE_URL[:40]}...")

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    # -- Probe 1: Live Insert --
    print("\n  [1] Probing alerts table with live INSERT...")
    payload = {
        "timestamp": "2026-04-24T02:44:00+00:00",
        "status": "AUDIT_PROBE",
        "message": "Bio-Quant Fail-Fast connectivity audit",
        "delivered": True,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{SUPABASE_URL}/rest/v1/alerts",
                headers=headers,
                json=payload,
            )
    except httpx.ConnectError as e:
        print(f"  [X] FAILED: Connection error to Supabase: {e}")
        sys.exit(1)
    except httpx.TimeoutException:
        print("  [X] FAILED: Request timed out (10s). Supabase unreachable.")
        sys.exit(1)

    print(f"  [INFO] HTTP Status: {response.status_code}")
    if response.status_code not in (200, 201):
        print(f"  [X] FAILED: INSERT rejected. Status {response.status_code}: {response.text[:200]}")
        sys.exit(1)
    print("  [OK] INSERT succeeded.")

    # -- Probe 2: Live READ --
    print("\n  [2] Probing alerts table with live SELECT...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/alerts",
                headers=headers,
                params={"status": "eq.AUDIT_PROBE", "order": "timestamp.desc", "limit": "1"},
            )
    except httpx.ConnectError as e:
        print(f"  [X] FAILED: Connection error on SELECT: {e}")
        sys.exit(1)

    if response.status_code not in (200, 201):
        print(f"  [X] FAILED: SELECT rejected. Status {response.status_code}: {response.text[:200]}")
        sys.exit(1)

    results = response.json()
    if not results:
        print("  [X] FAILED: SELECT returned zero rows. Data may not have persisted.")
        sys.exit(1)

    print(f"  [OK] SELECT returned {len(results)} row(s). Supabase read/write confirmed.")
    print("\n  [PASS] Supabase Connectivity Audit: SUCCESS\n")


if __name__ == "__main__":
    try:
        asyncio.run(run_audit())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n  [FATAL] Audit crash: {e}")
        sys.exit(1)