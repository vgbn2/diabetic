"""
scripts/utils/transform_bson_history.py

BSON Forensic Transformer — converts historical MongoDB clinical exports
into the unified "Big JSON" (MetabolicSnapshot) format for CNN retraining.

Usage:
    python scripts/utils/transform_bson_history.py --input path/to/dump.bson [--output path/to/out/]
    python scripts/utils/transform_bson_history.py --demo   (test with mock data)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("bio-quant.bson-transformer")


# --------------------------------------------------------------------------- #
# Import guard — bson (pymongo) is optional; script is standalone.
# --------------------------------------------------------------------------- #
try:
    import bson
    _BSON_AVAILABLE = True
except ImportError:
    _BSON_AVAILABLE = False
    logger.warning("'bson' package not found. Use: pip install pymongo. Only --demo mode available.")


# --------------------------------------------------------------------------- #
# Transform helpers
# --------------------------------------------------------------------------- #

def _normalize_ts(raw: Any) -> str:
    """Coerce MongoDB timestamps to ISO-8601 UTC strings."""
    if isinstance(raw, datetime):
        dt = raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if isinstance(raw, str):
        return raw
    return datetime.now(timezone.utc).isoformat()


def bson_record_to_snapshot(record: dict) -> dict:
    """
    Convert a single Nightscout / Bio-Quant BSON document into the
    MetabolicSnapshot-compatible JSON structure.

    Field mapping:
      - sgv (mg/dL)  → glucose.value (mmol/L, / 18.0)
      - direction    → glucose.trend
      - date         → glucose.timestamp
      - insulin      → last_insulin.units
      - carbs        → last_meal.carbs
    """
    # Glucose
    sgv_raw = record.get("sgv") or record.get("glucose", 0)
    glucose_mmol = round(float(sgv_raw) / 18.0, 2)
    trend = record.get("direction") or record.get("trend", "Flat")
    ts = _normalize_ts(record.get("date") or record.get("timestamp") or record.get("dateString"))

    snap: dict[str, Any] = {
        "glucose": {
            "timestamp": ts,
            "value": glucose_mmol,
            "trend": trend,
            "source": "bson_history",
            "unit": "mmol/L",
        },
        "predict_15m": 0.0,
        "predict_30m": 0.0,
        "predict_60m": 0.0,
        "confidence_index": 0.0,
        "velocity_score": 0.0,
        "sensor_health": 1.0,
        "activity_label": "UNKNOWN",
        # Legacy treatment fields
        "last_insulin": None,
        "last_meal": None,
    }

    # Insulin dose
    if "insulin" in record and record["insulin"] is not None:
        snap["last_insulin"] = {
            "timestamp": ts,
            "units": float(record["insulin"]),
            "type": record.get("insulinType", "rapid-acting"),
        }

    # Carbs / meal
    if "carbs" in record and record["carbs"] is not None:
        snap["last_meal"] = {
            "timestamp": ts,
            "carbs": float(record["carbs"]),
            "gi_type": record.get("foodType", "STARCH"),
        }

    return snap


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def transform_file(bson_path: Path, output_dir: Path) -> int:
    """Load BSON dump, transform all records, write NDJSON output."""
    if not _BSON_AVAILABLE:
        logger.error("bson not installed. Run: pip install pymongo")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{bson_path.stem}_snapshots.ndjson"

    count = 0
    with open(bson_path, "rb") as f_in, open(out_path, "w", encoding="utf-8") as f_out:
        for raw in bson.decode_file_iter(f_in):
            snap = bson_record_to_snapshot(raw)
            f_out.write(json.dumps(snap) + "\n")
            count += 1

    logger.info("Transformed %d records → %s", count, out_path)
    return 0


def demo() -> None:
    """Run transformer on synthetic records and print output."""
    mock_records = [
        {"sgv": 180, "direction": "FortyFiveUp", "date": datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc), "carbs": 40},
        {"sgv": 126, "direction": "Flat",         "date": datetime(2024, 1, 1, 7, 0, tzinfo=timezone.utc), "insulin": 2.5},
        {"sgv":  90, "direction": "FortyFiveDown","date": datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)},
    ]
    print("[DEMO] Transforming 3 mock BSON records:")
    for rec in mock_records:
        snap = bson_record_to_snapshot(rec)
        print(json.dumps(snap, indent=2))


# --------------------------------------------------------------------------- #
# CLI entry
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="Bio-Quant BSON History Transformer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path, help="Path to .bson dump file")
    group.add_argument("--demo",  action="store_true", help="Run with synthetic data")
    parser.add_argument("--output", type=Path, default=Path("storage/audit/history"),
                        help="Output directory for NDJSON files (default: storage/audit/history)")
    args = parser.parse_args()

    if args.demo:
        demo()
        return 0

    return transform_file(args.input, args.output)


if __name__ == "__main__":
    sys.exit(main())
