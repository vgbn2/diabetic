import sys
import os
from datetime import datetime, timedelta, timezone
import math

# Add project root to path
PROJECT_ROOT = r"c:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor"
sys.path.append(PROJECT_ROOT)

from diabetic.ml_engine.predictor import GlucoseForecaster
from diabetic.registry import MetabolicSnapshot, GlucoseReading, InsulinDose
from diabetic import medical_constants

def test_kinematic_acceleration():
    print("\n--- Testing Kinematic Acceleration term ---")
    forecaster = GlucoseForecaster()
    now = datetime.now()
    
    # Case A: High Velocity, Zero Acceleration
    snap_a = MetabolicSnapshot(
        glucose=GlucoseReading(timestamp=now, value=10.0, unit="mmol/L", trend="Flat"),
        filtered_value=10.0, velocity=0.2, acceleration=0.0, atr_14=0.0
    )
    pred_a, _ = forecaster.predict([snap_a], 30)
    
    # Case B: High Velocity, Negative Acceleration (Braking)
    snap_b = MetabolicSnapshot(
        glucose=GlucoseReading(timestamp=now, value=10.0, unit="mmol/L", trend="Flat"),
        filtered_value=10.0, velocity=0.2, acceleration=-0.01, atr_14=0.0
    )
    pred_b, _ = forecaster.predict([snap_b], 30)
    
    print(f"Velocity 0.2, Accel 0.0 -> Pred 30m: {pred_a}")
    print(f"Velocity 0.2, Accel -0.01 -> Pred 30m: {pred_b}")
    assert pred_b < pred_a
    print("SUCCESS: Acceleration correctly influences prediction.")

def test_signal_dynamics_features():
    print("\n--- Testing Signal Dynamics Feature Vector ---")
    forecaster = GlucoseForecaster()
    now = datetime.now()
    
    # Create a history of 6 readings for EMA residual
    history = []
    for i in range(6):
        ts = now - timedelta(minutes=(6-i)*5)
        # Force a rise: 10.0, 10.1, 10.2, 10.3, 10.4, 10.5
        history.append(MetabolicSnapshot(
            glucose=GlucoseReading(timestamp=ts, value=10.0 + (i*0.1), unit="mmol/L", trend="Flat"),
            filtered_value=10.0 + (i*0.1), velocity=0.1, acceleration=0.0, atr_14=0.1
        ))
    
    features = forecaster._prepare_features(history)
    # [val_mmol, v, a, momentum, lbgi, hbgi, t_sin, t_cos, atr, oscillation]
    print(f"Feature vector size: {features.shape[1]}")
    assert features.shape[1] == 10
    
    val = features[0][0]
    v = features[0][1]
    osc = features[0][9]
    
    print(f"Value: {val}, Velocity: {v}, Oscillation Residual: {osc:.4f}")
    assert val == 10.5
    assert v == 0.1
    print("SUCCESS: Signal-centric features correctly extracted.")

def test_confidence_decay():
    print("\n--- Testing Confidence Decay ---")
    forecaster = GlucoseForecaster()
    snap = MetabolicSnapshot(
        glucose=GlucoseReading(timestamp=datetime.now(), value=10.0, unit="mmol/L", trend="Flat"),
        filtered_value=10.0, velocity=0.0, acceleration=0.0, atr_14=0.0
    )
    
    _, conf_5 = forecaster.predict([snap], 5)
    _, conf_30 = forecaster.predict([snap], 30)
    _, conf_60 = forecaster.predict([snap], 60)
    
    print(f"Confidence 5m: {conf_5*100:.0f}%")
    print(f"Confidence 30m: {conf_30*100:.0f}%")
    print(f"Confidence 60m: {conf_60*100:.0f}%")
    
    assert conf_5 > conf_30 > conf_60
    print("SUCCESS: Confidence correctly decays over time horizon.")

if __name__ == "__main__":
    try:
        test_kinematic_acceleration()
        test_signal_dynamics_features()
        test_confidence_decay()
        print("\nALL PREDICTION ENGINE TESTS PASSED.\n")
    except Exception as e:
        print(f"\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
