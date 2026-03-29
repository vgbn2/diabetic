import sys
import os
from datetime import datetime, timedelta, timezone
import numpy as np

# Add project root to path
# Use absolute path to project root
PROJECT_ROOT = r"c:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor"
sys.path.append(PROJECT_ROOT)

from diabetic.dsp.kalman import GlucoseFilter
from diabetic.registry import GlucoseReading

def run_verification():
    print("\n--- Kalman Filter Verification ---\n")
    
    # Initialize with default config if needed, otherwise just use None
    # GlucoseFilter will try to import from diabetic.config
    filter = GlucoseFilter()
    start_time = datetime.now()
    
    # True glucose track
    true_glucose = 10.0
    velocity = -0.02 # Slow drift down
    
    snapshots = []
    
    for i in range(101):
        # 1. Simulate timing jitter and gaps
        if i == 50:
            dt = 5.0 # Normal interval but spike
        elif i == 70:
            dt = 25.0 # Big gap
        else:
            dt = 5.0 + np.random.uniform(-1.0, 1.0)
            
        current_time = start_time + timedelta(minutes=i * 5.0) 
        if i >= 70:
            # Shift timestamps after the gap
            current_time = start_time + timedelta(minutes=70 * 5.0 + (i-70) * 5.0 + 20.0)

        # 2. Simulate metabolic trend
        if i > 80:
            velocity = -0.5 # Sudden crash
        
        from diabetic import medical_constants
        true_glucose += velocity * 5.0 # True glucose change
        true_glucose = max(true_glucose, medical_constants.PHYSIO_FLOOR) # Apply floor
        
        # 3. Add sensor noise
        measurement = true_glucose + np.random.normal(0, 0.1)
        
        # 4. Inject a massive spike (outlier) at i=50
        if i == 50:
            raw_spike = measurement + 8.0 # +8 mmol/L jump
            measurement = raw_spike
            print(f"Injecting spike at index 50: {measurement:.1f}")

        reading = GlucoseReading(
            timestamp=current_time,
            value=measurement,
            trend="Flat"
        )
        
        snapshot = filter.update(reading)
        snapshots.append((i, dt, reading.value, snapshot.filtered_value, snapshot.velocity))
        
        if i % 10 == 0 or i == 50 or i == 70:
            print(f"[{i:3d}] Raw: {reading.value:5.1f} | Filt: {snapshot.filtered_value:5.1f} | Vel: {snapshot.velocity:6.3f} | dt: {dt:4.1f}")

    print("\n--- Analysis ---")
    
    # Check spike handling
    spike_filt = snapshots[50][3]
    prev_filt = snapshots[49][3]
    delta_filt = abs(spike_filt - prev_filt)
    print(f"Spike response: {prev_filt:.1f} -> {spike_filt:.2f} (Delta: {delta_filt:.2f}, Raw was +8.0)")
    
    # Check crash responsiveness
    crash_vel = snapshots[-1][4]
    print(f"Final velocity during crash: {crash_vel:.3f} (Target: -0.5)")
    
    if delta_filt < 3.0:
        print("SUCCESS: Spike was effectively dampened.")
    else:
        print("WARNING: Spike suppression might be too weak.")
        
    if crash_vel < -0.3:
        print("SUCCESS: Filter is responsive to rapid trends.")
    else:
        print("WARNING: Filter might be lagging too much during trends.")
    
    # Check gap handling
    # The velocity shouldn't jump wildly just because of the gap
    gap_vel = snapshots[70][4]
    print(f"Velocity after gap: {gap_vel:.3f}")

if __name__ == "__main__":
    run_verification()
