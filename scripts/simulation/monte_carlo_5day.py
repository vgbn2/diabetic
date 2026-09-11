import pandas as pd
import numpy as np
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from diabetic.ml_engine.twin import DigitalTwin
from diabetic.ml_engine.inference import MetabolicInferenceRunner
from diabetic.registry import MetabolicSnapshot, GlucoseReading, CardiacReading, EnvironmentReading
from diabetic.utils.schedule import schedule_manager
from diabetic.ml_engine.synthetic_cardiac import cardiac_synthesizer
from diabetic import medical_constants as mc
from diabetic.config import config

INTERVAL_MINS = 5.0
NUM_SIMULATIONS = 20  # Total iterations for Monte Carlo

def run_single_simulation(simulation_id: int):
    # Setup
    twin = DigitalTwin(
        isf=mc.INSULIN_SENSITIVITY_DEFAULT,
        csf=mc.CARB_SENSITIVITY_DEFAULT,
        gender=config.PATIENT_GENDER,
        age=config.PATIENT_AGE,
        weight_kg=config.PATIENT_WEIGHT_KG,
    )
    twin.starch_tau = 45.0
    twin.insulin_peak_tau_rapid = 120.0
    twin.insulin_onset_lag_mins = 20.0

    now = datetime.now(timezone.utc)
    start_time = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    total_ticks = int((5 * 24 * 60) / INTERVAL_MINS)

    records = []
    current_bg = 6.5
    active_meals = []
    active_insulin = []
    last_correction_tick = -999
    last_hypo_tick = -999
    last_meal_tick = -999

    ticks_per_30m = int(30 / INTERVAL_MINS)
    ticks_per_6h = int(360 / INTERVAL_MINS)
    ticks_per_45m = int(45 / INTERVAL_MINS)
    ticks_per_3h = int(180 / INTERVAL_MINS)

    for tick in range(total_ticks):
        curr_time = start_time + timedelta(minutes=tick * INTERVAL_MINS)
        hour = curr_time.hour + curr_time.minute / 60.0
        event = schedule_manager.get_event_at(curr_time)

        # Env
        temp = 22.0 + 8.0 * np.sin((hour - 8) * np.pi / 12) + np.random.normal(0, 1.0)
        humid = 70.0 + 15.0 * np.cos((hour - 6) * np.pi / 12)
        aqi_drift = 50.0 + (tick / total_ticks) * 100.0
        aqi = max(10, aqi_drift + np.random.normal(0, 5))
        env_snapshot = EnvironmentReading(timestamp=curr_time, temperature=temp, humidity=humid, aqi=aqi, is_outdoor=event.is_outdoor if event else False)

        # Logic
        if event and event.type == "MEAL":
            if (tick - last_meal_tick) >= ticks_per_30m:
                last_meal_tick = tick
                carbs = getattr(event, "carbs", 45) + random.randint(-10, 20)
                error_factor = np.random.normal(0.90, 0.22)
                bolus_val = (carbs / 10.0) * error_factor
                active_meals.append((tick, np.diff(twin.simulate_carb_impact(carbs, "STARCH", INTERVAL_MINS), prepend=0.0)))
                bolus_delay = max(-tick, random.randint(-1, 6))
                active_insulin.append((tick + bolus_delay, np.diff(twin.simulate_insulin_impact(bolus_val, "RAPID", INTERVAL_MINS), prepend=0.0)))

        if tick % ticks_per_6h == 0 and random.random() < 0.2:
            snack_carbs = random.randint(15, 25)
            active_meals.append((tick, np.diff(twin.simulate_carb_impact(snack_carbs, "LIQUID", INTERVAL_MINS), prepend=0.0)))

        if current_bg < 4.2 and (tick - last_hypo_tick) > ticks_per_45m:
            active_meals.append((tick, np.diff(twin.simulate_carb_impact(15.0, "LIQUID", INTERVAL_MINS), prepend=0.0)))
            last_hypo_tick = tick

        elif current_bg > 11.5 and (tick - last_correction_tick) > ticks_per_3h:
            req_units = ((current_bg - 6.5) / twin.isf) * (np.random.uniform(1.2, 1.8) if random.random() > 0.5 else 1.0)
            if req_units > 1.0:
                active_insulin.append((tick, np.diff(twin.simulate_insulin_impact(req_units, "RAPID", INTERVAL_MINS), prepend=0.0)))
                last_correction_tick = tick

        # Physics
        net_impact = 0.0
        active_meals = [e for e in active_meals if tick - e[0] < len(e[1])]
        active_insulin = [e for e in active_insulin if tick - e[0] < len(e[1])]
        for start_tick, deltas in active_meals: net_impact += deltas[tick - start_tick]
        for start_tick, deltas in active_insulin: net_impact -= deltas[tick - start_tick]

        res_mult = twin.get_hormonal_multiplier(curr_time) * twin.get_environmental_multiplier(MetabolicSnapshot(glucose=GlucoseReading(timestamp=curr_time, value=current_bg, trend="Flat"), environment=env_snapshot))
        basal_clearance = (0.58 * twin.isf / res_mult) * (INTERVAL_MINS / 60.0)
        hgo = (basal_clearance * 0.94) + ((0.38 + np.random.normal(0, 0.12)) * np.exp(-((hour - 6.5) ** 2) / 2.5) * (INTERVAL_MINS / 60.0))
        renal = (current_bg - 11.5) * mc.RENAL_CLEARANCE_SLOPE if current_bg > 11.5 else 0.0
        mass_action = 0.015 * (current_bg - 5.5) * (INTERVAL_MINS / 5.0)

        velocity = (net_impact * res_mult) - basal_clearance + hgo - renal - mass_action
        current_bg = max(2.6, current_bg + velocity + np.random.normal(0, 0.12))
        records.append(current_bg)
    
    return records, start_time

