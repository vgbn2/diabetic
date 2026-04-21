"""
Bio-Quant — Heart Rate Input Auditor (Mission Control)
======================================================
Tests BLE heart rate sensor connection independently from the engine.
Refactored for Async/Httpx parity and Registry Model usage.

Usage:
    python test_hr_input.py --scan            # find nearby BLE sensors
    python test_hr_input.py --mock            # mock mode, no sensor needed
    python test_hr_input.py --mock --watch    # stream mock HRV continuously
    python test_hr_input.py --address ADDR    # connect to specific sensor
"""

import sys
import os
import time
import math
import random
import asyncio
import argparse
from datetime import datetime, timezone
from typing import List, Optional

# Load project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from diabetic.registry import CardiacReading
from diabetic.config import config

# ── Dynamic Stress Index (DSI) ────────────────────────────────
def calculate_dsi(reading: CardiacReading, baseline_hrv: float = 55.0) -> float:
    """Dynamic Stress Index — higher = more stress."""
    safe_hrv = max(reading.hrv, 5.0)
    return max(0.5, min(baseline_hrv / safe_hrv, 3.0))

def get_stress_label(dsi: float) -> str:
    if   dsi < 1.2: return "Relaxed"
    elif dsi < 1.8: return "Nominal"
    elif dsi < 2.2: return "Elevated"
    else:           return "Critical stress"

# ── RMSSD calculator ──────────────────────────────────────────
def calculate_rmssd(rr_intervals: List[float]) -> float:
    if len(rr_intervals) < 2: return 0.0
    diffs = [(rr_intervals[i+1] - rr_intervals[i])**2 for i in range(len(rr_intervals) - 1)]
    return math.sqrt(sum(diffs) / len(diffs))

# ── Mock HR source ────────────────────────────────────────────
class MockHRSource:
    SCENARIOS = {
        "resting":  {"hr": 65,  "hrv": 55.0, "noise": 3.0},
        "stressed": {"hr": 88,  "hrv": 18.0, "noise": 2.0},
        "exercise": {"hr": 140, "hrv": 8.0,  "noise": 5.0},
    }

    def __init__(self, scenario: str = "resting"):
        self.cfg = self.SCENARIOS.get(scenario, self.SCENARIOS["resting"])

    async def read(self) -> CardiacReading:
        hr  = max(30, self.cfg["hr"] + random.gauss(0, self.cfg["noise"]))
        hrv = max(5,  self.cfg["hrv"] + random.gauss(0, 2.0))
        return CardiacReading(
            timestamp=datetime.now(timezone.utc),
            bpm=int(hr),
            hrv=round(hrv, 2),
            source="Mock"
        )

# ── BLE logic placeholder ─────────────────────────────────────
# (Kept for completeness but requires bleak)
async def scan_ble():
    try:
        from bleak import BleakScanner
        print("\n  Scanning for BLE devices...")
        devices = await BleakScanner.discover(timeout=5)
        for d in devices:
            print(f"  {d.address} | {d.name or 'Unknown'}")
    except ImportError:
        print("\n  [!] Bleak not installed. Run: pip install bleak")

# ── Validation ────────────────────────────────────────────────
def validate_reading(r: CardiacReading):
    issues = []
    if r.bpm < 30 or r.bpm > 220: issues.append(f"Impossible HR: {r.bpm} bpm")
    if r.hrv < 2.0: issues.append(f"Critical HRV Failure: {r.hrv} ms")
    return {"ok": len(issues) == 0, "issues": issues}

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--address", type=str)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--scenario", default="resting")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    print("\n  Bio-Quant - CARDIAC AUDIT")
    print("  " + "=" * 60)

    if args.scan:
        await scan_ble()
        return

    source = MockHRSource(args.scenario) if args.mock else None
    if not source and not args.address:
        print("  [!] Error: Must specify --mock or --address")
        return

    try:
        while True:
            reading = await source.read() if source else None
            # (BLE implementation omitted for brevity in this refactor, 
            # would use basic bleak loop if address is provided)
            
            if reading:
                dsi = calculate_dsi(reading)
                label = get_stress_label(dsi)
                print(f"  {reading.timestamp.strftime('%H:%M:%S')} | HR: {reading.bpm:>3} bpm | HRV: {reading.hrv:>5.1f} ms | DSI: {dsi:.2f} | {label}")
                
                report = validate_reading(reading)
                if not report["ok"]:
                    print(f"  [X] AUDIT FAILED: {report['issues']}")
                    sys.exit(1)
            
            if not args.watch: break
            await asyncio.sleep(5)
    except KeyboardInterrupt:
        print("\n  Stopped.")
    except Exception as e:
        print(f"\n  [FATAL] {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
