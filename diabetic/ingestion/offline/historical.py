"""Verification and replay helpers for local historical clinical data.

Real patient archives remain ignored and local.  This module emits aggregate
metadata only; callers must never log raw records or identifiers.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from bson import json_util

from diabetic import medical_constants
from diabetic.config import config
from diabetic.ingestion.normalization import normalize_nightscout_sgv
from diabetic.registry import GlucoseReading


class HistoricalDataError(ValueError):
    """Raised when historical data fails an integrity or schema contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_iso_timestamp(
    raw: object, *, require_timezone: bool = True
) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise HistoricalDataError("timestamp must be a non-empty ISO string")
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HistoricalDataError("timestamp is not valid ISO-8601") from exc
    if parsed.tzinfo is None and require_timezone:
        raise HistoricalDataError("timestamp must include a timezone")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _entry_timestamp(document: dict) -> datetime:
    raw_date = document.get("date")
    if isinstance(raw_date, (int, float)) and math.isfinite(float(raw_date)):
        return datetime.fromtimestamp(float(raw_date) / 1000.0, timezone.utc)
    return _parse_iso_timestamp(document.get("dateString"))


def _reading_value(mmol_value: float) -> tuple[float, str]:
    if config.PREFER_MMOL:
        return mmol_value, "mmol/L"
    return mmol_value * medical_constants.MMOL_TO_MGDL, "mg/dL"


def verify_nightscout_archive(root: str | Path) -> dict:
    """Verify a Nightscout Extended-JSON export without exposing its records."""

    archive = Path(root)
    manifest_path = archive / "manifest.json"
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "kind": "nightscout_archive",
            "ok": False,
            "root": str(archive),
            "errors": [f"manifest: {exc.__class__.__name__}"],
            "collections": {},
        }

    collections = manifest.get("collections")
    if not isinstance(collections, dict) or not collections:
        return {
            "kind": "nightscout_archive",
            "ok": False,
            "root": str(archive),
            "errors": ["manifest collections must be a non-empty object"],
            "collections": {},
        }

    reports: dict[str, dict] = {}
    for name, expected in sorted(collections.items()):
        path = archive / f"{name}.jsonl"
        report = {
            "count": 0,
            "expected_count": expected.get("count"),
            "sha256": None,
            "expected_sha256": expected.get("sha256"),
            "hash_ok": False,
            "parse_errors": 0,
            "duplicate_records": 0,
            "duplicate_timestamps": 0,
            "timestamps_monotonic": True,
            "first_timestamp": None,
            "last_timestamp": None,
        }
        reports[name] = report
        if not path.is_file():
            errors.append(f"{name}: missing JSONL file")
            continue

        report["sha256"] = sha256_file(path)
        report["hash_ok"] = report["sha256"] == report["expected_sha256"]
        if not report["hash_ok"]:
            errors.append(f"{name}: sha256 mismatch")

        identities: set[str] = set()
        timestamps: set[datetime] = set()
        previous_timestamp: datetime | None = None
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                report["count"] += 1
                try:
                    document = json_util.loads(line)
                    if not isinstance(document, dict):
                        raise HistoricalDataError("record must be an object")
                except (ValueError, TypeError, HistoricalDataError):
                    report["parse_errors"] += 1
                    errors.append(f"{name}: invalid record at line {line_number}")
                    continue

                identity = str(document.get("_id", ""))
                if identity:
                    if identity in identities:
                        report["duplicate_records"] += 1
                    identities.add(identity)

                if name == "entries":
                    try:
                        timestamp = _entry_timestamp(document)
                    except HistoricalDataError:
                        report["parse_errors"] += 1
                        errors.append(
                            f"{name}: invalid timestamp at line {line_number}"
                        )
                        continue
                    if timestamp in timestamps:
                        report["duplicate_timestamps"] += 1
                    timestamps.add(timestamp)
                    if previous_timestamp is not None and timestamp < previous_timestamp:
                        report["timestamps_monotonic"] = False
                    previous_timestamp = timestamp
                    report["first_timestamp"] = (
                        report["first_timestamp"] or timestamp.isoformat()
                    )
                    report["last_timestamp"] = timestamp.isoformat()

        if report["count"] != report["expected_count"]:
            errors.append(
                f"{name}: expected {report['expected_count']} records, "
                f"found {report['count']}"
            )
        if report["duplicate_records"]:
            errors.append(f"{name}: duplicate record identities")
        if name == "entries" and not report["timestamps_monotonic"]:
            errors.append("entries: timestamps are not monotonic")

    return {
        "kind": "nightscout_archive",
        "ok": not errors,
        "root": str(archive),
        "manifest_sha256": sha256_file(manifest_path),
        "cutoff": manifest.get("cutoff"),
        "database": manifest.get("database"),
        "collections": reports,
        "errors": errors,
    }


