"""
Bio-Quant — Standalone Heart Rate Input Tester
===============================================
Tests BLE heart rate sensor connection independently from the engine.
Calculates RMSSD (HRV) from RR intervals in real time.

Usage:
    python test_hr_input.py --scan            # find nearby BLE sensors
    python test_hr_input.py --mock            # mock mode, no sensor needed
    python test_hr_input.py --mock --watch    # stream mock HRV continuously
    python test_hr_input.py --address XX:XX:XX:XX:XX:XX  # connect to sensor

Requirements:
    pip install bleak
"""

import sys
import time
import math
import random
import asyncio
import argparse
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, field


# ── Data shape ────────────────────────────────────────────────
@dataclass
class HRReading:
    timestamp: datetime
    hr: float           # heart rate in bpm
    rmssd: float        # HRV — root mean square of successive differences (ms)
    rr_intervals: List[float] = field(default_factory=list)
    source: str = "Unknown"

    def dsi(self, baseline_rmssd: float = 55.0) -> float:
        """Dynamic Stress Index — same formula as Bio-Quant engine."""
        safe_rmssd = max(self.rmssd, 5.0)
        return max(0.5, min(baseline_rmssd / safe_rmssd, 3.0))

    def stress_label(self, baseline: float = 55.0) -> str:
        d = self.dsi(baseline)
        if   d < 1.2: return "Relaxed"
        elif d < 1.8: return "Nominal"
        elif d < 2.2: return "Elevated"
        else:         return "Critical stress"

    def __str__(self) -> str:
        t = self.timestamp.strftime("%H:%M:%S")
        return (
            f"[{t}] "
            f"HR: {self.hr:.0f} bpm  "
            f"| RMSSD: {self.rmssd:.1f} ms  "
            f"| DSI: {self.dsi():.2f}  "
            f"| {self.stress_label():<16}"
            f"| Source: {self.source}"
        )


# ── RMSSD calculator ──────────────────────────────────────────
def calculate_rmssd(rr_intervals: List[float]) -> float:
    """
    RMSSD = sqrt( mean( (RR[i+1] - RR[i])^2 ) )
    Standard HRV metric. Higher = more relaxed / better recovery.
    """
    if len(rr_intervals) < 2:
        return 0.0
    diffs = [abs(rr_intervals[i+1] - rr_intervals[i])
             for i in range(len(rr_intervals) - 1)]
    return math.sqrt(sum(d**2 for d in diffs) / len(diffs))


# ── BLE packet parser ─────────────────────────────────────────
def parse_hr_measurement(data: bytearray):
    """
    Parses Bluetooth HRM characteristic (UUID 0x2A37).
    Returns (hr_bpm, rr_intervals_ms)
    """
    flags = data[0]
    hr_format_16bit = flags & 0x01

    if hr_format_16bit:
        hr = int.from_bytes(data[1:3], "little")
        offset = 3
    else:
        hr = data[1]
        offset = 2

    # Skip energy expended if present
    if flags & 0x08:
        offset += 2

    # Parse RR intervals (each is 2 bytes, unit = 1/1024 seconds)
    rr_intervals = []
    while offset + 1 < len(data):
        raw = int.from_bytes(data[offset:offset+2], "little")
        rr_ms = raw / 1024.0 * 1000.0
        rr_intervals.append(rr_ms)
        offset += 2

    return hr, rr_intervals


