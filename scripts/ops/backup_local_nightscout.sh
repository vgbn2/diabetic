#!/usr/bin/env bash
set -euo pipefail

backup_dir="${1:-storage/backups}"
mkdir -p "$backup_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$backup_dir/nightscout-$stamp.archive.gz"

docker compose exec -T mongodb mongodump \
  --db nightscout \
  --archive \
  --gzip > "$archive"

sha256sum "$archive" > "$archive.sha256"
printf 'Backup written: %s\n' "$archive"
