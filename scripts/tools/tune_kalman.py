import sys
sys.path.append(r"c:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor")

from diabetic.dsp.kalman import GlucoseFilter
from diabetic.registry import GlucoseReading
from datetime import datetime, timedelta
import numpy as np

def run_test(q_var, R):
    # Mocking
    filter = GlucoseFilter()
    filter.q_var = q_var
    filter.kf.R = np.array([[R]])
    
    start_time = datetime.now()
    true_glucose = 10.0
    velocity = -0.02
    snapshots = []
    
    for i in range(101):
        if i == 50:
            dt = 5.0
        elif i == 70:
            dt = 25.0
        else:
            dt = 5.0 # Fixed for consistency in tuning
            
        current_time = start_time + timedelta(minutes=i * 5.0) 
        if i >= 70:
            current_time = start_time + timedelta(minutes=70 * 5.0 + (i-70) * 5.0 + 20.0)

        if i == 81:
            true_glucose = 15.0
        
        if i > 80:
            velocity = -0.5
        
        true_glucose += velocity * dt
        true_glucose = max(true_glucose, 2.2)
        
        measurement = true_glucose + np.random.normal(0, 0.05)
        
        if i == 50:
            measurement += 8.0

        reading = GlucoseReading(timestamp=current_time, value=measurement, trend="Flat")
        snapshot = filter.update(reading)
        snapshots.append(snapshot)
        
    spike_filt = snapshots[50].filtered_value
    prev_filt = snapshots[49].filtered_value
    delta = abs(spike_filt - prev_filt)
    
    crash_vels = [s.velocity for s in snapshots[81:90]]
    crash_min = min(crash_vels)
    
    return delta, crash_min

best_params = None
best_score = float('inf')

for q in [1e-3, 1e-4, 5e-5, 1e-5, 5e-6, 1e-6]:
    for r in [0.25, 0.5, 1.0, 2.0, 4.0]:
        delta, crash = run_test(q, r)
        print(f"q={q:.1e}, r={r:.2f} => Spike={delta:.2f}, Crash={crash:.3f}")
        
        if delta < 3.0 and crash < -0.3:
            print("  *** FOUND CANDIDATE ***")
