"""
Bio-Quant — Standalone Glucose Input Tester
============================================
Tests the Nightscout connection independently from the engine.
Run this file alone to verify glucose data is flowing correctly.

Usage:
    python test_glucose_input.py                  # live mode (requires .env)
    python test_glucose_input.py --mock           # mock mode (no Nightscout needed)
    python test_glucose_input.py --mock --watch   # mock mode, stream continuously
"""

import sys
import time
import random
import argparse
from datetime import datetime, timedelta
from typing import List, Optional
from dataclasses import dataclass

# ── Data shape ────────────────────────────────────────────────
@dataclass
class GlucoseReading:
    timestamp: datetime
    sgv: float          # sensor glucose value (mg/dL)
    direction: str      # trend direction
    source: str         # where it came from

    def is_low(self) -> bool:
        return self.sgv < 70

    def is_high(self) -> bool:
        return self.sgv > 180

    def is_critical_low(self) -> bool:
        return self.sgv < 54

    def is_critical_high(self) -> bool:
        return self.sgv > 300

    def trend_emoji(self) -> str:
        arrows = {
            "DoubleDown":    "⬇⬇",
            "SingleDown":    "⬇",
            "FortyFiveDown": "↘",
            "Flat":          "→",
            "FortyFiveUp":   "↗",
            "SingleUp":      "⬆",
            "DoubleUp":      "⬆⬆",
            "NONE":          "?",
        }
        return arrows.get(self.direction, "?")

    def status_label(self) -> str:
        if self.is_critical_low():  return "CRITICAL LOW"
        if self.is_low():           return "LOW"
        if self.is_critical_high(): return "CRITICAL HIGH"
        if self.is_high():          return "HIGH"
        return "IN RANGE"

    def __str__(self) -> str:
        status = self.status_label()
        trend  = self.trend_emoji()
        time   = self.timestamp.strftime("%H:%M:%S")
        return (
            f"[{time}] "
            f"{self.sgv:.1f} mg/dL {trend}  "
            f"| {status:<14} "
            f"| Source: {self.source}"
        )


# ── Mock data generator ───────────────────────────────────────
class MockGlucoseSource:
    """
    Generates realistic synthetic glucose readings.
    Simulates a slow rise after a meal, then a gradual correction.
    No Nightscout needed — purely for testing the pipeline shape.
    """

    SCENARIOS = {
        "stable":  {"start": 105, "drift": 0.0,  "noise": 2.0},
        "rising":  {"start": 120, "drift": 2.5,  "noise": 3.0},
        "falling": {"start": 95,  "drift": -2.0, "noise": 2.0},
        "crash":   {"start": 85,  "drift": -3.5, "noise": 1.5},
        "spike":   {"start": 150, "drift": 3.0,  "noise": 4.0},
    }

    DIRECTIONS = ["DoubleDown", "SingleDown", "FortyFiveDown",
                  "Flat", "FortyFiveUp", "SingleUp", "DoubleUp"]

    def __init__(self, scenario: str = "stable"):
        cfg = self.SCENARIOS.get(scenario, self.SCENARIOS["stable"])
        self.glucose  = cfg["start"]
        self.drift    = cfg["drift"]
        self.noise    = cfg["noise"]
        self.tick     = 0

    def _direction(self, delta: float) -> str:
        if   delta < -2.0: return "DoubleDown"
        elif delta < -1.0: return "SingleDown"
        elif delta < -0.3: return "FortyFiveDown"
        elif delta <  0.3: return "Flat"
        elif delta <  1.0: return "FortyFiveUp"
        elif delta <  2.0: return "SingleUp"
        else:              return "DoubleUp"

    def fetch(self, count: int = 5) -> List[GlucoseReading]:
        readings = []
        for i in range(count):
            delta        = self.drift + random.gauss(0, self.noise)
            self.glucose = max(30, min(450, self.glucose + delta))
            self.tick   += 1

            ts = datetime.now() - timedelta(minutes=(count - i) * 5)
            readings.append(GlucoseReading(
                timestamp=ts,
                sgv=round(self.glucose, 1),
                direction=self._direction(delta),
                source="Mock"
            ))
        return readings


