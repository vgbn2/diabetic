import os
import subprocess
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from src.shared.ml.twin import DigitalTwin
from src.shared.ml.predictor import GlucoseForecaster
from src.shared.ml.oracle import BasalOracle
from src.shared.core.registry import MetabolicSnapshot, GlucoseReading, CardiacReading, ProbabilisticForecast, MealEvent, InsulinDose
from src.shared.dsp.kalman import GlucoseFilter
from src.shared.core import medical_constants as mc

class OrnsteinUhlenbeckNoise:
    def __init__(self, dt, theta=0.15, sigma=0.2, mu=0.0):
        self.dt = dt
        self.theta = theta
        self.sigma = sigma
        self.mu = mu
        self.x = mu

    def step(self):
        dx = self.theta * (self.mu - self.x) * self.dt + self.sigma * np.sqrt(self.dt) * np.random.normal()
        self.x += dx
        return self.x

from src.shared.weather.fetcher import WeatherFetcher

def run_climate_aware_simulation():
    print(" Generating Climatological Metabolic Forecast (5-Day Confidence)")

    # 1. CORE ENGINES
    from src.shared.core.config import config
    twin = DigitalTwin(isf=mc.INSULIN_SENSITIVITY_DEFAULT, 
                       csf=mc.CARB_SENSITIVITY_DEFAULT,
                       gender=config.PATIENT_GENDER)
    oracle = BasalOracle()
    forecaster = GlucoseForecaster()
    try:
        forecaster.load_xgboost("models/xgboost_v1.json")
    except Exception: pass
    
    g_filter = GlucoseFilter(dt=mc.SAMPLING_INTERVAL_MINS)

    # 2. ENVIRONMENTAL FORCING (5-DAY)
    fetcher = WeatherFetcher()
    df_env = fetcher.fetch_forecast(days=5)
    if df_env.empty:
        print("[ERROR] Weather forecast unavailable. Aborting.")
        return

    days = 5
    interval = mc.SAMPLING_INTERVAL_MINS
    total_ticks = len(df_env) # Match simulation length to forecast length
    
    start_time = df_env['time'].min()
    history: List[MetabolicSnapshot] = []
    results: List[Dict] = []

    # 3. SENSITIVITY MAPPING
    # Replace random uniform noise with Environmental Sensitivity Logic
    df_env['env_isf_mult'] = 1.0
    df_env['env_isf_mult'] += (df_env['pm2_5'].clip(lower=20) - 20) * 0.002
    df_env['env_isf_mult'] += (df_env['temperature_2m'].clip(lower=30) - 30) * 0.015
    
    print(f"[MODEL] Weather-Induced Resistance: {df_env['env_isf_mult'].min():.2f}x to {df_env['env_isf_mult'].max():.2f}x")

    # Physiological Constants
    TARGET_BG = 8.4
    BASE_HGO_PER_TICK = (0.22) / (60 / interval)
    
    true_bg = 7.5
    active_meals = []
    active_insulin = []
    lag_buffer = [true_bg] * 2

    # 4. CHAOS & STOCHASTICITY (Residual Noise)
    ou_noise  = OrnsteinUhlenbeckNoise(dt=interval, sigma=0.15) # Damping noise since weather handles macro-fluctuations

    events = []
    for day in range(days):
        day_start = start_time + timedelta(days=day)
        def get_dose(carbs, ratio):
            exact = carbs / ratio
            error = np.random.uniform(0.95, 1.05)
            return exact * error

        # Breakfast (8:30)
        t_b = day_start + timedelta(hours=8.5)
        c_b = 45
        events.append({'t': t_b, 'type': 'MEAL', 'val': c_b, 'gi': "STARCH"})
        events.append({'t': t_b, 'type': 'BOLUS', 'val': get_dose(c_b, 8.0)})

        # Lunch (13:00)
        t_l = day_start + timedelta(hours=13.0)
        c_l = 60
        events.append({'t': t_l, 'type': 'MEAL', 'val': c_l, 'gi': "STARCH"})
        events.append({'t': t_l, 'type': 'BOLUS', 'val': get_dose(c_l, 7.5)})

    # 5. SIMULATION LOOP
    for tick in range(total_ticks):
        current_time = df_env.iloc[tick]['time']
        env_isf_mult = df_env.iloc[tick]['env_isf_mult']

        if tick > 0 and tick % int(360 / interval) == 0:
            twin.detect_regime(history)
            oracle.fit(history)

        # Apply environmental forced resistance
        isf_mult = (1.0 / env_isf_mult) * twin.regime_multiplier
        csf_mult = env_isf_mult

        carb_impact = 0.0
        for start_tick, deltas in active_meals:
            idx = tick - start_tick
            if 0 <= idx < len(deltas):
                carb_impact += deltas[idx] * csf_mult

        ins_impact = 0.0
        for start_tick, deltas in active_insulin:
            idx = tick - start_tick
            if 0 <= idx < len(deltas):
                ins_impact += deltas[idx] * isf_mult

        physio_delta = carb_impact - ins_impact
        hgo_suppression = min(1.0, max(0.0, (true_bg - TARGET_BG) / 8.0))
        effective_hgo   = BASE_HGO_PER_TICK * (1.0 - hgo_suppression)
        basal_loss_per_tick = (0.32) / (60 / interval)
        net_basal = effective_hgo - basal_loss_per_tick

        if true_bg > mc.RENAL_THRESHOLD:
            net_basal -= (true_bg - mc.RENAL_THRESHOLD) * 0.002

        impending = physio_delta + net_basal
        if true_bg + impending < mc.LOW_SIDE_THRESHOLD:
            physio_delta *= 0.5
            if true_bg + impending < mc.PHYSIO_FLOOR: net_basal += 0.05

        net_tick_impact = physio_delta + net_basal
        true_bg += net_tick_impact
        true_bg = max(mc.PHYSIO_FLOOR, min(24.0, true_bg))

        lag_buffer.append(true_bg)
        sensor_reported_clean = lag_buffer[0]
        if len(lag_buffer) > 2: lag_buffer.pop(0)

        # Combined Noise
        raw_noisy_val = sensor_reported_clean + ou_noise.step()
        raw_noisy_val = max(2.5, min(24.0, raw_noisy_val))

        reading = GlucoseReading(timestamp=current_time, value=round(raw_noisy_val, 2), trend="Flat")
        snap = g_filter.update(reading)

        # --- Ultra-Predictive Forecast (Monte Carlo) ---
        t_future = [current_time + timedelta(minutes=i * interval) for i in range(int(240/interval)+1)]
        ref_start = start_time
        basal_drift_pred = np.array([oracle.get_expected_basal(tf, ref_start) for tf in t_future])
        
        curr_meals = []
        for e in events:
            if 0 < (current_time - e['t']).total_seconds() / 60.0 < 240 and e['type'] == 'MEAL':
                curr_meals.append(MealEvent(timestamp=e['t'], carbs=e['val'], gi_type=e.get('gi', 'STARCH')))
        curr_insulin = []
        for e in events:
            if 0 < (current_time - e['t']).total_seconds() / 60.0 < 240 and e['type'] == 'BOLUS':
                curr_insulin.append(InsulinDose(timestamp=e['t'], units=e['val'], type="RAPID"))

        mean_traj, p5_traj, p95_traj = twin.predict_monte_carlo(history, curr_meals, curr_insulin, basal_drift=basal_drift_pred, N=15)
        
        idx_30 = int(30/interval)
        snap.forecast = ProbabilisticForecast(
            timestamp=current_time,
            mean=float(mean_traj[idx_30]),
            p5=float(p5_traj[idx_30]),
            p95=float(p95_traj[idx_30]),
            std_dev=float(np.std(mean_traj))
        )

        # Event ingestion
        for e in events:
            dt_ev = (current_time - e['t']).total_seconds() / 60.0
            if abs(dt_ev) < (interval / 2.0):
                if e['type'] == 'MEAL':
                    full_curve = twin.simulate_carb_impact(e['val'], e.get('gi', 'STARCH'), interval, timestamp=current_time)
                    active_meals.append((tick, np.diff(full_curve, prepend=0.0)))
                else:
                    full_ins = twin.simulate_insulin_impact(e['val'], "RAPID", interval, timestamp=current_time)
                    active_insulin.append((tick, np.diff(full_ins, prepend=0.0)))

        history.append(snap)
        pred = None
        if len(history) >= 25:
            pred, _ = forecaster.predict(history[-25:], 30.0)

        results.append({
            'timestamp':       current_time.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
            'glucose':         round(snap.filtered_value, 2),
            'true_bg':         round(true_bg, 4),
            'pm2_5':           df_env.iloc[tick]['pm2_5'],
            'temp':            df_env.iloc[tick]['temperature_2m'],
            'env_resistance':  round(env_isf_mult, 3),
            'predicted_30m':   round(pred, 2) if pred else None
        })

    df = pd.DataFrame(results)
    forensic_path = "storage/data/climate_forecast_5d.csv"
    df.to_csv(forensic_path, index=False)
    print(f"✅ Climatological Simulation Complete. Path: {forensic_path}")

if __name__ == "__main__":
    run_climate_aware_simulation()
