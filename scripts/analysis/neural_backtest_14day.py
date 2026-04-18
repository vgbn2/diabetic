import torch
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from diabetic.ml_engine.convolutional_layer import DiabeticCNN, CNNConfig
from diabetic.ml_engine.metabolic_dataset import MetabolicDataset
from diabetic.ml_engine.inference import MetabolicInferenceRunner

def run_historical_backtest(
    csv_path: str = "storage/data/processed/mar23-apr07.csv",
    weights_path: str = "diabetic/ml_engine/weights/diabetic_cnn.pth",
    output_path: str = "data/backtest_neural_overlay.csv"
):
    print(f"\n--- NEURAL BACKTEST INITIATED: {csv_path} ---")
    
    # 1. Load the underlying dataset to get pre-processed history
    # We use MetabolicDataset because it already handles Interpolation and HR synthesis
    dataset = MetabolicDataset(csv_path)
    df_clean = dataset.data.copy()
    
    # 2. Setup Inference Runner
    runner = MetabolicInferenceRunner(seq_len=30)
    # Weights are already synced in train.py to this path
    
    predictions = []
    # We loop through the data in windows
    # Note: MetabolicDataset.X contains windows [0:30], [1:31] etc.
    # Prediction target was (i + 30 + 6). 
    # So for window [i:i+30], the prediction is for timestamp [i+35] (5-tick offset)
    
    print(f"Running inference across {len(df_clean)} historical data points...")
    
    # Initialize neural column as float to avoid object-type NaN issues
    df_clean['glucose_neural'] = np.nan
    df_clean['glucose_neural'] = df_clean['glucose_neural'].astype(float)
    
    pred_offset = 6 
    
    count = 0
    for i in range(len(df_clean) - 30 - pred_offset):
        window_slice = df_clean.iloc[i : i+30][['glucose', 'heart_rate']]
        
        try:
            pred_val = runner.run_inference_on_window(window_slice, df_clean.index[i+30])
            
            # Use .iloc with integer positions to be absolutely sure
            target_pos = i + 30 + pred_offset - 1
            df_clean.iloc[target_pos, df_clean.columns.get_loc('glucose_neural')] = float(pred_val)
            
            count += 1
            if count % 500 == 0:
                print(f"  Processed {count} windows... Last Pred: {pred_val:.2f}")
        except Exception as e:
            continue
    
    print(f"Total successful inferences: {count}")

    # 3. Save Results
    results = df_clean.reset_index()
    results.rename(columns={'timestamp': 'timestamp'}, inplace=True)
    
    # Reload and align raw descriptors (bolus, meal, etc)
    raw_df = pd.read_csv(csv_path)
    raw_df['timestamp'] = pd.to_datetime(raw_df['timestamp']).dt.round('5min')
    
    # Sum activities sharing the same 5min bin
    raw_summary = raw_df.groupby('timestamp')[['bolus', 'basal', 'meal']].sum().reset_index()
    
    final_df = results.merge(raw_summary, on='timestamp', how='left')
    
    # Ensure 0s for plots
    for col in ['bolus', 'basal', 'meal']:
        if col in final_df.columns:
            final_df[col] = final_df[col].fillna(0)
        else:
            final_df[col] = 0

    Path("data").mkdir(parents=True, exist_ok=True)
    final_df.to_csv(output_path, index=False)
    print(f"SUCCESS: Backtest CSV generated at {output_path}")
    print(f"Range: {final_df['glucose'].min():.1f} - {final_df['glucose'].max():.1f}")
    
if __name__ == "__main__":
    run_historical_backtest()
