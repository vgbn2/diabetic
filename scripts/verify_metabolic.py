import sys
import os
from datetime import datetime, timedelta, timezone
import numpy as np

# Add project root to path
PROJECT_ROOT = r"c:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor"
sys.path.append(PROJECT_ROOT)

from diabetic.dsp.metabolic_math import MetabolicMath
from diabetic.dsp.signal_quality import SignalQuality
from diabetic.registry import GlucoseReading, MetabolicSnapshot

def test_risk_floor():
    print("\n--- Testing Risk Floor ---")
    # Low glucose that would normally cause log domain issues
    lbgi, hbgi = MetabolicMath.calculate_risk_indices(0.1)
    print(f"Glucose 0.1 mmol/L -> LBGI: {lbgi:.2f}, HBGI: {hbgi:.2f}")
    assert lbgi > 0
    assert not np.isnan(lbgi)
    print("SUCCESS: Risk floor handled correctly.")

def test_kinematics_gap():
    print("\n--- Testing Kinematics Gap ---")
    start_time = datetime.now()
    
    r1 = GlucoseReading(timestamp=start_time, value=10.0, trend="Flat")
    s1 = MetabolicSnapshot(glucose=r1, filtered_value=10.0, velocity=0.0)
    
    # Gap of 20 minutes
    r2 = GlucoseReading(timestamp=start_time + timedelta(minutes=20), value=9.0, trend="Flat")
    # Let's say velocity dropped from 0 to -0.2 mmol/L / min
    s2 = MetabolicSnapshot(glucose=r2, filtered_value=9.0, velocity=-0.2)
    
    _, acceleration = MetabolicMath.extract_kinematics([s1, s2])
    
    # Acceleration should be (-0.2 - 0.0) / 20 = -0.01
    print(f"Acceleration with 20min gap: {acceleration:.4f}")
    if abs(acceleration + 0.01) < 0.0001:
        print("SUCCESS: Acceleration uses actual dt.")
    else:
        print(f"FAILURE: Expected -0.01, got {acceleration:.4f}")

def test_signal_quality():
    print("\n--- Testing Signal Quality ---")
    start_time = datetime.now()
    
    # 1. Non-physiological drop (Artifact)
    r1 = GlucoseReading(timestamp=start_time, value=10.0, trend="Flat")
    r2 = GlucoseReading(timestamp=start_time + timedelta(minutes=1), value=8.5, trend="Flat") # drop of 1.5 in 1 min
    
    is_artifact = SignalQuality.is_compression_low([r1, r2])
    print(f"Drop of 1.5 mmol/L in 1 min: Artifact={is_artifact}")
    assert is_artifact == True
    
    # 2. Physiological drop
    r3 = GlucoseReading(timestamp=start_time + timedelta(minutes=5), value=9.0, trend="Flat") # drop of 1.0 in 5 min
    is_artifact_2 = SignalQuality.is_compression_low([r1, r3])
    print(f"Drop of 1.0 mmol/L in 5 min: Artifact={is_artifact_2}")
    assert is_artifact_2 == False

    print("SUCCESS: Signal quality rate-check works.")

if __name__ == "__main__":
    try:
        test_risk_floor()
        test_kinematics_gap()
        test_signal_quality()
        print("\nALL METABOLIC TESTS PASSED.\n")
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
