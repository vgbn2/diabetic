import asyncio
import sys
import os
from datetime import datetime, timezone
import pandas as pd

# Load project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from diabetic.ingestion.mongo import MongoDBClient
from diabetic.config import config
from diabetic.registry import GlucoseReading

async def test_mongo_extraction():
    print("\n--- [Audit 1/2] Clinical Data Extraction ---")
    client = MongoDBClient()
    
    active_mongo = config.MONGODB_URI or config.MONGO_URI
    if not active_mongo:
        print("[!] SKIP: No MongoDB URI configured.")
        return

    print(f"Connecting to: {active_mongo[:20]}...")
    try:
        # 1. Test Recent Fetch (for live context)
        readings = await client.fetch_recent_glucose(count=30)
        print(f"[OK] Acquired {len(readings)} readings from 'entries' collection.")
        
        if readings:
            r = readings[0]
            print(f"Sample: {r.timestamp} | {r.value} {r.unit}")
            
            # Biological Boundary Audit
            if r.value < 2.0 or r.value > 33.3:
                print(f"[X] BIOLOGICAL VIOLATION in MongoDB data: {r.value} mmol/L")
                sys.exit(1)
        
        # 2. Test Period Export (for CNN training/backtesting)
        print("\n--- [Audit 2/2] Clinical File-IO Integration ---")
        export_dir = "storage/exports/test_audit"
        await client.export_sensor_periods(output_dir=export_dir)
        
        if os.path.exists(export_dir):
            files = os.listdir(export_dir)
            if files:
                print(f"[OK] SUCCESS: Exported {len(files)} chapters to {export_dir}")
                sample_file = os.path.join(export_dir, files[0])
                df = pd.read_csv(sample_file)
                print(f"Sample CSV Density: {len(df)} rows.")
                assert len(df) > 0
            else:
                print("[!] WARNING: Export dir exists but is empty. Check sensor availability.")
        else:
            print(f"[X] FATAL: Export directory {export_dir} was not created.")
            sys.exit(1)

    except Exception as e:
        print(f"[X] FATAL: MongoDB extraction audit failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(test_mongo_extraction())
        print("\n[PHASE 0.6.1] Clinical MongoDB Audit: SUCCESS\n")
    except KeyboardInterrupt:
        pass
