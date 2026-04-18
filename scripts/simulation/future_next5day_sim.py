import pandas as pd
import numpy as np
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from diabetic.ml_engine.twin import DigitalTwin
from diabetic.ml_engine.inference import MetabolicInferenceRunner
from diabetic.registry import MetabolicSnapshot, GlucoseReading, CardiacReading
from diabetic.utils.schedule import schedule_manager
from diabetic.ml_engine.synthetic_cardiac import cardiac_synthesizer
from diabetic import medical_constants as mc
from diabetic.config import config

def run_future_5day_simulation():
    """
    Generates a schedule-aware 5-day predictive metabolic simulation.
    Factor: Schedule (Work, Gym, Sleep), Meals, Synthetic Biometrics.
    """
    print("\n--- BIO-QUANT 5-DAY METABOLIC FORECAST ENGINE ---")
    
    # 1. Setup Simulation Engine (Physiological Harmony)
    twin = DigitalTwin(
        isf=1.0,          # 1 unit -> 1.0 mmol/L drop
        csf=0.10,         # 10g carbs -> 1.0 mmol/L rise
        gender=config.PATIENT_GENDER,
        age=config.PATIENT_AGE,
        weight_kg=config.PATIENT_WEIGHT_KG,
    )
    # Kinetics: Carbs hit fast, Insulin hits slow = Natural Spike
    twin.starch_tau = 50.0 
    mc.INSULIN_PEAK_TAU_RAPID = 110.0

    # 2. Simulation Timeline
    now = datetime.now(timezone.utc)
    # Start at top of the next hour for cleanliness
    start_time = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    interval_mins = 5.0 
    total_days = 5
    total_ticks = int((total_days * 24 * 60) / interval_mins)

    records = []
    current_bg = 6.5 # Healthy baseline

    active_meals = []    # List of (start_tick, impact_deltas)
    active_insulin = []  # List of (start_tick, impact_deltas)

    # 3. Simulation Loop
    runner = MetabolicInferenceRunner(seq_len=30)
    print(f"Projecting {total_ticks} metabolic states using Neural-Hybrid Engine...")
    
    for tick in range(total_ticks):
        curr_time = start_time + timedelta(minutes=tick * interval_mins)
        
        # --- SCHEDULE & BEHAVIORAL ENGINE ---
        event = schedule_manager.get_event_at(curr_time)
        
        # Check for Meal/Bolus trigger
        meal_val = 0
        bolus_val = 0
        
        # A. Scheduled Meals
        if event and event.type == "MEAL":
            # Start of meal (approximate)
            if tick % (30 // interval_mins) == 0: # Check every 30 mins to avoid re-triggering within same event window
                # Check if we already processed a meal for this window
                last_meal_time = records[-1].get("meal_event") if records else None
                if not last_meal_time:
                    # In a real system, we'd track IDs. Here we use presence of 'carbs' in schema or hardcode
                    carbs = getattr(event, "carbs", 40) 
                    meal_val = carbs
                    bolus_val = carbs / 10.0 # Standard 1:10 Ratio for perfect balance
                    
                    curve_c = twin.simulate_carb_impact(meal_val, "STARCH", interval_mins)
                    active_meals.append((tick, np.diff(curve_c, prepend=0.0)))
                    
                    curve_i = twin.simulate_insulin_impact(bolus_val, "RAPID", interval_mins)
                    active_insulin.append((tick, np.diff(curve_i, prepend=0.0)))

        # B. Unexpected Carb Noise
        if tick % (360 // interval_mins) == 0 and random.random() < 0.2:
            snack_carbs = random.randint(15, 25)
            print(f"  [STRESS] Unexpected Snack: {snack_carbs}g at {curr_time.strftime('%H:%M')}")
            curve_s = twin.simulate_carb_impact(snack_carbs, "LIQUID", interval_mins)
            active_meals.append((tick, np.diff(curve_s, prepend=0.0)))

        # --- PHYSIOLOGICAL ENGINE (Mechanistic Truth) ---
        net_impact = 0.0
        # Carb Rise
        for start_tick, deltas in active_meals:
            idx = tick - start_tick
            if 0 <= idx < len(deltas): net_impact += deltas[idx]
        # Insulin Drop
        for start_tick, deltas in active_insulin:
            idx = tick - start_tick
            if 0 <= idx < len(deltas): net_impact -= deltas[idx]
            
        # Get dynamic resistance multiplier from Twin (Aware of Schedule + Temporal)
        snapshot = MetabolicSnapshot(
            glucose=GlucoseReading(timestamp=curr_time, value=current_bg, trend="Flat"),
            environment=None # Placeholder
        )
        res_mult = twin.get_hormonal_multiplier(curr_time)
        
        # Neutral basal (Basal - HGO = 0)
        net_basal = (0.22 - 0.22) * (interval_mins / 60.0)
        
        velocity = (net_impact + net_basal)
        current_bg += velocity
        
        # Physical Floor
        current_bg = max(mc.PHYSIO_FLOOR, current_bg + np.random.normal(0, 0.010)) # Reduced noise for neural clarity

        # --- NEURAL ENGINE (CNN Prediction) ---
        # Look ahead prediction (T + 30m)
        glucose_neural = current_bg # Default to current
        if len(records) >= 30:
            window_df = pd.DataFrame(records[-30:])
            # Feed current mechanistic state to CNN
            pred_val = runner.run_inference_on_window(window_df, curr_time)
            # The model predicts scaled glucose. Convert back using 20x multiplier.
            glucose_neural = pred_val * 20.0 

        # --- BIOMETRIC SYNTHESIS ---
        g_reading = GlucoseReading(timestamp=curr_time, value=current_bg, trend="NONE")
        cardiac = cardiac_synthesizer.estimate(g_reading, velocity=velocity)

        records.append({
            "timestamp_utc": curr_time.isoformat(),
            "glucose_mmol_l": round(float(current_bg), 3),
            "glucose_neural": round(float(glucose_neural), 3),
            "heart_rate_bpm": cardiac.bpm,
            "hrv_rmssd": cardiac.hrv,
            "is_outdoor": int(event.is_outdoor if event else False),
            "event_type": event.type if event else "ROUTINE",
            "sensitivity_mult": round(float(res_mult), 3),
            "meal_carbs": meal_val,
            "insulin_units": bolus_val
        })

    # 4. Export
    df = pd.DataFrame(records)
    out_dir = Path("data/forecasts")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{start_time.strftime('%Y-%m-%d')}_5day_forecast.csv"
    csv_path = out_dir / filename
    df.to_csv(csv_path, index=False)
    
    print(f"\nSUCCESS: Forecast Generated.")
    print(f"Path: {csv_path}")
    print(f"Sample First 3 Rows:\n{df.head(3)}")

if __name__ == "__main__":
    run_future_5day_simulation()
