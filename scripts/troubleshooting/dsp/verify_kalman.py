"""
Bio-Quant — Kalman Filter & DSP Auditor (Mission Control)
=========================================================
Verifies signal smoothing, spike suppression, and metabolic velocity accuracy.
Refactored for "Fail Fast" — crashes if signal integrity is compromised.
"""

import sys
import os
from datetime import datetime, timedelta, timezone
import numpy as np

# Load project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from diabetic.dsp.kalman import GlucoseFilter
from diabetic.registry import GlucoseReading

def run_dsp_audit():
    print("\n  Bio-Quant - KALMAN FILTER / DSP AUDIT")
    print("  " + "=" * 60)
    
    kf = GlucoseFilter()
    start_time = datetime.now(timezone.utc)
    
    true_glucose = 15.0 # Start higher
    velocity = -0.01    # Drifts slower
    snapshots = []
    
    print("  [Step 1] Simulating 100-Reading Metabolic Stream...")
    for i in range(101):
        # 1. Simulate timing jitter and gaps
        dt = 5.0 + np.random.uniform(-0.5, 0.5)
        current_time = start_time + timedelta(minutes=i * 5.0) 
        
        # 2. Add sensor noise
        measurement = true_glucose + np.random.normal(0, 0.15)
        
        # 3. Massive Spike Entry (Outlier)
        if i == 50:
            measurement += 8.0 
            print(f"  [!] Injected 8.0 mmol/L artifact at index 50")

        reading = GlucoseReading(
            timestamp=current_time,
            value=measurement,
            trend="Flat",
            source="Audit"
        )
        
        snap = kf.update(reading)
        snapshots.append(snap)
        
        # Biological boundary check (Internal Audit)
        if snap.filtered_value < 1.0 or snap.filtered_value > 35.0:
            print(f"  [X] BIOLOGICAL VIOLATION: Filtered value {snap.filtered_value:.1f} is impossible.")
            sys.exit(1)

        # Velocity check (Physiological limit: ~0.8 mmol/L/min)
        if abs(snap.velocity) > 0.8:
            print(f"  [X] SIGNAL ARTIFACT: Velocity {snap.velocity:.3f} exceeds physiological limits.")
            sys.exit(1)

        # Incremental Trend
        true_glucose += velocity * 5.0 
        true_glucose = max(3.0, true_glucose) # Stay within bio boundaries
        if i == 80: velocity = -0.4 # Start crash

    print("\n  [Step 2] Processing Analysis")
    print("  " + "-" * 50)
    
    # 1. Spike Suppression Check
    spike_idx = 50
    delta = abs(snapshots[spike_idx].filtered_value - snapshots[spike_idx-1].filtered_value)
    print(f"  Spike Suppression: Raw +8.0 | Filtered Delta: {delta:.2f}")
    if delta > 3.5:
        print("  [X] FAILED: Kalman gain is too high. Spike suppression failed.")
        sys.exit(1)

    # 2. Trend Responsiveness Check
    crash_vels = [s.velocity for s in snapshots[85:95]]
    max_neg_vel = min(crash_vels)
    print(f"  Crash Sensitivity: Target -0.4 | Max Detected: {max_neg_vel:.3f}")
    if max_neg_vel > -0.2:
        print("  [X] FAILED: Filter is too sluggish, missing rapid trends.")
        sys.exit(1)

    print("\n  [OK] SUCCESS: DSP / Kalman Integrity Verified.")
    print("\n  [PHASE 0.6.3] DSP Audit: COMPLETE\n")

if __name__ == "__main__":
    try:
        run_dsp_audit()
    except Exception as e:
        print(f"\n  [FATAL] {e}")
        sys.exit(1)