# ── Mock HR source ────────────────────────────────────────────
class MockHRSource:
    """
    Generates realistic HR and HRV data without a physical sensor.
    Simulates resting, stressed, and recovery states.
    """

    SCENARIOS = {
        "resting":  {"hr_base": 65,  "rmssd_base": 55.0, "noise": 3.0},
        "stressed": {"hr_base": 88,  "rmssd_base": 18.0, "noise": 2.0},
        "exercise": {"hr_base": 140, "rmssd_base": 8.0,  "noise": 5.0},
        "recovery": {"hr_base": 72,  "rmssd_base": 35.0, "noise": 4.0},
    }

    def __init__(self, scenario: str = "resting"):
        cfg = self.SCENARIOS.get(scenario, self.SCENARIOS["resting"])
        self.hr_base    = cfg["hr_base"]
        self.rmssd_base = cfg["rmssd_base"]
        self.noise      = cfg["noise"]

    def read(self) -> HRReading:
        hr    = self.hr_base + random.gauss(0, self.noise)
        rmssd = max(5.0, self.rmssd_base + random.gauss(0, self.noise * 0.5))

        # Simulate RR intervals consistent with this RMSSD
        base_rr = 60000.0 / hr
        rr = [base_rr + random.gauss(0, rmssd * 0.1) for _ in range(10)]

        return HRReading(
            timestamp=datetime.now(),
            hr=round(hr, 1),
            rmssd=round(rmssd, 1),
            rr_intervals=rr,
            source="Mock"
        )


# ── BLE scanner ───────────────────────────────────────────────
async def scan_ble_devices(duration: int = 5):
    """Scans for nearby BLE devices and prints their addresses and names."""
    try:
        from bleak import BleakScanner
    except ImportError:
        print("\n  ERROR: bleak not installed.")
        print("  Run: pip install bleak\n")
        return

    print(f"\n  Scanning for BLE devices ({duration}s)...")
    print("  Make sure your heart rate sensor is turned on and nearby.")
    print()

    devices = await BleakScanner.discover(timeout=duration)

    if not devices:
        print("  No devices found. Check that sensor is powered on.")
        return

    hr_candidates = []
    others        = []

    for d in devices:
        name = d.name or "Unknown"
        if any(kw in name.lower() for kw in ["polar", "heart", "hr", "wahoo", "garmin", "fitbit"]):
            hr_candidates.append(d)
        else:
            others.append(d)

    if hr_candidates:
        print("  Likely heart rate sensors:")
        print("  " + "─" * 50)
        for d in hr_candidates:
            print(f"  Address: {d.address}  |  Name: {d.name}")
        print()

    print("  All discovered devices:")
    print("  " + "─" * 50)
    for d in sorted(devices, key=lambda x: x.name or ""):
        print(f"  {d.address}  |  {d.name or 'Unknown'}")
    print()

    if hr_candidates:
        print("  To connect, run:")
        print(f"  python test_hr_input.py --address {hr_candidates[0].address}")
    print()


# ── BLE live reader ───────────────────────────────────────────
async def read_ble_sensor(address: str, duration: int = 60):
    """Connects to a BLE HR sensor and streams readings."""
    try:
        from bleak import BleakClient, BleakError
    except ImportError:
        print("\n  ERROR: bleak not installed.")
        print("  Run: pip install bleak\n")
        return

    HR_UUID  = "00002a37-0000-1000-8000-00805f9b34fb"
    rr_buffer: List[float] = []
    baseline  = 55.0

    print(f"\n  Connecting to {address}...")

    def callback(sender, data):
        nonlocal baseline
        hr, rr = parse_hr_measurement(bytearray(data))
        rr_buffer.extend(rr)

        if len(rr_buffer) > 20:
            del rr_buffer[:-20]

        rmssd = calculate_rmssd(rr_buffer) if len(rr_buffer) >= 2 else 0.0

        # Update baseline slowly (rolling average)
        if rmssd > 0:
            baseline = baseline * 0.95 + rmssd * 0.05

        reading = HRReading(
            timestamp=datetime.now(),
            hr=float(hr),
            rmssd=rmssd,
            rr_intervals=list(rr_buffer),
            source=f"BLE ({address[:8]}...)"
        )
        print(f"  {reading}")

    try:
        async with BleakClient(address) as client:
            print(f"  Connected.\n")
            print("  HR (bpm) | RMSSD (ms) | DSI | Stress")
            print("  " + "─" * 60)

            await client.start_notify(HR_UUID, callback)
            await asyncio.sleep(duration)
            await client.stop_notify(HR_UUID)

    except BleakError as e:
        print(f"\n  Connection failed: {e}")
        print("  Check the address is correct and sensor is powered on.")


