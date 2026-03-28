import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from diabetic.config import config
from diabetic.coordinator import Coordinator
from diabetic.registry import GlucoseReading

# Core orchestration logic relocated to diabetic/main.py

async def run_simulation(scenario: str):
    """
    Runs a metabolic simulation scenario.
    Scenarios: 'crash', 'faint', 'simulation' (stress)
    """
    coordinator = Coordinator()
    print(f"\n{'='*60}")
    print(f"  SYSTEM RUNTIME: BIO-QUANT (MODE: SIMULATION - {scenario.upper()})  ")
    print(f"{'='*60}\n")

    # Simulation data generation
    readings = []
    start_time = datetime.now(timezone.utc)
    
    if scenario == "crash":
        # Rapid drop from normal to hypoglycemia
        print("SIMULATION: Initiating Rapid Hypoglycemic Crash...")
        for i in range(10):
            val = 110 - (i * 10) # dropping fast (mg/dL internally for logic? No, registry says mmol/L)
            # Wait, 110 mmol/L is huge. Registry says mmol/L. 
            # If 110 is mg/dL, it's ~6.1 mmol/L. Let's use mmol/L directly.
            # Normal: 5.0. Crash: 3.0.
            val_mmol = 6.1 - (i * 0.5) 
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="DoubleDown"))
    elif scenario == "faint":
        # High hyperglycemia with suspected faint risk factors (Rapid climb)
        print("SIMULATION: Initiating Hyperglycemic Faint Risk (High + Rapid Rise)...")
        for i in range(10):
            val_mmol = 15.0 + (i * 0.8) # starting high and rising fast
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="FortyFiveUp"))
    else:
        # 'simulation' or 'normal' stress test
        print("SIMULATION: Normal Metabolic Stress Test...")
        for i in range(10):
            val_mmol = 8.0 + (i * 0.1)
            readings.append(GlucoseReading(timestamp=start_time + timedelta(minutes=i*5), value=val_mmol, trend="Flat"))

    for r in readings:
        await coordinator._process_reading(r)
        await asyncio.sleep(0.05) # Speed up simulation

async def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd in ["crash", "faint", "simulation", "normal"]:
            scenario = cmd
            await run_simulation(scenario)
        elif cmd == "live":
            coordinator = Coordinator()
            await coordinator.start_live_mode()
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: python main.py [crash|faint|simulation|live]")
    else:
        # Default to regular simulation
        await run_simulation("simulation")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSystem stopped by user.")
