#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s ARCHIVE_DIRECTORY\n' "${0##*/}" >&2
  exit 2
fi

archive_input=$1
if [[ ! -d "$archive_input" ]]; then
  printf 'Archive directory not found.\n' >&2
  exit 2
fi
if [[ ! -f "$archive_input/manifest.json" ]]; then
  printf 'Archive manifest not found.\n' >&2
  exit 2
fi

archive=$(realpath -- "$archive_input")
if [[ "$archive" == *:* || "$archive" == *$'\n'* ]]; then
  printf 'Archive path contains unsupported characters.\n' >&2
  exit 2
fi

docker compose --profile migration run --rm --build --no-deps \
  --volume "$archive:/archive:ro" \
  nightscout-stage-restore
