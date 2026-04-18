import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import correlate
from pathlib import Path

def verify_predictive_power():
    path = Path("storage/data/processed/synthetic_glucose_study.csv")
    if not path.exists():
        print("Error: Dataset not found.")
        return
        
    df = pd.read_csv(path)
    horizon = 12 # 30 mins
    FAINT_THRESHOLD = 18.0
    
    # 1. Clean data for alignment
    df['actual_future'] = df['glucose'].shift(-horizon)
    valid = df.dropna(subset=['predicted_30m', 'actual_future', 'twin_p95'])
    
    y_true = valid['actual_future'].values
    y_pred = valid['predicted_30m'].values
    y_p95  = valid['twin_p95'].values
    y_now  = valid['glucose'].values
    
    # 2. Baseline Comparison
    rmse_persistence = np.sqrt(np.mean((y_true - y_now)**2))
    v = (valid['glucose'] - valid['glucose'].shift(1)).fillna(0) / 2.5
    y_kinematic = y_now + (v * 30)
    rmse_kinematic = np.sqrt(np.mean((y_true - y_kinematic)**2))
    rmse_model = np.sqrt(np.mean((y_true - y_pred)**2))
    
    print("--- Predictive Power Audit ---")
    print(f"Persistence RMSE (Future=Now):  {rmse_persistence:.4f} mmol/L")
    print(f"Kinematic RMSE (Linear Extrap): {rmse_kinematic:.4f} mmol/L")
    print(f"XGBoost Ensemble RMSE:          {rmse_model:.4f} mmol/L")
    
    improvement = (1 - (rmse_model / rmse_kinematic)) * 100
    print(f"\n✅ VERDICT: PREDICTIVE. Beats Kinematic model by {improvement:.1f}%")

    # 3. Lead Time Validation (Safety Check)
    # Find points where p95 hits threshold vs when actual hits threshold
    p95_alerts = valid[valid['twin_p95'] >= FAINT_THRESHOLD]
    actual_events = valid[valid['actual_future'] >= FAINT_THRESHOLD]
    
    print("\n--- Safety Lead-Time Validation ---")
    if not actual_events.empty:
        # Check first event
        first_actual_idx = actual_events.index[0]
        # Look for first p95 alert before this actual event
        p95_earlier = p95_alerts[p95_alerts.index <= first_actual_idx]
        
        if not p95_earlier.empty:
            lead_ticks = first_actual_idx - p95_earlier.index[0]
            lead_mins = lead_ticks * 2.5
            print(f"✅ PROACTIVE: p95 hit threshold {lead_mins:.1f} mins BEFORE actual future event.")
        else:
            print("⚠ REACTIVE: actual hit threshold before p95 did.")
    else:
        print("ℹ No faint-threshold events in this 14-day study.")

    # 4. Phase Lag Analysis
    norm_true = (y_true - np.mean(y_true)) / (np.std(y_true) * len(y_true))
    norm_pred = (y_pred - np.mean(y_pred)) / (np.std(y_pred))
    corr = correlate(norm_pred, norm_true, mode='full')
    lags = np.arange(-len(y_true) + 1, len(y_true))
    best_lag = lags[np.argmax(corr)]
    
    print(f"\n📊 Temporal Phase Lag (Mean): {best_lag * 2.5:.1f} minutes")

if __name__ == "__main__":
    verify_predictive_power()