def run_monte_carlo():
    print(f"Starting Monte Carlo Simulation ({NUM_SIMULATIONS} iterations)...")
    all_runs = []
    start_time = None
    for i in range(NUM_SIMULATIONS):
        run, st = run_single_simulation(i)
        all_runs.append(run)
        start_time = st
        if (i+1) % 5 == 0: print(f"  Completed {i+1}/{NUM_SIMULATIONS}")

    # Statistics
    data = np.array(all_runs)
    mean_bg = np.mean(data, axis=0)
    p5_bg = np.percentile(data, 5, axis=0)
    p95_bg = np.percentile(data, 95, axis=0)
    
    # Plotting
    total_ticks = data.shape[1]
    timestamps = [start_time + timedelta(minutes=i * INTERVAL_MINS) for i in range(total_ticks)]
    
    plt.figure(figsize=(15, 8))
    plt.fill_between(timestamps, p5_bg, p95_bg, color='#1f77b4', alpha=0.2, label='90% Confidence Interval (P5-P95)')
    plt.plot(timestamps, mean_bg, color='#1f77b4', linewidth=2, label='Mean Glucose Trajectory')
    
    # Plot individual runs (subset)
    for i in range(min(5, NUM_SIMULATIONS)):
        plt.plot(timestamps, all_runs[i], alpha=0.1, color='black', linewidth=0.5)

    plt.axhline(y=3.9, color='red', linestyle='--', alpha=0.5, label='Hypo Threshold (3.9)')
    plt.axhline(y=10.0, color='orange', linestyle='--', alpha=0.5, label='Target Ceiling (10.0)')
    plt.axhline(y=14.0, color='darkred', linestyle='--', alpha=0.3, label='Hyper Threshold (14.0)')

    plt.ylim(2.0, 18.0)
    plt.title(f'Monte Carlo Metabolic Forecast (n={NUM_SIMULATIONS})', fontsize=14)
    plt.ylabel('Glucose (mmol/L)', fontsize=12)
    plt.xlabel('Date', fontsize=12)
    plt.grid(True, alpha=0.2)
    plt.legend(loc='upper right')
    
    ax = plt.gca()
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Save
    out_path = 'data/forecasts/monte_carlo_forecast.png'
    os.makedirs('data/forecasts', exist_ok=True)
    plt.savefig(out_path, dpi=150)
    print(f"Saved Monte Carlo plot to {out_path}")
    
    # Copy to artifacts
    import shutil
    artifact_dir = r"C:\Users\Lenovo\.gemini\antigravity\brain\831e32d2-df04-499c-97e4-478c48be0d3c"
    shutil.copy(out_path, os.path.join(artifact_dir, "monte_carlo_forecast.png"))

if __name__ == "__main__":
    run_monte_carlo()
