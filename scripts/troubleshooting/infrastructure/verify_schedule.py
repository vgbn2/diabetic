"""
Bio-Quant -- Schedule Logic Auditor (Mission Control)
======================================================
Verifies that the schedule_manager and DigitalTwin correctly override 
hormonal heuristics based on the temporal registry.

Fail-Fast: Crashes with sys.exit(1) if logic mismatches.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone

# -- Path Resolution --
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from diabetic.utils.schedule import schedule_manager
from diabetic.ml_engine.twin import DigitalTwin

async def run_audit():
    print("\n  Bio-Quant -- SCHEDULE LOGIC AUDIT")
    print("  " + "=" * 50)

    twin = DigitalTwin()
    
    # Test Time 1: 3:00 AM (Monday) - Should be SLEEP (Indoor, 1.1x Resistance)
    print("\n  [1] Testing Case: SLEEP (3:00 AM)")
    t1 = datetime(2026, 4, 13, 3, 0, tzinfo=timezone.utc)
    event1 = schedule_manager.get_event_at(t1)
    mult1 = twin.get_hormonal_multiplier(t1)
    
    if not event1 or event1.type != "SLEEP":
        print(f"  [X] FAILED: Expected SLEEP at 3:00 AM, got {event1.type if event1 else 'None'}")
        sys.exit(1)
    if mult1 <= 1.0:
        print(f"  [X] FAILED: Expected increased resistance (>1.0) during sleep, got {mult1:.4f}")
        sys.exit(1)
    print(f"  [OK] Case 1 Passed. Event: {event1.type}, Multiplier: {mult1:.4f}")

    # Test Time 2: 8:30 AM (Monday) - Should be COMMUTE (Outdoor)
    print("\n  [2] Testing Case: COMMUTE/OUTDOOR (8:30 AM)")
    t2 = datetime(2026, 4, 13, 8, 30, tzinfo=timezone.utc)
    event2 = schedule_manager.get_event_at(t2)
    
    if not event2 or not event2.is_outdoor:
        print(f"  [X] FAILED: Expected outdoor event at 8:30 AM, got {event2.name if event2 else 'None'}")
        sys.exit(1)
    print(f"  [OK] Case 2 Passed. Event: {event2.name}, Outdoor: {event2.is_outdoor}")

    # Test Time 3: 7:00 PM (Monday) - Should be GYM (0.8x Resistance)
    print("\n  [3] Testing Case: WORKOUT (7:00 PM)")
    t3 = datetime(2026, 4, 13, 19, 0, tzinfo=timezone.utc)
    event3 = schedule_manager.get_event_at(t3)
    mult3 = twin.get_hormonal_multiplier(t3)
    
    if not event3 or event3.type != "WORKOUT":
        print(f"  [X] FAILED: Expected WORKOUT at 7:00 PM, got {event3.type if event3 else 'None'}")
        sys.exit(1)
    if mult3 >= 1.0:
        print(f"  [X] FAILED: Expected decreased resistance (<1.0) during workout, got {mult3:.4f}")
        sys.exit(1)
    print(f"  [OK] Case 3 Passed. Event: {event3.type}, Multiplier: {mult3:.4f}")

    print("\n  [PASS] Schedule Logic Audit: SUCCESS\n")

if __name__ == "__main__":
    try:
        asyncio.run(run_audit())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n  [FATAL] Audit crash: {e}")
        sys.exit(1)
