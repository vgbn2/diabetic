import sys
import os
from datetime import datetime, timedelta
from typing import List, Optional

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

# Mocking parts of Coordinator to allow synchronous testing
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic.dsp.kalman import GlucoseFilter
from diabetic.dsp.metabolic_math import MetabolicMath
from diabetic.ml_engine.predictor import GlucoseForecaster
from diabetic.telegram_bot.decision_matrix import DecisionMatrix, CircuitBreaker, Alert
from diabetic import medical_constants
from diabetic.config import config

class SyncTester:
    def __init__(self):
        self.filter = GlucoseFilter()
        self.forecaster = GlucoseForecaster()
        self.alert_guard = DecisionMatrix()
        self.breaker = CircuitBreaker()
        self.history: List[MetabolicSnapshot] = []

    def process(self, reading: GlucoseReading):
        # 1. Kalman
        snapshot = self.filter.update(reading)
        
        # 2. Extract Kinematics
        v, a = MetabolicMath.extract_kinematics(self.history + [snapshot])
        snapshot.velocity = v
        snapshot.acceleration = a
        
        # 3. Forecast 30m
        prediction = self.forecaster.predict_30m(self.history + [snapshot])
        
        # 4. Alerting logic
        alert = self.alert_guard.evaluate(snapshot, prediction)
        
        # 5. Circuit Breaker
        can_trigger = "BLOCKED"
        if alert:
            if self.breaker.can_alert(alert.type, severity=alert.severity):
                can_trigger = "TRIGGERED"
        
        self.history.append(snapshot)
        
        status = f"G:{snapshot.filtered_value:.1f} V:{snapshot.velocity:+.2f} P30:{prediction:.1f}"
        alert_str = f"ALERT: [{alert.type}] {alert.message[:40]}..." if alert else "NORMAL"
        print(f"[{reading.timestamp.strftime('%H:%M')}] {status} | {alert_str} ({can_trigger})")

def run_tests():
    tester = SyncTester()
    start_time = datetime.now()
    
    print("\n" + "="*60)
    print("  SYNCHRONOUS SAFETY VERIFICATION: BIO-QUANT ENGINE  ")
    print("="*60)

    # Scenario 1: HYPO CRASH (Emergency Bypass Verification)
    print("\n[SCENARIO 1: HYPO CRASH]")
    print("-" * 30)
    crash_vals = [6.5, 6.0, 5.2, 4.2, 3.5, 3.0, 2.8, 2.5]
    for i, v in enumerate(crash_vals):
        tester.process(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=v, trend="DoubleDown"))

    # Scenario 2: FAINT RISK (Cardiac & Dawn Damping Verification)
    print("\n[SCENARIO 2: FAINT RISK]")
    print("-" * 30)
    # Start high and rising fast
    tester_faint = SyncTester()
    faint_vals = [15.5, 16.2, 16.9, 17.5, 18.2, 19.0]
    for i, v in enumerate(faint_vals):
        tester_faint.process(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=v, trend="FortyFiveUp"))

    print("\n" + "="*60)
    print("  VERIFICATION COMPLETE  ")
    print("="*60 + "\n")

if __name__ == "__main__":
    run_tests()
