import time
import sys
from datetime import datetime
from src.coordinator import BioQuantCoordinator
from src.logger import logger

def run_nuclear_execution(mode: str = "simulation"):
    """
    Runs the full Bio-Quant pipeline.
    Modes: 
      - 'live': Connects to Nightscout API.
      - 'simulation': Generates synthetic data to test AI logic.
    """
    print("="*60)
    print("      ☢️  BIO-QUANT: NUCLEAR EXECUTION ACTIVATED  ☢️      ")
    print("="*60)
    
    coordinator = BioQuantCoordinator(use_mock_model=True)
    
    if mode == "simulation":
        print("\n[MODE] SIMULATION: Testing AI response to Stress + Glucose Spikes...")
        # Synthetic scenario: Rapid rise + Sudden Stress (Emotional Spike)
        mock_scenarios = [
            {"g": 110, "hrv": 55.0, "note": "Stable Baseline"},
            {"g": 135, "hrv": 50.0, "note": "Glucose rising..."},
            {"g": 180, "hrv": 25.0, "note": "SUDDEN STRESS (HRV Drop) + Sharp Spike"},
            {"g": 250, "hrv": 15.0, "note": "Continued Stress..."},
            {"g": 310, "hrv": 10.0, "note": "CRITICAL HYPER + EXTREME STRESS"}
        ]
        
        for i, scene in enumerate(mock_scenarios):
            print(f"\n--- Cycle {i+1}: {scene['note']} ---")
            
            # In simulation, we bypass the Nightscout client and inject values
            # (In a real run, this would be coordinator.run_cycle())
            dsi = coordinator.stress_tracker.get_current_dsi(current_rmssd=scene['hrv'])
            coordinator.stress_tracker.add_reading(
                type('HRVRecord', (object,), {'timestamp': datetime.now(), 'rmssd': scene['hrv']})
            )
            
            # UKF Update
            filtered = coordinator.ukf.update(z_glucose=scene['g'], dsi=dsi)
            
            # ML Prediction (Mocked for simulation)
            predicted_30m = filtered['glucose'] + (filtered['velocity'] * 30)
            
            # AI Alert Controller
            alert_level, message = coordinator.alert_controller.evaluate_state(
                current_glucose=scene['g'],
                predicted_glucose=predicted_30m,
                dsi=dsi
            )
            
            print(f"📊 METRICS | Glucose: {scene['g']} | Filtered: {filtered['glucose']:.1f} | Velocity: {filtered['velocity']:.2f}")
            print(f"🧠 AI DSI  | Stress Index: {dsi:.2f} (Base: {coordinator.stress_tracker.baseline_hrv:.1f})")
            print(f"📢 ALERT   | [{alert_level}] - {message}")
            time.sleep(1)

    elif mode == "live":
        print("\n[MODE] LIVE: Connecting to Nightscout API...")
        try:
            while True:
                # In a live environment, HRV would come from a wearable API
                # For now, we use a neutral baseline for HR
                result = coordinator.run_cycle(current_hrv=50.0)
                
                if result.get("status") == "NO_DATA":
                    print("Waiting for Nightscout data...")
                else:
                    print(f"\n[{result['timestamp'].strftime('%H:%M:%S')}] G: {result['glucose']} | Stress: {result['dsi']:.1f} | Alert: {result['alert_level']}")
                    print(f"AI Message: {result['message']}")
                
                print("Sleeping for 5 minutes (next CGM interval)...")
                time.sleep(300) 
        except KeyboardInterrupt:
            print("\nExecution terminated by user.")

    print("\n" + "="*60)
    print("      NUCLEAR EXECUTION COMPLETE. SYSTEM STANDBY.      ")
    print("="*60)

if __name__ == "__main__":
    # Default to simulation if no args provided
    mode = sys.argv[1] if len(sys.argv) > 1 else "simulation"
    run_nuclear_execution(mode=mode)
