"""Verify local historical archives and CSV bundles without exposing records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from diabetic.ingestion.offline.historical import (  # noqa: E402
    verify_csv_directory,
    verify_nightscout_archive,
    write_csv_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--csv-dir", action="append", type=Path, default=[])
    parser.add_argument(
        "--write-manifest",
        action="store_true",
        help="Write or refresh manifest.json in each verified CSV directory.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.archive is None and not args.csv_dir:
        parser.error("provide --archive and/or --csv-dir")

    reports = []
    if args.archive is not None:
        reports.append(verify_nightscout_archive(args.archive))
    for directory in args.csv_dir:
        report = verify_csv_directory(directory)
        if args.write_manifest and report["ok"]:
            write_csv_manifest(directory, report)
            report = verify_csv_directory(directory)
        reports.append(report)

    payload = {"ok": all(report["ok"] for report in reports), "reports": reports}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for report in reports:
            status = "OK" if report["ok"] else "FAILED"
            print(f"{status}: {report['kind']} {report['root']}")
            for error in report["errors"]:
                print(f"  - {error}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
