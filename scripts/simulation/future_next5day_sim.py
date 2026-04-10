import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from diabetic.ml_engine.twin import DigitalTwin
from diabetic.registry import MetabolicSnapshot, GlucoseReading, CardiacReading, MealEvent, InsulinDose
from diabetic import medical_constants as mc

def run_future_5day_simulation():
    """
    Generates a 5-day predictive metabolic simulation for future projection.
    Uses DigitalTwin physiology engine to model meal and insulin curves.
    """
    print("Launching High-Fidelity 5-Day Metabolic Simulation...")

    # 1. Setup Simulation Engine
    # Using specific patient constants from config for realism
    twin = DigitalTwin(
        isf=mc.INSULIN_SENSITIVITY_DEFAULT,
        csf=mc.CARB_SENSITIVITY_DEFAULT,
        gender="FEMALE", # Based on config.PATIENT_GENDER
        age=19,         # Based on Ottai report age
        weight_kg=45.0, # Based on Ottai report weight
    )

    # 2. Simulation Timeline
    # Start simulation from the last date in our processed report (approx Apr 07)
    # or start from 'now' for a true 'Future' projection.
    # We'll start from April 11, 2026 00:00 (end of report)
    start_time = datetime(2026, 4, 11, 0, 0, 0, tzinfo=timezone.utc)
    interval_mins = 5.0 # 5-minute binned resolution
    total_days = 5
    total_ticks = int((total_days * 24 * 60) / interval_mins)

    records = []
    current_bg = 6.0 # Starting in healthy range

    active_meals = []    # List of (start_tick, impact_deltas)
    active_insulin = []  # List of (start_tick, impact_deltas)

    # 3. Daily Schedule Generation (Simple deterministic model with stochastic variance)
    # 08:00 Breakfast
    # 12:30 Lunch
    # 19:00 Dinner
    schedule = []
    for d in range(total_days):
        d_start = start_time + timedelta(days=d)
        
        # Breakfast
        t_b = d_start + timedelta(hours=8.0, minutes=np.random.normal(0, 15))
        schedule.append({'t': t_b, 'type': 'MEAL', 'carbs': 35, 'gi': 'STARCH'})
        schedule.append({'t': t_b, 'type': 'BOLUS', 'units': 35 / 8.0}) # 1:8 Ratio
        
        # Lunch
        t_l = d_start + timedelta(hours=12.5, minutes=np.random.normal(0, 20))
        schedule.append({'t': t_l, 'type': 'MEAL', 'carbs': 50, 'gi': 'STARCH'})
        schedule.append({'t': t_l, 'type': 'BOLUS', 'units': 50 / 7.0}) # 1:7 Ratio (lower sensitivity midday)
        
        # Dinner
        t_d = d_start + timedelta(hours=19.0, minutes=np.random.normal(0, 30))
        schedule.append({'t': t_d, 'type': 'MEAL', 'carbs': 45, 'gi': 'STARCH'})
        schedule.append({'t': t_d, 'type': 'BOLUS', 'units': 45 / 8.0}) # 1:8 Ratio

    # 4. Simulation Loop
    print(f"Simulating {total_ticks} ticks...")
    for tick in range(total_ticks):
        curr_time = start_time + timedelta(minutes=tick * interval_mins)
        
        # Check for scheduled events
        bolus_val = 0
        meal_val = 0
        for ev in schedule:
            if abs((curr_time - ev['t']).total_seconds()) < (interval_mins * 30): # Search window
                if ev['type'] == 'MEAL' and not ev.get('processed'):
                    ev['processed'] = True
                    meal_val = ev['carbs']
                    curve = twin.simulate_carb_impact(ev['carbs'], ev['gi'], interval_mins)
                    active_meals.append((tick, np.diff(curve, prepend=0.0)))
                elif ev['type'] == 'BOLUS' and not ev.get('processed'):
                    ev['processed'] = True
                    bolus_val = ev['units']
                    curve = twin.simulate_insulin_impact(ev['units'], "RAPID", interval_mins)
                    active_insulin.append((tick, np.diff(curve, prepend=0.0)))

        # Sum active impacts
        net_impact = 0.0
        # Carb Rise
        for start_tick, deltas in active_meals:
            idx = tick - start_tick
            if 0 <= idx < len(deltas): net_impact += deltas[idx]
        # Insulin Drop
        for start_tick, deltas in active_insulin:
            idx = tick - start_tick
            if 0 <= idx < len(deltas): net_impact -= deltas[idx]
            
        # Basal Drift (Simplified)
        # 0.22 mmol/L rise per hour HGO vs 0.32 mmol/L basal insulin coverage
        net_basal = (0.22 - 0.32) * (interval_mins / 60.0)
        
        current_bg += (net_impact + net_basal)
        
        # Physiological Floor & Stochastic Jitter
        current_bg = max(2.5, current_bg + np.random.normal(0, 0.02))

        records.append({
            "timestamp": curr_time.strftime('%Y-%m-%d %H:%M:%S'),
            "glucose": round(current_bg, 3),
            "bolus": 1 if bolus_val > 0 else 0,
            "basal": 0, # Simplified simulation
            "meal": 1 if meal_val > 0 else 0
        })

    # 5. Export and Plot
    df = pd.DataFrame(records)
    csv_path = "storage/data/processed/Future_5Day_Sim.csv"
    df.to_csv(csv_path, index=False)
    print("Simulation Saved: " + csv_path)
    
    # Generate Plot using existing infrastructure
    from diabetic.ingestion.offline.plot_glucose import plot_glucose_data
    plot_path = "storage/data/processed/plots/Future_5Day_Sim.png"
    plot_glucose_data(csv_path, output_image=plot_path)
    print("Plot Generated: " + plot_path)

if __name__ == "__main__":
    run_future_5day_simulation()
