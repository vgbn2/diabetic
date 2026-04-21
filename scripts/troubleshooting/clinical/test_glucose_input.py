"""
Bio-Quant — Standalone Glucose Audit (Mission Control)
======================================================
Tests the Nightscout connection independently from the engine.
Refactored for Async/Httpx parity and Model Consistency.

Usage:
    python test_glucose_input.py                  # live mode (requires .env)
    python test_glucose_input.py --mock           # mock mode (no Nightscout needed)
    python test_glucose_input.py --mock --watch   # stream continuously
"""

import sys
import os
import time
import random
import argparse
import asyncio
import httpx
from datetime import datetime, timedelta, timezone
from typing import List, Optional

# Load project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from diabetic.registry import GlucoseReading
from diabetic.config import config

# ── Mock data generator ───────────────────────────────────────
class MockGlucoseSource:
    """Generates realistic synthetic glucose readings."""
    SCENARIOS = {
        "stable":  {"start": 105, "drift": 0.0,  "noise": 2.0},
        "rising":  {"start": 120, "drift": 2.5,  "noise": 3.0},
        "falling": {"start": 95,  "drift": -2.0, "noise": 2.0},
        "crash":   {"start": 85,  "drift": -3.5, "noise": 1.5},
        "spike":   {"start": 150, "drift": 3.0,  "noise": 4.0},
    }

    def __init__(self, scenario: str = "stable"):
        cfg = self.SCENARIOS.get(scenario, self.SCENARIOS["stable"])
        self.glucose  = cfg["start"]
        self.drift    = cfg["drift"]
        self.noise    = cfg["noise"]

    def _direction(self, delta: float) -> str:
        if   delta < -2.0: return "DoubleDown"
        elif delta < -1.0: return "SingleDown"
        elif delta < -0.3: return "FortyFiveDown"
        elif delta <  0.3: return "Flat"
        elif delta <  1.0: return "FortyFiveUp"
        elif delta <  2.0: return "SingleUp"
        else:              return "DoubleUp"

    async def fetch(self, count: int = 5) -> List[GlucoseReading]:
        readings = []
        for i in range(count):
            delta        = self.drift + random.gauss(0, self.noise)
            self.glucose = max(30, min(450, self.glucose + delta))
            ts = datetime.now(timezone.utc) - timedelta(minutes=(count - i) * 5)
            val_mmol = round(self.glucose / 18.018, 1)
            readings.append(GlucoseReading(
                timestamp=ts, value=val_mmol, trend=self._direction(delta), source="Mock"
            ))
        return readings

# ── Nightscout client (Async/Strict) ──────────────────────────
class NightscoutGlucoseSource:
    """Pulls real CGM readings via httpx. LOUD FAILURE on error."""
    def __init__(self):
        self.url = config.NIGHTSCOUT_URL.rstrip("/")
        self.secret = config.NIGHTSCOUT_API_SECRET
        if not self.url or "REPLACE_ME" in self.url:
            raise ValueError("NIGHTSCOUT_URL not set in .env")

    async def fetch(self, count: int = 5) -> List[GlucoseReading]:
        headers = {"Accept": "application/json"}
        if self.secret: headers["api-secret"] = self.secret
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.url}/api/v1/entries.json", headers=headers, params={"count": count})
            resp.raise_for_status()
            data = resp.json()
            readings = []
            for entry in data:
                if "sgv" not in entry: continue
                val_mmol = round(float(entry["sgv"]) / 18.018, 1)
                ts = datetime.fromtimestamp(entry.get("date", 0) / 1000.0, tz=timezone.utc)
                readings.append(GlucoseReading(
                    timestamp=ts, value=val_mmol, trend=entry.get("direction", "Flat"), source="Nightscout"
                ))
            return readings

# ── Validation ────────────────────────────────────────────────
def validate_readings(readings: List[GlucoseReading]) -> dict:
    if not readings: return {"ok": False, "reason": "No readings"}
    issues = []
    for r in readings:
        if r.value < 2.0 or r.value > 33.3:
            issues.append(f"Physio Violation: {r.value} mmol/L")
    return {"ok": len(issues) == 0, "count": len(readings), "issues": issues}

# ── Display ───────────────────────────────────────────────────
def print_readings(readings: List[GlucoseReading]):
    print(f"\n  {'Timestamp':<20} | {'Value':<10} | {'Trend':<12} | {'Source'}")
    print("  " + "-" * 65)
    for r in readings:
        color = ""
        if r.value < 3.9: color = "!! [LOW] "
        elif r.value > 10.0: color = "!  [HIGH]"
        print(f"  {r.timestamp.strftime('%H:%M:%S'):<20} | {r.value:>5.1f} mmol/L | {r.trend:<12} | {r.source} {color}")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--scenario", default="stable")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()

    print("\n  Bio-Quant - MISSION CONTROL AUDIT")
    print("  " + "=" * 60)
    source = MockGlucoseSource(args.scenario) if args.mock else NightscoutGlucoseSource()

    try:
        while True:
            readings = await source.fetch(args.count)
            print_readings(readings)
            report = validate_readings(readings)
            if not report["ok"]:
                print(f"\n  [!] FAILED: {report['issues']}")
            else:
                print(f"\n  [OK] Passed ({report['count']} readings)")
            if not args.watch: break
            await asyncio.sleep(10)
    except Exception as e:
        print(f"\n  [FATAL] {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
