"""Export or stage a bounded Nightscout MongoDB migration.

Secrets are read from environment variables and are never printed. Export
files use MongoDB Extended JSON so ObjectIds and BSON dates round-trip.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bson import json_util
from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne

from diabetic.ingestion.offline.historical import (
    NIGHTSCOUT_EXCLUDED_COLLECTIONS,
    NIGHTSCOUT_REFERENCE_COLLECTIONS,
    NIGHTSCOUT_WINDOWED_COLLECTIONS,
    verify_nightscout_archive,
)
from diabetic.ingestion.timestamps import treatment_timestamp


def _database(uri: str):
    client = MongoClient(uri, serverSelectionTimeoutMS=10_000)
    client.admin.command("ping")
    name = uri.rsplit("/", 1)[-1].split("?", 1)[0] or "nightscout"
    return client, client[name]


def _timestamp(document: dict) -> datetime | None:
    if isinstance(document.get("date"), (int, float)):
        return datetime.fromtimestamp(document["date"] / 1000, timezone.utc)
    return treatment_timestamp(document)


def _iter_documents(collection, cutoff: datetime | None):
    query = {}
    if cutoff is not None and collection.name == "entries":
        query = {"date": {"$gte": int(cutoff.timestamp() * 1000)}}
    for document in collection.find(query):
        if cutoff is None or collection.name == "entries":
            yield document
            continue
        timestamp = _timestamp(document)
        if timestamp is not None and timestamp >= cutoff:
            yield document


def export_database(uri: str, destination: Path, cutoff: datetime) -> dict:
    client, database = _database(uri)
    partial = destination.with_name(destination.name + ".partial")
    if destination.exists() or partial.exists():
        client.close()
        raise FileExistsError(f"destination or partial export already exists: {destination}")
    partial.mkdir(parents=True)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cutoff": cutoff.isoformat(),
        "database": database.name,
        "collections": {},
        "excluded": list(NIGHTSCOUT_EXCLUDED_COLLECTIONS),
    }
    try:
        existing = set(database.list_collection_names())
        for name in (
            *NIGHTSCOUT_WINDOWED_COLLECTIONS,
            *NIGHTSCOUT_REFERENCE_COLLECTIONS,
        ):
            if name not in existing:
                continue
            output = partial / f"{name}.jsonl"
            digest = hashlib.sha256()
            count = 0
            with output.open("wb") as stream:
                collection_cutoff = (
                    cutoff if name in NIGHTSCOUT_WINDOWED_COLLECTIONS else None
                )
                for document in _iter_documents(database[name], collection_cutoff):
                    line = json_util.dumps(document, json_options=json_util.CANONICAL_JSON_OPTIONS)
                    encoded = (line + "\n").encode()
                    stream.write(encoded)
                    digest.update(encoded)
                    count += 1
            manifest["collections"][name] = {
                "count": count,
                "sha256": digest.hexdigest(),
            }
    finally:
        client.close()
    manifest_path = partial / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    partial.rename(destination)
    return manifest


def stage_restore(uri: str, source: Path) -> dict:
    integrity = verify_nightscout_archive(source)
    if not integrity["ok"]:
        raise RuntimeError(
            "source archive failed integrity verification: "
            + "; ".join(integrity["errors"])
        )
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    client, target = _database(uri)
    staging_name = f"{target.name}_staging_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    staging = client[staging_name]
    verified = {}
    try:
        for name, expected in manifest["collections"].items():
            operations = []
            with (source / f"{name}.jsonl").open(encoding="utf-8") as stream:
                for line in stream:
                    document = json_util.loads(line)
                    operations.append(ReplaceOne({"_id": document["_id"]}, document, upsert=True))
                    if len(operations) >= 500:
                        staging[name].bulk_write(operations, ordered=False)
                        operations.clear()
                if operations:
                    staging[name].bulk_write(operations, ordered=False)
            actual = staging[name].count_documents({})
            if actual != expected["count"]:
                raise RuntimeError(f"{name}: expected {expected['count']} rows, staged {actual}")
            verified[name] = actual
    finally:
        client.close()
    return {"status": "staged", "database": staging_name, "counts": verified}


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export")
    export.add_argument("--destination", type=Path, required=True)
    export.add_argument("--days", type=int, default=60)
    export.add_argument("--since", help="UTC date, e.g. 2026-06-01")
    restore = subparsers.add_parser("stage-restore")
    restore.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "export":
        uri = (
            os.environ.get("SOURCE_MONGODB_URI")
            or os.environ.get("MONGODB_URI")
            or os.environ.get("MONGO_URI")
        )
        if not uri:
            raise SystemExit("SOURCE_MONGODB_URI is required")
        cutoff = (
            datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
            if args.since
            else datetime.now(timezone.utc) - timedelta(days=args.days)
        )
        result = export_database(uri, args.destination, cutoff)
        print(json.dumps({"status": "exported", **result}, indent=2))
    else:
        uri = os.environ.get("TARGET_MONGODB_URI")
        if not uri:
            raise SystemExit("TARGET_MONGODB_URI is required")
        result = stage_restore(uri, args.source)
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
