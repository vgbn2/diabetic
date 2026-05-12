import pandas as pd
from pathlib import Path

base_path = Path(r"C:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor\data\processed")
files = ['june_pixel_dense_v3.csv', 'feb_pixel_dense_v3.csv']

for f_name in files:
    f = base_path / f_name
    try:
        df = pd.read_csv(f)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        
        # Calculate Rate of Change (ROC)
        dt_mins = df['timestamp'].diff().dt.total_seconds() / 60.0
        dg = df['glucose'].diff().abs()
        roc = (dg / dt_mins).replace([float('inf'), float('-inf')], 0).fillna(0)
        
        print(f"\n--- {f_name} ---")
        print(f"Total Readings: {len(df)}")
        print(f"Duplicate Timestamps: {df['timestamp'].duplicated().sum()}")
        print(f"Max Rate of Change: {roc.max():.4f} mmol/L/min (Target < 0.4)")
        print(f"Glucose Range: {df['glucose'].min():.2f} to {df['glucose'].max():.2f} mmol/L")
    except Exception as e:
        print(f"Error validating {f_name}: {e}")