# ── Nightscout client ─────────────────────────────────────────
class NightscoutGlucoseSource:
    """
    Pulls real CGM readings from a Nightscout instance.
    Requires NIGHTSCOUT_URL and NIGHTSCOUT_API_SECRET in .env
    """

    def __init__(self):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        import os
        self.url    = os.getenv("NIGHTSCOUT_URL", "").rstrip("/")
        self.secret = os.getenv("NIGHTSCOUT_API_SECRET", "")

        if not self.url:
            raise ValueError(
                "NIGHTSCOUT_URL not set in .env\n"
                "Add: NIGHTSCOUT_URL=https://yourname.up.railway.app"
            )

    def fetch(self, count: int = 5) -> List[GlucoseReading]:
        import requests, datetime as dt

        headers = {"Accept": "application/json"}
        if self.secret:
            headers["API-SECRET"] = self.secret

        try:
            resp = requests.get(
                f"{self.url}/api/v1/entries.json",
                headers=headers,
                params={"count": count},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()

            readings = []
            for entry in data:
                if "sgv" not in entry:
                    continue
                ts = dt.datetime.fromtimestamp(entry.get("date", 0) / 1000.0)
                readings.append(GlucoseReading(
                    timestamp=ts,
                    sgv=float(entry["sgv"]),
                    direction=entry.get("direction", "NONE"),
                    source="Nightscout"
                ))
            return readings

        except requests.exceptions.ConnectionError:
            print(f"  ERROR: Cannot reach {self.url}")
            print("  Check NIGHTSCOUT_URL in .env and that Nightscout is running.")
            return []
        except requests.exceptions.HTTPError as e:
            print(f"  ERROR: Nightscout returned {e.response.status_code}")
            print("  Check NIGHTSCOUT_API_SECRET in .env")
            return []
        except Exception as e:
            print(f"  ERROR: {e}")
            return []


# ── Validation ────────────────────────────────────────────────
def validate_readings(readings: List[GlucoseReading]) -> dict:
    """
    Checks the data quality of a batch of readings.
    Returns a report you can inspect before trusting the engine.
    """
    if not readings:
        return {"ok": False, "reason": "No readings returned"}

    issues = []

    # Check for physiologically impossible values
    for r in readings:
        if r.sgv < 20 or r.sgv > 600:
            issues.append(f"Impossible SGV: {r.sgv} at {r.timestamp}")

    # Check for time ordering
    times = [r.timestamp for r in readings]
    if times != sorted(times):
        issues.append("Readings are not in chronological order")

    # Check for duplicate timestamps
    if len(times) != len(set(times)):
        issues.append("Duplicate timestamps detected")

    # Check for large gaps (> 20 minutes between readings)
    for i in range(1, len(readings)):
        gap = (readings[i].timestamp - readings[i-1].timestamp).total_seconds() / 60
        if gap > 20:
            issues.append(f"Large gap: {gap:.0f} min between readings")

    # Check velocity (rate of change)
    for i in range(1, len(readings)):
        dt_min = max(
            (readings[i].timestamp - readings[i-1].timestamp).total_seconds() / 60,
            0.1
        )
        velocity = (readings[i].sgv - readings[i-1].sgv) / dt_min
        if abs(velocity) > 4.0:
            issues.append(
                f"Physiologically impossible velocity: "
                f"{velocity:.1f} mg/dL/min at {readings[i].timestamp}"
            )

    return {
        "ok":       len(issues) == 0,
        "count":    len(readings),
        "min_sgv":  min(r.sgv for r in readings),
        "max_sgv":  max(r.sgv for r in readings),
        "issues":   issues
    }


# ── Display ───────────────────────────────────────────────────
def print_readings(readings: List[GlucoseReading]):
    print()
    print("  SGV Readings")
    print("  " + "─" * 60)
    for r in readings:
        # Color-code by status
        prefix = ""
        if r.is_critical_low() or r.is_critical_high():
            prefix = "  !! "
        elif r.is_low() or r.is_high():
            prefix = "  !  "
        else:
            prefix = "     "
        print(f"{prefix}{r}")
    print()


def print_validation(report: dict):
    print("  Validation Report")
    print("  " + "─" * 60)
    print(f"  Readings:  {report['count']}")
    if report.get("min_sgv"):
        print(f"  Range:     {report['min_sgv']:.1f} – {report['max_sgv']:.1f} mg/dL")
    if report["ok"]:
        print("  Status:    OK — data looks clean")
    else:
        print(f"  Status:    {len(report['issues'])} issue(s) found")
        for issue in report["issues"]:
            print(f"             - {issue}")
    print()


# ── Entry point ───────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Bio-Quant Glucose Input Tester")
    parser.add_argument("--mock",     action="store_true", help="Use mock data instead of Nightscout")
    parser.add_argument("--scenario", default="stable",    help="Mock scenario: stable/rising/falling/crash/spike")
    parser.add_argument("--watch",    action="store_true", help="Poll continuously every 30 seconds")
    parser.add_argument("--count",    type=int, default=5, help="Number of readings to fetch")
    args = parser.parse_args()

    print()
    print("  Bio-Quant — Glucose Input Tester")
    print("  " + "═" * 60)

    # Choose source
    if args.mock:
        print(f"  Mode:      Mock ({args.scenario} scenario)")
        source = MockGlucoseSource(scenario=args.scenario)
        fetch  = source.fetch
    else:
        print("  Mode:      Live (Nightscout)")
        try:
            ns    = NightscoutGlucoseSource()
            fetch = ns.fetch
            print(f"  URL:       {ns.url}")
        except ValueError as e:
            print(f"\n  ERROR: {e}\n")
            print("  Run with --mock to test without Nightscout:")
            print("  python test_glucose_input.py --mock\n")
            sys.exit(1)

    print()

    # Single fetch or continuous watch
    if args.watch:
        print("  Watching... Press Ctrl+C to stop")
        print()
        try:
            while True:
                readings = fetch(args.count)
                print_readings(readings)
                report = validate_readings(readings)
                print_validation(report)
                print(f"  Next update in 30 seconds...")
                time.sleep(30)
        except KeyboardInterrupt:
            print("\n  Stopped.\n")
    else:
        readings = fetch(args.count)
        print_readings(readings)
        report = validate_readings(readings)
        print_validation(report)

        print("  To watch continuously:")
        print("  python test_glucose_input.py --mock --watch")
        print()


if __name__ == "__main__":
    main()