def _csv_role(path: Path, fieldnames: Sequence[str]) -> str:
    fields = set(fieldnames)
    if path.name == "consolidated_training.csv":
        return "derived_mixed_schema_unsafe"
    if {"timestamp_utc", "glucose_mmol_l", "trend", "source"} <= fields:
        if path.parent.name == "test_audit":
            return "manual_mongo_export"
        return "operational_mongo_export"
    if {"timestamp", "glucose"} <= fields:
        return "pdf_derived"
    return "unknown"


def _profile_csv(path: Path) -> tuple[dict, set[tuple[str, str, str]]]:
    digest = sha256_file(path)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames or []
        role = _csv_role(path, fieldnames)
        count = 0
        parse_errors = 0
        duplicate_records = 0
        previous_timestamp: datetime | None = None
        first_timestamp: str | None = None
        last_timestamp: str | None = None
        keys: set[tuple[str, str, str]] = set()
        for row in reader:
            count += 1
            if role == "derived_mixed_schema_unsafe":
                continue
            if role in {"manual_mongo_export", "operational_mongo_export"}:
                timestamp_key = "timestamp_utc"
                glucose_key = "glucose_mmol_l"
            elif role == "pdf_derived":
                timestamp_key = "timestamp"
                glucose_key = "glucose"
            else:
                parse_errors += 1
                continue
            try:
                timestamp = _parse_iso_timestamp(
                    row.get(timestamp_key),
                    require_timezone=role != "pdf_derived",
                )
                glucose = float(row.get(glucose_key, ""))
                if not math.isfinite(glucose) or glucose <= 0:
                    raise HistoricalDataError("glucose must be finite and positive")
            except (ValueError, TypeError, HistoricalDataError):
                parse_errors += 1
                continue
            key = (role, timestamp.isoformat(), f"{glucose:.8f}")
            if key in keys:
                duplicate_records += 1
            keys.add(key)
            if previous_timestamp is not None and timestamp < previous_timestamp:
                parse_errors += 1
            previous_timestamp = timestamp
            first_timestamp = first_timestamp or timestamp.isoformat()
            last_timestamp = timestamp.isoformat()

    report = {
        "name": path.name,
        "role": role,
        "sha256": digest,
        "rows": count,
        "schema": fieldnames,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "timestamp_basis": (
            "naive_local" if role == "pdf_derived" else "explicit_timezone"
        ),
        "parse_errors": parse_errors,
        "duplicate_records": duplicate_records,
        "training_safe": False,
    }
    return report, keys


def verify_csv_directory(root: str | Path) -> dict:
    """Profile a retained CSV bundle and verify an existing local manifest."""

    directory = Path(root)
    errors: list[str] = []
    reports: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    overlap_records = 0
    for path in sorted(directory.glob("*.csv")):
        report, keys = _profile_csv(path)
        reports.append(report)
        overlap_records += len(seen & keys)
        seen.update(keys)
        if report["role"] == "unknown":
            errors.append(f"{path.name}: unsupported schema")
        if report["parse_errors"] and report["role"] in {
            "manual_mongo_export",
            "operational_mongo_export",
        }:
            errors.append(f"{path.name}: {report['parse_errors']} invalid rows")
        if report["duplicate_records"] and report["role"] in {
            "manual_mongo_export",
            "operational_mongo_export",
        }:
            errors.append(
                f"{path.name}: {report['duplicate_records']} duplicate rows"
            )

    if not reports:
        errors.append("no CSV files found")

    manifest_path = directory / "manifest.json"
    manifest_ok: bool | None = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = {
                item["name"]: (item["sha256"], item["rows"], item["role"])
                for item in manifest.get("files", [])
            }
            actual = {
                item["name"]: (item["sha256"], item["rows"], item["role"])
                for item in reports
            }
            manifest_ok = actual == expected
        except (OSError, ValueError, KeyError, TypeError):
            manifest_ok = False
        if not manifest_ok:
            errors.append("CSV manifest does not match current files")

    return {
        "kind": "csv_bundle",
        "ok": not errors,
        "root": str(directory),
        "files": reports,
        "unique_records": len(seen),
        "overlap_records": overlap_records,
        "overlap_policy": (
            "approved_manual_validation_evidence"
            if directory.name == "test_audit"
            else "disallowed"
        ),
        "manifest_present": manifest_path.exists(),
        "manifest_ok": manifest_ok,
        "errors": errors,
    }


