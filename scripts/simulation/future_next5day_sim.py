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
        isf=mc.INSULIN_SENSITIVITY_DEFAULT,
        csf=mc.CARB_SENSITIVITY_DEFAULT,
        gender=config.PATIENT_GENDER,
        age=config.PATIENT_AGE,
        weight_kg=config.PATIENT_WEIGHT_KG,
    )
    # Kinetics Tuning for Lag Spikes (Carbs peak in 45m, Insulin in 120m)
    twin.starch_tau = 45.0 
    mc.INSULIN_PEAK_TAU_RAPID = 120.0 
    mc.INSULIN_ONSET_LAG_MINS = 20.0

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
    
    last_correction_tick = -999
    last_hypo_tick = -999

    # 3. Simulation Loop
    runner = MetabolicInferenceRunner(seq_len=30)
    print(f"Projecting {total_ticks} metabolic states using Neural-Hybrid Engine...")
    
    for tick in range(total_ticks):
        curr_time = start_time + timedelta(minutes=tick * interval_mins)
        hour = curr_time.hour + curr_time.minute / 60.0
        
        # --- SCHEDULE & BEHAVIORAL ENGINE ---
        event = schedule_manager.get_event_at(curr_time)
        
        # --- SYNTHETIC CLIMATOLOGY (Layer 2) ---
        # Weather waves: Temp peaks at 14:00, AQI rises over 5 days
        temp = 22.0 + 8.0 * np.sin((hour - 8) * np.pi / 12) + np.random.normal(0, 1.0)
        humid = 70.0 + 15.0 * np.cos((hour - 6) * np.pi / 12)
        aqi_drift = 50.0 + (tick / total_ticks) * 100.0 # From 50 to 150
        aqi = max(10, aqi_drift + np.random.normal(0, 5))
        
        env_dict = {
            "temperature": temp,
            "humidity": humid,
            "aqi": aqi,
            "is_outdoor": event.is_outdoor if event else False
        }
        
        from diabetic.registry import EnvironmentReading
        env_snapshot = EnvironmentReading(
            timestamp=curr_time,
            temperature=temp,
            humidity=humid,
            aqi=aqi,
            is_outdoor=env_dict["is_outdoor"]
        )
        
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
                    carbs = getattr(event, "carbs", 45) + random.randint(-10, 20) 
                    meal_val = carbs
                    # Bolus Miscalculation (User Error 22%)
                    error_factor = np.random.normal(0.90, 0.22) 
                    bolus_val = (carbs / 10.0) * error_factor
                    
                    curve_c = twin.simulate_carb_impact(meal_val, "STARCH", interval_mins)
                    active_meals.append((tick, np.diff(curve_c, prepend=0.0)))
                    
                    # Bolus Delay (Behavioral flaw: eating before injecting)
                    # Delay randomly between -1 tick (pre-bolus) to +6 ticks (+30 mins late bolus)
                    bolus_delay = random.randint(-1, 6) 
                    curve_i = twin.simulate_insulin_impact(bolus_val, "RAPID", interval_mins)
                    active_insulin.append((tick + bolus_delay, np.diff(curve_i, prepend=0.0)))

        # B. Unexpected Carb Noise (Stressors)
        if tick % (360 // interval_mins) == 0 and random.random() < 0.2:
            snack_carbs = random.randint(15, 25)
            print(f"  [STRESS] Unexpected Snack: {snack_carbs}g at {curr_time.strftime('%H:%M')}")
            curve_s = twin.simulate_carb_impact(snack_carbs, "LIQUID", interval_mins)
            active_meals.append((tick, np.diff(curve_s, prepend=0.0)))
            
        # C. User Bio-Feedback (Corrections & Rescues)
        # 1. Hypo Rescue
        if current_bg < 4.2 and (tick - last_hypo_tick) > (45 / interval_mins):
            rescue_carbs = 15.0 # Standard rule of 15
            print(f"  [RESCUE] Hypo Treatment: {rescue_carbs}g at {curr_time.strftime('%H:%M')} (BG: {current_bg:.1f})")
            curve_r = twin.simulate_carb_impact(rescue_carbs, "LIQUID", interval_mins)
            active_meals.append((tick, np.diff(curve_r, prepend=0.0)))
            last_hypo_tick = tick
            meal_val += rescue_carbs

        # 2. Hyper Correction Bolus
        elif current_bg > 11.5 and (tick - last_correction_tick) > (180 / interval_mins):
            # Only correct if we are drifting high and no recent insulin is active
            req_units = (current_bg - 6.5) / twin.isf
            if req_units > 1.0:
                # "Rage Bolus" mechanic: frustrated user takes 120-180% of what's actually needed!
                rage_factor = np.random.uniform(1.2, 1.8) if random.random() > 0.5 else 1.0
                req_units *= rage_factor
                
                print(f"  [CORRECTION] Bolus: {req_units:.1f}U (Rage:{rage_factor:.1f}) at {curr_time.strftime('%H:%M')} (BG: {current_bg:.1f})")
                curve_c = twin.simulate_insulin_impact(req_units, "RAPID", interval_mins)
                active_insulin.append((tick, np.diff(curve_c, prepend=0.0)))
                last_correction_tick = tick
                bolus_val += req_units

        # --- PHYSIOLOGICAL ENGINE ---
        net_impact = 0.0
        for start_tick, deltas in active_meals:
            idx = tick - start_tick
            if 0 <= idx < len(deltas): net_impact += deltas[idx]
        for start_tick, deltas in active_insulin:
            idx = tick - start_tick
            if 0 <= idx < len(deltas): net_impact -= deltas[idx]
            
        # Circadian Basal-HGO (Hepatic Glucose Output)
        hour = curr_time.hour + curr_time.minute/60.0
        # Dawn Phenomenon (Liver dump in morning) with daily random amplitude variation
        dawn_amp = 0.38 + np.random.normal(0, 0.12)  # High daily volatility in liver dumps
        dawn_effect = dawn_amp * np.exp(-((hour - 6.5)**2) / 2.5)
        
        basal_rate_u = 0.58 
        
        # Get dynamic resistance multiplier from Twin (Aware of Schedule + Temporal + Env)
        snapshot = MetabolicSnapshot(
            glucose=GlucoseReading(timestamp=curr_time, value=current_bg, trend="Flat"),
            environment=env_snapshot 
        )
        res_mult = twin.get_hormonal_multiplier(curr_time) * twin.get_environmental_multiplier(snapshot)

        # Effective Forces (Applying Resistance)
        basal_impact = (basal_rate_u * twin.isf / res_mult) * (interval_mins / 60.0)
        hgo_impact = (basal_impact * 0.94) + (dawn_effect * (interval_mins / 60.0)) # 6% negative drift for realism
        
        # Renal Clearance (The Ceiling)
        renal_clearance = 0.0
        if current_bg > 11.5:
            renal_clearance = (current_bg - 11.5) * mc.RENAL_CLEARANCE_SLOPE 
            
        # Mass Action (Non-Insulin Mediated Glucose Uptake)
        # Tissues passively absorb glucose proportional to gradient above 5.5
        mass_action = 0.015 * (current_bg - 5.5) * (interval_mins / 5.0)
            
        velocity = (net_impact * res_mult) - (basal_impact) + hgo_impact - renal_clearance - mass_action
        current_bg += velocity
        current_bg = max(2.6, current_bg + np.random.normal(0, 0.12)) # Tripled high-frequency noise for volatile CGM realism

        # --- NEURAL ENGINE (CNN Prediction) ---
        # Look ahead prediction (T + 30m)
        glucose_neural = current_bg # Default to current
        if len(records) >= 30:
            window_df = pd.DataFrame(records[-30:])
            # Feed current mechanistic state + weather to CNN
            pred_res = runner.run_inference_on_window(window_df, curr_time, env_data=env_dict)
            glucose_neural = pred_res["glucose"]

        # --- BIOMETRIC SYNTHESIS ---
        g_reading = GlucoseReading(timestamp=curr_time, value=current_bg, trend="NONE")
        cardiac = cardiac_synthesizer.estimate(g_reading, velocity=velocity)

        records.append({
            "timestamp_utc": curr_time.isoformat(),
            "glucose_mmol_l": round(float(current_bg), 3),
            "glucose_neural": round(float(glucose_neural), 3),
            "heart_rate_bpm": cardiac.bpm,
            "hrv_rmssd": cardiac.hrv,
            "is_outdoor": int(env_dict["is_outdoor"]),
            "temperature_c": round(float(temp), 1),
            "aqi": round(float(aqi), 1),
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
