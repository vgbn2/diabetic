import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

def generate_fidelity_report(
    backtest_path: str = "data/backtest_neural_overlay.csv",
    og_path: str = "storage/data/processed/mar23-apr07.csv"
):
    print(f"\n--- METABOLIC FIDELITY AUDIT ---")
    
    # 1. Load Data
    b_df = pd.read_csv(backtest_path)
    b_df['timestamp'] = pd.to_datetime(b_df['timestamp'])
    
    o_df = pd.read_csv(og_path)
    o_df['timestamp'] = pd.to_datetime(o_df['timestamp']).dt.round('5min')

    # 2. Alignment & Comparison
    # o_df has the raw points (with GAPs/NaNs). 
    # b_df has interpolated baseline AND neural predictions.
    
    # Standardize time for merging
    b_df['timestamp'] = b_df['timestamp'].dt.tz_localize(None)
    o_df['timestamp'] = o_df['timestamp'].dt.tz_localize(None)
    
    # We want to compare actual RAW values to the AI prediction produced for that time
    comparison = o_df.dropna(subset=['glucose']).merge(
        b_df[['timestamp', 'glucose_neural']], 
        on='timestamp', 
        how='inner'
    ).dropna(subset=['glucose_neural'])
    
    if comparison.empty:
        print("ERROR: No aligned data points found for comparison.")
        return

    # 3. Metrics
    rmse = np.sqrt(np.mean((comparison['glucose'] - comparison['glucose_neural'])**2))
    mae = np.mean(np.abs(comparison['glucose'] - comparison['glucose_neural']))
    
    print(f"Sample Size: {len(comparison)} points")
    print(f"RMSE: {rmse:.3f} mmol/L")
    print(f"MAE: {mae:.3f} mmol/L")
    
    # 4. Side-by-Side Verification Plot
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10), sharex=True)
    
    # Plot OG Data Points (Scatter)
    ax1.scatter(o_df['timestamp'], o_df['glucose'], color='#2d3436', s=5, alpha=0.4, label='OG Raw Data (CGM)')
    ax1.set_title("Original Historical Ground Truth (Raw CGM Points)", fontsize=14)
    ax1.legend()
    ax1.grid(True, alpha=0.2)
    
    # Plot Neural Backtest (Continuos)
    ax2.plot(b_df['timestamp'], b_df['glucose'], color='#0984e3', linewidth=1.5, alpha=0.9, label='Inferred Baseline')
    ax2.plot(b_df['timestamp'], b_df['glucose_neural'], color='#6c5ce7', linewidth=2.0, linestyle='--', label='AI Strategy (H+30m)')
    ax2.set_title("Neural Backtest Inference (Personalized AI Overlay)", fontsize=14)
    ax2.legend()
    ax2.grid(True, alpha=0.2)
    
    save_path = "data/plots/og_vs_neural_comparison.png"
    plt.tight_layout()
    plt.savefig(save_path)
    print(f"Fidelity Dashboard Saved: {save_path}")

if __name__ == "__main__":
    generate_fidelity_report()
