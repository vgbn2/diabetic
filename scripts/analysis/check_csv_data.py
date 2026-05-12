import pandas as pd
from pathlib import Path

base_path = Path(r"C:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor\data\processed")
files = ['feb_pixel_dense_v2.csv', 'june_pixel_dense_v2.csv']

for f_name in files:
    f = base_path / f_name
    try:
        df = pd.read_csv(f)
        print(f"\n--- {f_name} ---")
        print(df[['timestamp', 'glucose']].head(10))
        print(f"Total Rows: {len(df)}")
        print(f"Null Glucose: {df['glucose'].isna().sum()}")
        print(f"Zero Glucose: {(df['glucose'] == 0).sum()}")
        print(f"Mean Glucose: {df['glucose'].mean()}")
    except Exception as e:
        print(f"Error reading {f_name}: {e}")
