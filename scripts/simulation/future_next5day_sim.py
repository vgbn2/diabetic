import pandas as pd
import numpy as np
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from diabetic.ml_engine.twin import DigitalTwin
from diabetic.ml_engine.inference import MetabolicInferenceRunner
from diabetic.registry import MetabolicSnapshot, GlucoseReading, CardiacReading, EnvironmentReading  # FIX #5: top-level import
from diabetic.utils.schedule import schedule_manager
from diabetic.ml_engine.synthetic_cardiac import cardiac_synthesizer
from diabetic import medical_constants as mc
from diabetic.config import config


# FIX #4: Do not mutate module constants. Define local overrides here.
_STARCH_TAU = 45.0
_INSULIN_PEAK_TAU_RAPID = 120.0
_INSULIN_ONSET_LAG_MINS = 20.0

INTERVAL_MINS = 5.0  # FIX #2: named constant, not magic number


def run_future_5day_simulation():
    """
    Generates a schedule-aware 5-day predictive metabolic simulation.
    Factors: Schedule (Work, Gym, Sleep), Meals, Synthetic Biometrics.
    """
    print("\n--- BIO-QUANT 5-DAY METABOLIC FORECAST ENGINE ---")

    # 1. Setup
    twin = DigitalTwin(
        isf=mc.INSULIN_SENSITIVITY_DEFAULT,
        csf=mc.CARB_SENSITIVITY_DEFAULT,
        gender=config.PATIENT_GENDER,
        age=config.PATIENT_AGE,
        weight_kg=config.PATIENT_WEIGHT_KG,
    )
    # FIX #4: assign on instance, not on the shared module
    twin.starch_tau = _STARCH_TAU
    twin.insulin_peak_tau_rapid = _INSULIN_PEAK_TAU_RAPID
    twin.insulin_onset_lag_mins = _INSULIN_ONSET_LAG_MINS

    # 2. Timeline
    now = datetime.now(timezone.utc)
    start_time = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    total_days = 5
    total_ticks = int((total_days * 24 * 60) / INTERVAL_MINS)

    records = []
    current_bg = 6.5  # Healthy baseline

    active_meals = []    # List of (start_tick, impact_deltas)
    active_insulin = []  # List of (start_tick, impact_deltas)

    last_correction_tick = -999
    last_hypo_tick = -999
    last_meal_tick = -999  # FIX #1 + #10 + #11: explicit tick tracker replaces broken dict lookup

    # 3. Simulation Loop
    runner = MetabolicInferenceRunner(seq_len=30)
    print(f"Projecting {total_ticks} metabolic states using Neural-Hybrid Engine...")

    ticks_per_30m = int(30 / INTERVAL_MINS)
    ticks_per_6h = int(360 / INTERVAL_MINS)
    ticks_per_45m = int(45 / INTERVAL_MINS)
    ticks_per_3h = int(180 / INTERVAL_MINS)

    for tick in range(total_ticks):
        curr_time = start_time + timedelta(minutes=tick * INTERVAL_MINS)
        hour = curr_time.hour + curr_time.minute / 60.0

        # --- SCHEDULE ---
        event = schedule_manager.get_event_at(curr_time)

        # --- SYNTHETIC CLIMATOLOGY ---
        temp = 22.0 + 8.0 * np.sin((hour - 8) * np.pi / 12) + np.random.normal(0, 1.0)
        humid = 70.0 + 15.0 * np.cos((hour - 6) * np.pi / 12)
        aqi_drift = 50.0 + (tick / total_ticks) * 100.0
        aqi = max(10, aqi_drift + np.random.normal(0, 5))

        env_dict = {
            "temperature": temp,
            "humidity": humid,
            "aqi": aqi,
            "is_outdoor": event.is_outdoor if event else False,
        }
        env_snapshot = EnvironmentReading(
            timestamp=curr_time,
            temperature=temp,
            humidity=humid,
            aqi=aqi,
            is_outdoor=env_dict["is_outdoor"],
        )

        meal_val = 0
        bolus_val = 0

        # A. Scheduled Meals
        # FIX #1: use last_meal_tick so we fire at most once per 30-min window per MEAL event
        if event and event.type == "MEAL":
            if (tick - last_meal_tick) >= ticks_per_30m:
                last_meal_tick = tick
                carbs = getattr(event, "carbs", 45) + random.randint(-10, 20)
                meal_val = carbs
                error_factor = np.random.normal(0.90, 0.22)
                bolus_val = (carbs / 10.0) * error_factor

                # FIX #3: simulate_carb_impact returns a cumulative curve; take diff to get per-tick deltas
                curve_c = twin.simulate_carb_impact(meal_val, "STARCH", INTERVAL_MINS)
                active_meals.append((tick, np.diff(curve_c, prepend=0.0)))

                # FIX #6: clamp bolus_delay so start_tick >= 0
                bolus_delay = max(-tick, random.randint(-1, 6))
                curve_i = twin.simulate_insulin_impact(bolus_val, "RAPID", INTERVAL_MINS)
                active_insulin.append((tick + bolus_delay, np.diff(curve_i, prepend=0.0)))

        # B. Unexpected snack noise
        if tick % ticks_per_6h == 0 and random.random() < 0.2:
            snack_carbs = random.randint(15, 25)
            print(f"  [STRESS] Unexpected Snack: {snack_carbs}g at {curr_time.strftime('%H:%M')}")
            curve_s = twin.simulate_carb_impact(snack_carbs, "LIQUID", INTERVAL_MINS)
            active_meals.append((tick, np.diff(curve_s, prepend=0.0)))

        # C. Corrections & Rescues
        if current_bg < 4.2 and (tick - last_hypo_tick) > ticks_per_45m:
            rescue_carbs = 15.0
            print(f"  [RESCUE] Hypo Treatment: {rescue_carbs}g at {curr_time.strftime('%H:%M')} (BG: {current_bg:.1f})")
            curve_r = twin.simulate_carb_impact(rescue_carbs, "LIQUID", INTERVAL_MINS)
            active_meals.append((tick, np.diff(curve_r, prepend=0.0)))
            last_hypo_tick = tick
            meal_val += rescue_carbs

        elif current_bg > 11.5 and (tick - last_correction_tick) > ticks_per_3h:
            req_units = (current_bg - 6.5) / twin.isf
            if req_units > 1.0:
                # FIX #7: only apply rage_factor when actually raging; log accurately
                is_rage = random.random() > 0.5
                rage_factor = np.random.uniform(1.2, 1.8) if is_rage else 1.0
                req_units *= rage_factor
                rage_label = f"RAGE x{rage_factor:.1f}" if is_rage else "NORMAL"
                print(
                    f"  [CORRECTION] Bolus: {req_units:.1f}U ({rage_label}) "
                    f"at {curr_time.strftime('%H:%M')} (BG: {current_bg:.1f})"
                )
                curve_c2 = twin.simulate_insulin_impact(req_units, "RAPID", INTERVAL_MINS)
                active_insulin.append((tick, np.diff(curve_c2, prepend=0.0)))
                last_correction_tick = tick
                bolus_val += req_units

        # --- PHYSIOLOGICAL ENGINE ---
        net_impact = 0.0
        # FIX #9: collect finished curves for pruning
        exhausted_meals = []
        exhausted_insulin = []

        for entry in active_meals:
            start_tick, deltas = entry
            idx = tick - start_tick
            if 0 <= idx < len(deltas):
                net_impact += deltas[idx]
            elif idx >= len(deltas):
                exhausted_meals.append(entry)

        for entry in active_insulin:
            start_tick, deltas = entry
            idx = tick - start_tick
            if 0 <= idx < len(deltas):
                net_impact -= deltas[idx]
            elif idx >= len(deltas):
                exhausted_insulin.append(entry)

        # FIX #9: prune exhausted curves to prevent O(n) blowup
        for e in exhausted_meals:
            active_meals.remove(e)
        for e in exhausted_insulin:
            active_insulin.remove(e)

        # Circadian Basal / HGO
        dawn_amp = 0.38 + np.random.normal(0, 0.12)
        dawn_effect = dawn_amp * np.exp(-((hour - 6.5) ** 2) / 2.5)

        basal_rate_u = 0.58

        snapshot = MetabolicSnapshot(
            glucose=GlucoseReading(timestamp=curr_time, value=current_bg, trend="Flat"),
            environment=env_snapshot,
        )
        res_mult = twin.get_hormonal_multiplier(curr_time) * twin.get_environmental_multiplier(snapshot)

        # Effective forces
        # FIX #8: clearly separate insulin-mediated clearance (negative) from hepatic output (positive)
        basal_clearance = (basal_rate_u * twin.isf / res_mult) * (INTERVAL_MINS / 60.0)  # lowers BG
        hgo = (basal_clearance * 0.94) + (dawn_effect * (INTERVAL_MINS / 60.0))          # raises BG (net ~6% deficit when no dawn)

        renal_clearance = 0.0
        if current_bg > 11.5:
            renal_clearance = (current_bg - 11.5) * mc.RENAL_CLEARANCE_SLOPE

        mass_action = 0.015 * (current_bg - 5.5) * (INTERVAL_MINS / 5.0)

        # velocity: meals raise, insulin+clearance lowers, HGO raises
        velocity = (net_impact * res_mult) - basal_clearance + hgo - renal_clearance - mass_action
        current_bg += velocity
        current_bg = max(2.6, current_bg + np.random.normal(0, 0.12))

        # --- NEURAL ENGINE ---
        glucose_neural = current_bg  # FIX #12: flagged below in record
        neural_valid = False
        if len(records) >= 30:
            window_df = pd.DataFrame(records[-30:])
            pred_res = runner.run_inference_on_window(window_df, curr_time, env_data=env_dict)
            glucose_neural = pred_res["glucose"]
            neural_valid = True

        # --- BIOMETRIC SYNTHESIS ---
        g_reading = GlucoseReading(timestamp=curr_time, value=current_bg, trend="NONE")
        cardiac = cardiac_synthesizer.estimate(g_reading, velocity=velocity)

        records.append({
            "timestamp_utc": curr_time.isoformat(),
            "glucose_mmol_l": round(float(current_bg), 3),
            "glucose_neural": round(float(glucose_neural), 3),
            "neural_valid": int(neural_valid),   # FIX #12: distinguishes warmup from real predictions
            "heart_rate_bpm": cardiac.bpm,
            "hrv_rmssd": cardiac.hrv,
            "is_outdoor": int(env_dict["is_outdoor"]),
            "temperature_c": round(float(temp), 1),
            "aqi": round(float(aqi), 1),
            "event_type": event.type if event else "ROUTINE",
            "sensitivity_mult": round(float(res_mult), 3),
            "meal_carbs": meal_val,
            "insulin_units": bolus_val,
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