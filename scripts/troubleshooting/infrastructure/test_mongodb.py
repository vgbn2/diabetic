"""
Bio-Quant -- MongoDB Connectivity Auditor (Mission Control)
============================================================
Performs a live async probe against the Nightscout MongoDB instance.
Fail-Fast: crashes with sys.exit(1) on any auth or network failure.

Principle: Never trust object initialization. Verify with an actual database ping.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone

# -- Path Resolution --
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import ConnectionFailure, OperationFailure
except ImportError as e:
    print(f"  [X] FAILED: Missing dependency: {e}")
    print("       Run: pip install motor pymongo")
    sys.exit(1)

from diabetic.config import config

async def run_audit():
    print("\n  Bio-Quant -- MONGODB CONNECTIVITY AUDIT")
    print("  " + "=" * 50)

    # -- Probe 0: Env Var Check --
    print("\n  [0] Checking environment variables...")
    uri = config.MONGODB_URI or config.MONGO_URI
    if not uri:
        print("  [X] FAILED: MONGODB_URI or MONGO_URI not set in config/env")
        sys.exit(1)
    
    # Mask password for display
    try:
        masked_uri = uri.split('@')[1] if '@' in uri else uri
        print(f"  [OK] Mongo URI Detected: ...@{masked_uri[:40]}...")
    except Exception:
        print("  [OK] Mongo URI Detected (Malformed for masking)")

    # -- Probe 1: Connection & Ping --
    print("\n  [1] Connecting and Pinging Cluster...")
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    try:
        # The 'ping' command is cheap and verifies connectivity/auth
        await client.admin.command('ping')
        print("  [OK] Global Ping successful.")
    except ConnectionFailure as e:
        print(f"  [X] FAILED: Could not connect to MongoDB server: {e}")
        sys.exit(1)
    except OperationFailure as e:
        print(f"  [X] FAILED: Authentication failed or operation not permitted: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"  [X] FAILED: Unexpected error during ping: {e}")
        sys.exit(1)

    # -- Probe 2: Database & Collection Access --
    db_name = uri.split('/')[-1].split('?')[0] or "nightscout"
    print(f"\n  [2] Accessing Database: {db_name}...")
    db = client[db_name]
    
    try:
        # Try to count docs in 'entries' (standard Nightscout collection)
        count = await db.entries.count_documents({}, limit=1)
        print(f"  [OK] Accessed 'entries' collection. (Preview count: {count}+)")
    except Exception as e:
        print(f"  [X] FAILED: Could not access 'entries' collection: {e}")
        sys.exit(1)

    # -- Probe 3: Write Test (Audit Logs) --
    print("\n  [3] Probing 'audit_logs' with live write...")
    audit_payload = {
        "timestamp": datetime.now(timezone.utc),
        "event_type": "infra_probe",
        "message": "Fail-Fast MongoDB connectivity audit",
        "severity": "INFO"
    }
    
    try:
        result = await db.audit_logs.insert_one(audit_payload)
        if result.inserted_id:
            print(f"  [OK] Write succeeded. Inserted ID: {result.inserted_id}")
            # Immediate cleanup of probe data
            await db.audit_logs.delete_one({"_id": result.inserted_id})
            print("  [OK] Probe data cleaned up.")
        else:
            print("  [X] FAILED: Insert returned no ID.")
            sys.exit(1)
    except Exception as e:
        print(f"  [X] FAILED: Write test failed: {e}")
        sys.exit(1)

    client.close()
    print("\n  [PASS] MongoDB Connectivity Audit: SUCCESS\n")

if __name__ == "__main__":
    try:
        asyncio.run(run_audit())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n  [FATAL] Audit crash: {e}")
        sys.exit(1)
