#!/usr/bin/env bash
set -euo pipefail

backup_dir="${1:-storage/backups}"
retention_days="${BACKUP_RETENTION_DAYS:-30}"
if [[ ! "$retention_days" =~ ^[0-9]+$ ]]; then
  printf 'BACKUP_RETENTION_DAYS must be a non-negative integer.\n' >&2
  exit 2
fi

mkdir -p "$backup_dir"
umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$backup_dir/nightscout-$stamp.archive.gz"
checksum="$archive.sha256"
metadata="$archive.json"

if [[ -e "$archive" || -e "$checksum" || -e "$metadata" ]]; then
  printf 'Backup destination already exists for timestamp %s.\n' "$stamp" >&2
  exit 1
fi

temporary_archive="$(mktemp "$backup_dir/.nightscout-$stamp.XXXXXX.archive.gz")"
temporary_checksum="$(mktemp "$backup_dir/.nightscout-$stamp.XXXXXX.sha256")"
temporary_metadata="$(mktemp "$backup_dir/.nightscout-$stamp.XXXXXX.json")"
validation_log="$(mktemp "$backup_dir/.nightscout-$stamp.XXXXXX.validate")"

cleanup() {
  rm -f -- \
    "$temporary_archive" \
    "$temporary_checksum" \
    "$temporary_metadata" \
    "$validation_log"
  if [[ ! -f "$archive" ]]; then
    rm -f -- "$checksum" "$metadata"
  fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

docker compose exec -T mongodb mongodump \
  --db nightscout \
  --archive \
  --gzip > "$temporary_archive"

if [[ ! -s "$temporary_archive" ]]; then
  printf 'Backup validation failed: mongodump produced an empty archive.\n' >&2
  exit 1
fi

if ! docker compose exec -T mongodb mongorestore \
  --archive \
  --gzip \
  --dryRun \
  --nsInclude 'nightscout.*' \
  < "$temporary_archive" > "$validation_log" 2>&1; then
  printf 'Backup validation failed: archive dry-run was rejected.\n' >&2
  exit 1
fi

if ! grep -Eq 'nightscout\.entries([^A-Za-z0-9_.-]|$)' "$validation_log"; then
  printf 'Backup validation failed: archive contains no nightscout.entries namespace.\n' >&2
  exit 1
fi

archive_size="$(wc -c < "$temporary_archive")"
archive_hash="$(sha256sum "$temporary_archive" | cut -d ' ' -f 1)"
printf '%s  %s\n' "$archive_hash" "$(basename "$archive")" > "$temporary_checksum"
printf '{\n  "archive": "%s",\n  "bytes": %s,\n  "database": "nightscout",\n  "sha256": "%s",\n  "validated_with": "mongorestore_dry_run",\n  "created_at": "%s"\n}\n' \
  "$(basename "$archive")" \
  "$archive_size" \
  "$archive_hash" \
  "$stamp" > "$temporary_metadata"

chmod 600 "$temporary_archive" "$temporary_checksum" "$temporary_metadata"
mv -- "$temporary_checksum" "$checksum"
mv -- "$temporary_metadata" "$metadata"
mv -- "$temporary_archive" "$archive"

while IFS= read -r -d '' expired; do
  rm -f -- "$expired.sha256" "$expired.json" "$expired"
done < <(
  find "$backup_dir" -maxdepth 1 -type f \
    -name 'nightscout-*.archive.gz' \
    -mtime "+$retention_days" \
    -print0
)

printf 'Validated backup written: %s\n' "$archive"
