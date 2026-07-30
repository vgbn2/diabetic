# Historical Data Provenance

Real clinical data is local, ignored by Git, and must never be printed or
committed. Verification output is limited to hashes, counts, schemas, time
ranges, and rejected-record totals.

## Retained Authorities

| Location | Role | Permitted use |
|---|---|---|
| `storage/migrations/from-2026-06-01/` | Source-preserving Nightscout Extended-JSON archive | Migration staging and local historical replay after manifest verification |
| `storage/exports/*.csv` | Operational MongoDB CSV chapters | Local analysis and explicit CSV replay |
| `storage/exports/test_audit/` | Manually exported MongoDB extraction evidence | Preserve byte-for-byte; validate against its local manifest |
| `storage/data/processed/*.csv` | PDF-derived estimates | Labelled offline experiments only; never deployable training truth |
| `ops/lab/fixtures/` | Synthetic committed fixtures | Deterministic unit and contract tests |

The manual `test_audit` bundle intentionally overlaps operational chapters.
That overlap is approved validation evidence, not an accidental duplicate.
`consolidated_training.csv` is preserved for provenance but is explicitly
unsafe as a training input because it combines incompatible timestamp/glucose
schemas. `mar23-apr07.csv` is PDF-derived rather than a MongoDB export.

## Verification

Verify local authorities without exposing records:

```bash
.venv/bin/python scripts/ops/verify_historical_data.py \
  --archive storage/migrations/from-2026-06-01 \
  --csv-dir storage/exports \
  --csv-dir storage/exports/test_audit \
  --json
```

Refresh the ignored manual-evidence manifest only after confirming the target:

```bash
.venv/bin/python scripts/ops/verify_historical_data.py \
  --csv-dir storage/exports/test_audit \
  --write-manifest --json
```

The verifier fails closed on hash, count, JSON, schema, timestamp-order, and
unapproved duplicate-record errors. The migration restore path runs archive
verification before connecting to the target database.
