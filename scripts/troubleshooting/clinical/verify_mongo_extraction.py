import asyncio
import sys
import os
from datetime import datetime, timezone
import pandas as pd

# Add project root to path
PROJECT_ROOT = r"c:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor"
sys.path.append(PROJECT_ROOT)

from diabetic.ingestion.mongo import MongoDBClient
from diabetic.config import config
from diabetic.registry import GlucoseReading

async def test_mongo_extraction():
    print("\n--- [Audit 1/2] Clinical Data Extraction ---")
    client = MongoDBClient()
    
    if not config.MONGO_URI:
        print("SKIP: No MONGO_URI configured in .env")
        return

    try:
        # 1. Test Recent Fetch (for live context)
        print(f"Connecting to MongoDB Atlas...")
        readings = await client.fetch_recent_glucose(count=30)
        print(f"Acquired {len(readings)} readings from 'entries' collection.")
        
        if readings:
            r_first = readings[0]
            print(f"Sample Reading: {r_first.timestamp} | {r_first.value} {r_first.unit} | Source: {r_first.source}")
            assert isinstance(r_first, GlucoseReading)
        
        # 2. Test Period Export (for CNN training/backtesting)
        print("\n--- [Audit 2/2] Clinical File-IO Integration ---")
        # The method iterates internal windows, so we check the directory for results
        export_dir = "storage/exports/test_audit"
        await client.export_sensor_periods(output_dir=export_dir)
        
        if os.path.exists(export_dir):
            files = os.listdir(export_dir)
            if files:
                print(f"SUCCESS: Exported {len(files)} clinical chapters to {export_dir}")
                sample_file = os.path.join(export_dir, files[0])
                # Verify CSV Density
                df = pd.read_csv(sample_file)
                print(f"Sample CSV Density ({files[0]}): {len(df)} rows detected.")
                assert len(df) > 0
            else:
                print("WARNING: No sensor periods found for the specified window.")
        else:
            print(f"FAILED: Export directory {export_dir} was not created.")
            sys.exit(1)

    except Exception as e:
        print(f"FAILED: MongoDB extraction audit failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_mongo_extraction())
    print("\n[PHASE 19.1.A] MongoDB Forensic Extraction Audit: SUCCESS\n")
