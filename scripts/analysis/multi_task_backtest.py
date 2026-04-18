import torch
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime, timezone
from diabetic.ml_engine.inference import MetabolicInferenceRunner

def run_multi_task_backtest(
    csv_path: str = "storage/data/processed/mar23-apr07.csv",
    output_plot: str = "data/plots/multi_task_backtest_dashboard.png"
):
    print(f"\n--- MULTI-TASK NEURAL BACKTEST ---")
    
    # 1. Load Data
    raw_df = pd.read_csv(csv_path)
    raw_df['timestamp'] = pd.to_datetime(raw_df['timestamp'])
    
    # Preprocess slightly for inference (same as dataset)
    df_clean = raw_df.set_index('timestamp').select_dtypes(include=[np.number]).resample('5min').mean()
    df_clean['glucose'] = df_clean['glucose'].interpolate(method='linear')
    df_clean = df_clean.dropna(subset=['glucose'])
    
    # Re-synthesize Heart Rate for comparison (since it wasn't in raw CSV)
    from diabetic.ml_engine.synthetic_cardiac import cardiac_synthesizer
    from diabetic.registry import GlucoseReading
    
    hrs = []
    for i in range(len(df_clean)):
        g_val = df_clean.iloc[i]['glucose']
        vel = 0 if i == 0 else g_val - df_clean.iloc[i-1]['glucose']
        reading = GlucoseReading(timestamp=df_clean.index[i], value=g_val, trend="NONE")
        cardiac = cardiac_synthesizer.estimate(reading, velocity=vel)
        hrs.append(cardiac.bpm)
    df_clean['heart_rate'] = hrs
    
    # 2. Setup Inference
    runner = MetabolicInferenceRunner()
    
    g_preds = []
    hr_preds = []
    times = []
    
    pred_offset = 6 # 30 mins
    
    print(f"Executing Multi-Task Inference across {len(df_clean)} points...")
    for i in range(len(df_clean) - 30 - pred_offset):
        window = df_clean.iloc[i : i+30][['glucose', 'heart_rate']]
        
        try:
            state = runner.run_inference_on_window(window, df_clean.index[i+30])
            
            target_time = df_clean.index[i+30+pred_offset-1]
            times.append(target_time)
            g_preds.append(state['glucose'])
            hr_preds.append(state['heart_rate'])
        except Exception:
            continue

    # 3. Visualization
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 12), sharex=True)
    
    # Plot 1: Glucose (Actual vs Predicted)
    ax1.plot(df_clean.index, df_clean['glucose'], color='#0984e3', alpha=0.4, label='Actual Glucose (Historical)')
    ax1.plot(times, g_preds, color='#6c5ce7', linestyle='--', label='Neural Glucose Prediction')
    ax1.set_title("Multi-Task Prediction: Glucose Strategy", fontsize=14)
    ax1.set_ylabel("mmol/L")
    ax1.legend()
    ax1.grid(True, alpha=0.2)
    
    # Plot 2: Heart Rate (Actual vs Predicted)
    # Note: 'Actual' HR here is our synthetic estimate in the CSV
    ax2.plot(df_clean.index, df_clean['heart_rate'], color='#d63031', alpha=0.4, label='Estimated HR (Original)')
    ax2.plot(times, hr_preds, color='#fdcb6e', linestyle='--', label='Neural Heart Rate Prediction')
    ax2.set_title("Multi-Task Prediction: Cardiac State Estimation", fontsize=14)
    ax2.set_ylabel("BPM")
    ax2.legend()
    ax2.grid(True, alpha=0.2)
    
    Path("data/plots").mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_plot)
    print(f"SUCCESS: Multi-Task Dashboard Saved to {output_plot}")

if __name__ == "__main__":
    run_multi_task_backtest()
