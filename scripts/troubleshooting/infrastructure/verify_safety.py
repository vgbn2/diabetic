"""
Bio-Quant — Safety Logic Auditor (Mission Control)
==================================================
Verifies that the Coordinator correctly identifies Hyper/Hypo emergencies.
Refactored for "Fail Fast" — crashes if safety thresholds are NOT reached.
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Load project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from diabetic.registry import GlucoseReading
from diabetic.coordinator import Coordinator
from diabetic.config import config

async def run_safety_audit():
    coordinator = Coordinator()
    start_time = datetime.now(timezone.utc)
    captured_alerts = []

    # Patch dispatch to capture outcomes
    async def mock_dispatch(alert):
        print(f"  [DISPATCH] {alert.type} | {alert.severity} | {alert.message}")
        captured_alerts.append(alert)

    coordinator._dispatch_alert = mock_dispatch

    print("\n  Bio-Quant - SAFETY THRESHOLD AUDIT")
    print("  " + "=" * 60)

    # ── Test 1: Hypoglycemic Crash ────────────────────────────
    print("\n  TEST 1: Hypoglycemic Crash (Expected: HYPO/CRASH Alert)")
    print("  " + "-" * 50)
    
    captured_alerts.clear()
    crash_values = [6.5, 5.0, 4.0, 3.2, 2.8, 2.4] # Rapid descent
    
    for i, val in enumerate(crash_values):
        r = GlucoseReading(
            timestamp=start_time + timedelta(minutes=i*5), 
            value=val, 
            trend="DoubleDown",
            source="Audit"
        )
        await coordinator._process_reading(r)

    if not captured_alerts:
        print("  [X] FAILED: No emergency alerts triggered during crash scenario.")
        sys.exit(1)
    
    print(f"  [OK] Success: {len(captured_alerts)} alert(s) triggered during hypo crash.")

    # ── Test 2: Faint Risk (Hyper + Rise) ─────────────────────
    print("\n  TEST 2: Faint Risk (Expected: HYPER/FAINT Alert)")
    print("  " + "-" * 50)
    
    captured_alerts.clear()
    # Reset coordinator state for clean hyper test
    coordinator.snapshots.clear()
    
    faint_values = [15.0, 16.5, 18.0, 19.5, 21.0] # Rapid ascent while high
    for i, val in enumerate(faint_values):
        r = GlucoseReading(
            timestamp=start_time + timedelta(hours=1, minutes=i*5), 
            value=val, 
            trend="DoubleUp",
            source="Audit"
        )
        await coordinator._process_reading(r)

    if not any(a.severity in ["WARNING", "CRITICAL"] for a in captured_alerts):
        print("  [X] FAILED: No high-severity alerts triggered for faint risk.")
        sys.exit(1)

    print(f"  [OK] Success: Severe alerts triggered correctly.")
    print("\n  [PHASE 0.6.2] Safety Audit: SUCCESS\n")

if __name__ == "__main__":
    try:
        asyncio.run(run_safety_audit())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n  [FATAL] Audit Crash: {e}")
        sys.exit(1)
