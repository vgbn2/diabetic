import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parents[2]))

from diabetic.ingestion.offline.plot_glucose import plot_glucose_data

def plot_all():
    processed_dir = Path("storage/data/processed")
    viz_dir = Path("artifacts/viz")
    viz_dir.mkdir(parents=True, exist_ok=True)
    
    files = [
        ("june02-june17-2025.csv", "june_2025_recovered.png"),
        ("feb12-feb27-2026.csv", "feb_2026_recovered.png"),
        ("mar23-apr07-2026.csv", "mar23_apr07_2026_recovered.png")
    ]
    
    for csv_name, out_name in files:
        csv_path = processed_dir / csv_name
        if not csv_path.exists():
            print(f"Skipping {csv_name}: File not found.")
            continue
            
        out_path = Path(f"c:\\Users\\Lenovo\\.gemini\\antigravity\\brain\\9bd93ee4-bde3-4bf4-b678-51d332fc2c3f\\{out_name}")
        print(f"\n[plot] Plotting {csv_name} -> {out_name}...")
        
        try:
            plot_glucose_data(str(csv_path), str(out_path))
            print(f"  Success!")
        except Exception as e:
            print(f"  Error plotting {csv_name}: {e}")

if __name__ == "__main__":
    plot_all()