def write_csv_manifest(root: str | Path, report: dict) -> Path:
    """Write aggregate provenance metadata beside an ignored local CSV bundle."""

    if report.get("kind") != "csv_bundle" or not report.get("ok"):
        raise HistoricalDataError("cannot manifest an invalid CSV bundle")
    destination = Path(root) / "manifest.json"
    payload = {
        "schema_version": 1,
        "purpose": (
            "manual_mongodb_extraction_validation"
            if Path(root).name == "test_audit"
            else "operational_mongodb_csv_chapters"
        ),
        "privacy": "local_ignored_clinical_data",
        "overlap_policy": report["overlap_policy"],
        "files": report["files"],
    }
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


@dataclass(frozen=True)
class HistoricalReplayReader:
    """Strict replay reader for verified archives or canonical CSV chapters."""

    archive: Path | None = None
    csv_paths: tuple[Path, ...] = ()

    @classmethod
    def from_archive(cls, root: str | Path) -> "HistoricalReplayReader":
        report = verify_nightscout_archive(root)
        if not report["ok"]:
            raise HistoricalDataError("; ".join(report["errors"]))
        return cls(archive=Path(root))

    @classmethod
    def from_csvs(
        cls, paths: Sequence[str | Path]
    ) -> "HistoricalReplayReader":
        resolved = tuple(Path(path) for path in paths)
        if not resolved:
            raise HistoricalDataError("at least one CSV path is required")
        for path in resolved:
            report, _ = _profile_csv(path)
            if report["role"] not in {
                "operational_mongo_export",
                "manual_mongo_export",
            }:
                raise HistoricalDataError(
                    f"{path.name}: CSV is not a canonical Mongo export"
                )
            if report["parse_errors"] or report["duplicate_records"]:
                raise HistoricalDataError(f"{path.name}: CSV failed validation")
        return cls(csv_paths=resolved)

    def stream(self) -> Iterator[GlucoseReading]:
        if self.archive is not None:
            yield from self._stream_archive()
            return
        yield from self._stream_csvs()

    def _stream_archive(self) -> Iterator[GlucoseReading]:
        assert self.archive is not None
        with (self.archive / "entries.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                document = json_util.loads(line)
                mmol_value = normalize_nightscout_sgv(
                    document.get("sgv"), document.get("units")
                )
                value, unit = _reading_value(mmol_value)
                yield GlucoseReading(
                    timestamp=_entry_timestamp(document),
                    value=value,
                    trend=document.get("direction", "Flat"),
                    source="historical_archive",
                    unit=unit,
                )

    def _stream_csvs(self) -> Iterator[GlucoseReading]:
        readings: list[GlucoseReading] = []
        for path in self.csv_paths:
            with path.open(newline="", encoding="utf-8-sig") as stream:
                for row in csv.DictReader(stream):
                    mmol_value = float(row["glucose_mmol_l"])
                    if not math.isfinite(mmol_value) or mmol_value <= 0:
                        raise HistoricalDataError(
                            f"{path.name}: glucose must be finite and positive"
                        )
                    value, unit = _reading_value(mmol_value)
                    readings.append(
                        GlucoseReading(
                            timestamp=_parse_iso_timestamp(row["timestamp_utc"]),
                            value=value,
                            trend=row.get("trend") or "Flat",
                            source="historical_csv",
                            unit=unit,
                        )
                    )
        readings.sort(key=lambda reading: reading.timestamp)
        for reading in readings:
            yield reading
