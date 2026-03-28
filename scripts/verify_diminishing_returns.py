import sys
import os
from datetime import datetime
from typing import List

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic.ml_engine.predictor import GlucoseForecaster
from diabetic import medical_constants

def test_diminishing_returns():
    forecaster = GlucoseForecaster()
    
    print("\n" + "="*60)
    print("  METABOLIC BRAKE VERIFICATION: BOTH-SIDES SYMMETRY  ")
    print("="*60)

    # Base Case: Normal range (no brakes)
    # v = -0.1 mmol/L per min. Over 30 mins, expect -3.0 mmol/L drop.
    snap_normal = MetabolicSnapshot(
        glucose=GlucoseReading(timestamp=datetime.now(), value=8.0, trend="Flat"),
        filtered_value=8.0,
        velocity=-0.1,
        acceleration=0.0,
        atr_14=0.0
    )
    pred_normal = forecaster.predict_30m([snap_normal])
    drop_normal = 8.0 - pred_normal
    print(f"\n[NORMAL: 8.0 mmol/L] Predicted 30m Drop: {drop_normal:.2f} (Target: ~3.0)")

    # High Side: Above Renal Threshold (>10.0)
    # Predicted rise should be damped.
    snap_high = MetabolicSnapshot(
        glucose=GlucoseReading(timestamp=datetime.now(), value=15.0, trend="Flat"),
        filtered_value=15.0,
        velocity=0.1,  # Rising at 0.1/min
        acceleration=0.0,
        atr_14=0.0
    )
    pred_high = forecaster.predict_30m([snap_high])
    rise_high = pred_high - 15.0
    print(f"[HIGH: 15.0 mmol/L] Predicted 30m Rise: {rise_high:.2f} (Target: < 3.0 via Renal Sink)")

    # Low Side: Below Hypo Warning (<3.9)
    # Decline should be damped.
    snap_low = MetabolicSnapshot(
        glucose=GlucoseReading(timestamp=datetime.now(), value=3.5, trend="Flat"),
        filtered_value=3.5,
        velocity=-0.04,  # Falling slower to avoid absolute floor
        acceleration=0.0,
        atr_14=0.0
    )
    pred_low = forecaster.predict_30m([snap_low])
    drop_low = 3.5 - pred_low
    
    un_damped_drop = 0.04 * 30.0
    print(f"[LOW:  3.5 mmol/L] Predicted 30m Drop: {drop_low:.2f} (Un-damped: {un_damped_drop:.2f})")
    
    if drop_low < un_damped_drop - 0.05:
        print("\nSUCCESS: Low-side braking detected.")
    else:
        print(f"\nFAILURE: Damping insufficient (Drop {drop_low:.3f} vs Target < {un_damped_drop-0.05:.3f})")

    print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    test_diminishing_returns()