# ── Validation ────────────────────────────────────────────────
def validate_reading(r: HRReading) -> dict:
    issues = []

    if r.hr < 30 or r.hr > 220:
        issues.append(f"Impossible HR: {r.hr} bpm")

    if r.rmssd < 0:
        issues.append(f"Negative RMSSD: {r.rmssd}")

    if r.rmssd > 200:
        issues.append(f"Unusually high RMSSD: {r.rmssd} ms — check sensor placement")

    if r.rr_intervals:
        for rr in r.rr_intervals:
            if rr < 300 or rr > 2000:
                issues.append(f"Impossible RR interval: {rr:.0f} ms")
                break

    return {"ok": len(issues) == 0, "issues": issues}


# ── Entry point ───────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Bio-Quant HR Input Tester")
    parser.add_argument("--scan",     action="store_true",          help="Scan for nearby BLE devices")
    parser.add_argument("--address",  type=str, default=None,       help="BLE device MAC address to connect")
    parser.add_argument("--mock",     action="store_true",          help="Use mock data instead of sensor")
    parser.add_argument("--scenario", default="resting",            help="Mock scenario: resting/stressed/exercise/recovery")
    parser.add_argument("--watch",    action="store_true",          help="Stream continuously")
    parser.add_argument("--duration", type=int, default=60,         help="BLE read duration in seconds")
    parser.add_argument("--baseline", type=float, default=55.0,     help="Personal HRV baseline in ms")
    args = parser.parse_args()

    print()
    print("  Bio-Quant — Heart Rate Input Tester")
    print("  " + "═" * 60)

    if args.scan:
        asyncio.run(scan_ble_devices())
        return

    if args.address:
        print(f"  Mode:     Live BLE sensor")
        print(f"  Address:  {args.address}")
        print(f"  Duration: {args.duration}s")
        print(f"  Baseline: {args.baseline} ms RMSSD")
        print()
        asyncio.run(read_ble_sensor(args.address, args.duration))
        return

    if args.mock:
        print(f"  Mode:     Mock ({args.scenario} scenario)")
        print(f"  Baseline: {args.baseline} ms RMSSD")
        print()
        source = MockHRSource(scenario=args.scenario)

        if args.watch:
            print("  Streaming... Press Ctrl+C to stop")
            print()
            print("  Timestamp  | HR (bpm) | RMSSD (ms) | DSI  | Stress")
            print("  " + "─" * 65)
            try:
                while True:
                    reading = source.read()
                    report  = validate_reading(reading)

                    prefix = "  !! " if not report["ok"] else "     "
                    print(f"{prefix}{reading}")

                    if not report["ok"]:
                        for issue in report["issues"]:
                            print(f"       WARNING: {issue}")

                    time.sleep(5)
            except KeyboardInterrupt:
                print("\n  Stopped.\n")
        else:
            print("  Single reading:")
            print()
            reading = source.read()
            report  = validate_reading(reading)

            print(f"  {reading}")
            print()
            print(f"  DSI at baseline {args.baseline}ms: {reading.dsi(args.baseline):.2f}")
            print(f"  Stress level: {reading.stress_label(args.baseline)}")
            print()

            if not report["ok"]:
                print("  Validation issues:")
                for issue in report["issues"]:
                    print(f"  - {issue}")
            else:
                print("  Validation: OK")

            print()
            print("  To stream continuously:")
            print(f"  python test_hr_input.py --mock --scenario {args.scenario} --watch")
            print()
        return

    # No arguments — show help
    print()
    print("  No mode selected. Examples:")
    print()
    print("  Scan for BLE sensors:")
    print("  python test_hr_input.py --scan")
    print()
    print("  Connect to a sensor:")
    print("  python test_hr_input.py --address XX:XX:XX:XX:XX:XX")
    print()
    print("  Mock mode (no sensor needed):")
    print("  python test_hr_input.py --mock --scenario resting")
    print("  python test_hr_input.py --mock --scenario stressed --watch")
    print()
    print("  Scenarios: resting | stressed | exercise | recovery")
    print()


if __name__ == "__main__":
    main()
