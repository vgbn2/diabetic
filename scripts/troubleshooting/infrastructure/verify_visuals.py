"""
Bio-Quant -- Visualizer Auditor (Mission Control)
==================================================
Verifies system persistence and chart generation.
Fail-Fast: Crashes with sys.exit(1) if image is not generated.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

# -- Path Resolution --
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from diabetic.utils.audit_logger import AuditLogger
from diabetic.registry import GlucoseReading, MetabolicSnapshot, CardiacReading
from diabetic.ui.visualizer import MetabolicVisualizer

async def run_audit():
    print("\n  Bio-Quant -- VISUALIZER AUDIT")
    print("  " + "=" * 50)

    # -- Probe 1: Local Persistence --
    print("\n  [1] Verifying Local Audit DB Logging...")
    audit = AuditLogger()
    test_val = 10.5
    reading = GlucoseReading(
        timestamp=datetime.now(timezone.utc),
        value=test_val,
        trend="Flat"
    )
    try:
        await audit.log_reading(reading)
        last_ts = await audit.get_last_reading_timestamp()
        if not last_ts:
            print("  [X] FAILED: Could not retrieve last reading timestamp from audit.db")
            sys.exit(1)
        print(f"  [OK] Persistence confirmed. Last reading at: {last_ts}")
    except Exception as e:
        print(f"  [X] FAILED: Persistence error: {e}")
        sys.exit(1)

    # -- Probe 2: Visualization Engine --
    print("\n  [2] Verifying Chart Generation...")
    viz = MetabolicVisualizer(output_dir="test_charts")
    
    # Cleanup previous run
    IMG_PATH = "test_charts/live_dashboard.png"
    if os.path.exists(IMG_PATH):
        os.remove(IMG_PATH)

    cardiac = CardiacReading(timestamp=datetime.now(timezone.utc), bpm=72, hrv=50.0)
    snapshot = MetabolicSnapshot(glucose=reading, cardiac=cardiac)
    snapshot.velocity = 0.5
    
    try:
        # Simulate continuous update pipeline
        viz.update_continuous([snapshot])
    except Exception as e:
        print(f"  [X] FAILED: Visualizer crashed during rendering: {e}")
        sys.exit(1)

    if os.path.exists(IMG_PATH):
        print(f"  [OK] Chart generated successfully: {IMG_PATH}")
    else:
        print("  [X] FAILED: live_dashboard.png NOT found after render pass.")
        sys.exit(1)

    print("\n  [PASS] Visualizer Audit: SUCCESS\n")

if __name__ == "__main__":
    try:
        asyncio.run(run_audit())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n  [FATAL] Audit crash: {e}")
        sys.exit(1)
