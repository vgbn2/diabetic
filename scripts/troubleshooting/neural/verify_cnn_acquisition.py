import sys
import os
import torch
import numpy as np
from datetime import datetime, timezone

# Add project root to path
PROJECT_ROOT = r"c:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor"
sys.path.append(PROJECT_ROOT)

from diabetic.ml_engine.inference import MetabolicInferenceRunner
from diabetic.registry import MetabolicSnapshot, GlucoseReading, CardiacReading, EnvironmentReading
from diabetic.utils.scaling_engine import scaling_engine

def test_cnn_acquisition_assembly():
    print("\n--- [Audit 1/2] Neural Assembly Lab (L4/5) ---")
    
    # 1. Initialize Neural Runner
    try:
        runner = MetabolicInferenceRunner(seq_len=30)
    except Exception as e:
        print(f"FAILED: Neural runner initialization: {e}")
        sys.exit(1)

    # 2. Simulate 30-Snapshot Sliding Window
    dummy_snapshots = []
    now = datetime.now(timezone.utc)
    
    print("Simulating 30-snapshot metabolic window...")
    from datetime import timedelta
    for i in range(30):
        ts = now - timedelta(minutes=(30 - i) * 5) # 5-min intervals
        # Increasing glucose trend
        val = 7.0 + (i * 0.1)
        
        snap = MetabolicSnapshot(
            glucose=GlucoseReading(timestamp=ts, value=val, trend="Flat", source="mongodb"),
            cardiac=CardiacReading(timestamp=ts, bpm=70 + (i % 5), hrv=50.0),
            environment=EnvironmentReading(timestamp=ts, temperature=26.5, humidity=80.0, aqi=45.0)
        )
        dummy_snapshots.append(snap)

    # 3. Assemble Static Vector Test
    print("Auditing 15-trait Static Vector assembly...")
    static_v = scaling_engine.assemble_static_vector(now)
    print(f"Static Vector Shape: {static_v.shape}")
    assert static_v.shape == (15,)
    
    # 4. Neural Inference Pass (Gold Run)
    print("\n--- [Audit 2/2] Gold Run Validation ---")
    res = runner.run_inference_on_snapshots(dummy_snapshots)
    
    if res and "glucose" in res:
        print(f"SUCCESS: Neural Inference Result -> Glu: {res['glucose']:.2f} | HR: {res.get('heart_rate', 0.0):.1f}")
        assert res["glucose"] > 0
    else:
        print("FAILED: Inference failed to return valid multi-task results.")
        sys.exit(1)

if __name__ == "__main__":
    test_cnn_acquisition_assembly()
    print("\n[PHASE 19.1.C] CNN Acquisition Protocol: SUCCESS\n")
