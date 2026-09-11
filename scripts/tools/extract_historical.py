from pathlib import Path
from datetime import datetime
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from diabetic.ingestion.offline.normalize_ottai_share import normalize_share_report
from diabetic.ingestion.offline.high_res_parser import HighResGlucoseParser

def process_historical() -> int:
    data_dir = ROOT / "storage/raw/test/ottai_data"
    out_dir = ROOT / "storage/data/processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # (filename, output_csv, date_range)
    files = [
        ("OttaiShare_Report_2June-17June2025.pdf", "june02-june17-2025.csv",
         (datetime(2025, 6, 1), datetime(2025, 6, 18))),
        ("OttaiShare_Report_12Fed-27Fed2026.pdf", "feb12-feb27-2026.csv",
         (datetime(2026, 2, 11), datetime(2026, 2, 28))),
        ("OttaiShare_Report_23Mar-7Apr2026.pdf", "mar23-apr07-2026.csv",
         (datetime(2026, 3, 22), datetime(2026, 4, 8))),
    ]
    
    missing = [filename for filename, _, _ in files if not (data_dir / filename).is_file()]
    if missing:
        for filename in missing:
            print(f"Missing required input: {data_dir / filename}", file=sys.stderr)
        return 1

    for filename, out_name, date_range in files:
        target = data_dir / filename

        print(f"\n[batch] Processing {filename}...")
        
        # 1. Re-normalize (overwriting old _normalized version if it exists)
        norm_path = normalize_share_report(target)
        
        # 2. Parse
        parser = HighResGlucoseParser(norm_path)
        parser.parse()
        
        # 3. Save with date range filter
        final_out = out_dir / out_name
        parser.save_csv(final_out, date_range=date_range)
        print(f"[batch] Success! Saved to {final_out}")
    return 0

if __name__ == "__main__":
    raise SystemExit(process_historical())
