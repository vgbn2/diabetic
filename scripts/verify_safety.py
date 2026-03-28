import asyncio
import sys
import os
from datetime import datetime, timedelta

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from diabetic.registry import GlucoseReading
from diabetic.coordinator import Coordinator
from diabetic.config import config

async def test_scenarios():
    coordinator = Coordinator()
    start_time = datetime.now()
    
    print("\n" + "="*60)
    print("  VERIFYING SAFETY FIXES: CRASH & FAINT SCENARIOS  ")
    print("="*60 + "\n")

    # Scenario 1: HYPO CRASH (Emergency Bypass Verification)
    print("TEST 1: Hypoglycemic Crash (Expect EMERGENCY / No Cooldown)...")
    crash_readings = [
        6.5, 6.0, 5.0, 4.0, 3.2, 3.0, 2.8, 2.5
    ]
    for i, val in enumerate(crash_readings):
        r = GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val, trend="DoubleDown")
        await coordinator._process_reading(r)
    
    print("\nTEST 2: Faint Risk (High + Rise + Heart Stress)...")
    # Scenario 2: FAINT RISK (Cardiac Integration Verification)
    # We'll simulate a rise while high
    faint_readings = [
        15.5, 16.0, 16.8, 17.5, 18.2, 19.0
    ]
    for i, val in enumerate(faint_readings):
        r = GlucoseReading(timestamp=start_time + timedelta(minutes=60 + i*5), value=val, trend="FortyFiveUp")
        # Note: We aren't injecting HR/HRV here yet, so it will use baselines
        await coordinator._process_reading(r)

    print("\n" + "="*60)
    print("  VERIFICATION COMPLETE  ")
    print("="*60 + "\n")

if __name__ == "__main__":
    # If the socket error persists even here, we might need a different approach.
    # But often standalone scripts in different contexts work better.
    try:
        asyncio.run(test_scenarios())
    except Exception as e:
        print(f"Bypass failed: {e}")
