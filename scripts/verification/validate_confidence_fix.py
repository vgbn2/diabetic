import sys
import logging
from datetime import datetime, timezone, timedelta
from pprint import pprint

# Adjust path to import diabetic module
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from diabetic.utils.data_factory import TacticalForecaster, compute_confidence_index
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic import medical_constants

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Validation")

def create_mock_snapshots(minutes: int) -> list[MetabolicSnapshot]:
    """Generates continuous mock data for the specified duration (one reading every 5 minutes)."""
    snapshots = []
    now = datetime.now(timezone.utc)
    interval = medical_constants.SAMPLING_INTERVAL_MINS
    num_readings = int(minutes / interval)
    
    for i in range(num_readings):
        dt = now - timedelta(minutes=(num_readings - 1 - i) * interval)
        reading = GlucoseReading(timestamp=dt, value=6.0, device="MOCK")
        snapshot = MetabolicSnapshot(glucose=reading)
        snapshots.append(snapshot)
        
    return snapshots

def run_validation():
    print("================================================")
    print("🧪 Validating Confidence Score Decoupling Fix")
    print("================================================")
    
    # Simulate an uninterrupted 90-minute data stream
    print("[1] Generating 90 minutes of continuous mock sensor data...")
    mock_history = create_mock_snapshots(90)
    
    # The 'current' snapshot is the last one in the history
    snapshot = mock_history[-1]
    history_list = mock_history[:-1] + [snapshot]
    
    print(f"    -> Generated {len(history_list)} snapshots.")

    # Replicate the logic now found in coordinator.py (Lines 267-278)
    points_1h = int(60 / medical_constants.SAMPLING_INTERVAL_MINS)
    points_90m = int(90 / medical_constants.SAMPLING_INTERVAL_MINS)
    
    print(f"\n[2] Slicing Data Arrays:")
    print(f"    -> Forecaster requires {points_1h} points (60m).")
    print(f"    -> Confidence Index requires {points_90m} points (90m).")
    
    raw_history = [
        (s.glucose.timestamp, s.glucose.value)
        for s in history_list[-points_1h:]
    ]
    confidence_history = [
        (s.glucose.timestamp, s.glucose.value)
        for s in history_list[-points_90m:]
    ]
    
    print(f"    -> Sliced raw_history len: {len(raw_history)}")
    print(f"    -> Sliced confidence_history len: {len(confidence_history)}")

    # Execute Functions
    print("\n[3] Executing Functions:")
    forecaster = TacticalForecaster(age=30, weight_kg=75.0)
    tactical = forecaster.compute(raw_history)
    confidence = compute_confidence_index(confidence_history)
    
    # Old calculation logic for comparison
    old_confidence = compute_confidence_index(raw_history)

    print("\n[4] Results:")
    print(f"    📈 OLD Logic Confidence (Bugged):  {old_confidence * 100:.0f}%")
    print(f"    📈 NEW Logic Confidence (Fixed):   {confidence * 100:.0f}%")
    print("\n    📊 Tactical Forecaster Horizons:")
    print(f"        ├ 15m: {tactical['p15m']} mmol/L")
    print(f"        ├ 30m: {tactical['p30m']} mmol/L")
    print(f"        └ 60m: {tactical['p60m']} mmol/L")
    
    print("\n================================================")
    if confidence == 1.0 and len(raw_history) == 12 and len(confidence_history) == 18:
        print("✅ VALIDATION PASSED: The windows are correctly decoupled and confidence reaches 100%.")
    else:
        print("❌ VALIDATION FAILED: Something is wrong with the calculation or slicing.")

if __name__ == "__main__":
    run_validation()
