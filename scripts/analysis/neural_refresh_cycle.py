import pandas as pd
import glob
import os
import sys
from pathlib import Path

# -- Path Resolution --
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from diabetic.ml_engine.train import train_metabolic_cnn

def execute_neural_refresh():
    print("\n  NEURAL REFRESH ORCHESTRATOR")
    print("  " + "=" * 50)
    
    # 1. Consolidate Data
    export_dir = "storage/exports/test_audit"
    csv_pattern = os.path.join(export_dir, "*.csv")
    csv_files = glob.glob(csv_pattern)
    
    if not csv_files:
        print(f"  [X] FAILED: No CSV data found in {export_dir}")
        sys.exit(1)
        
    print(f"  [1] Merging {len(csv_files)} files from {export_dir}...")
    dfs = []
    for f in csv_files:
        # Ignore previously consolidated files to avoid recursion
        if "consolidated_training.csv" in f: continue
        try:
            df = pd.read_csv(f)
            dfs.append(df)
        except Exception as e:
            print(f"  [!] Warning: Could not read {f}: {e}")

    if not dfs:
        print("  [X] FAILED: No valid data frames to merge.")
        sys.exit(1)
        
    final_df = pd.concat(dfs).drop_duplicates().sort_values("timestamp_utc" if "timestamp_utc" in dfs[0].columns else "timestamp")
    target_csv = os.path.join(export_dir, "consolidated_training.csv")
    final_df.to_csv(target_csv, index=False)
    print(f"  [OK] Consolidated Data: {target_csv} ({len(final_df)} samples)")

    # 2. Train CNN
    print("\n  [2] Starting CNN Training...")
    # Using 10 epochs for faster execution in this turn, usually 50 in production
    train_metabolic_cnn(csv_path=target_csv, epochs=15)
    print("  [OK] Training Complete.")

    # 3. Trigger Simulation
    print("\n  [3] Triggering 5-Day Forecast...")
    from scripts.simulation.future_next5day_sim import run_future_5day_simulation
    run_future_5day_simulation()
    
    print("\n  [DONE] Neural Refresh Cycle Complete.\n")

if __name__ == "__main__":
    execute_neural_refresh()
