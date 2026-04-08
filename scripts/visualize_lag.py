import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

def plot_lag_diagnostic():
    path = Path("offline/ingestion/ottai_data/processed/synthetic_glucose_machine_learned.csv")
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # We want to see how predicted_30m aligns with the ACTUAL glucose 30m later
    # Shift actual glucose BACK by 30 mins so we can compare same-row
    df['actual_outcome'] = df['glucose'].shift(-12)
    
    plt.figure(figsize=(15, 7))
    # Plot only 1 day for clarity
    subset = df.iloc[500:1000]
    
    plt.plot(subset['timestamp'], subset['actual_outcome'], label="Actual Outcome (T+30m)", color='blue', linewidth=2)
    plt.plot(subset['timestamp'], subset['predicted_30m'], label="XGBoost Prediction", color='red', linestyle='--')
    plt.plot(subset['timestamp'], subset['glucose'], label="Current Glucose (Now)", color='green', alpha=0.3)
    
    plt.title("Phase Lag Diagnostic: Prediction vs Outcome vs Now")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plt.savefig("offline/ingestion/ottai_data/processed/lag_diagnostic.png")
    print("🖼️ Saved lag diagnostic to offline/ingestion/ottai_data/processed/lag_diagnostic.png")

if __name__ == "__main__":
    plot_lag_diagnostic()
