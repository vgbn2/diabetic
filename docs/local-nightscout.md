# Local Nightscout runbook

The local stack keeps MongoDB private to the Compose network and publishes
Nightscout and Bio-Quant only on loopback by default.

1. Copy `.env.example` to `.env` and set a strong Nightscout secret plus the
   required Telegram and patient values.
2. Validate with `docker compose config`.
3. Start with `docker compose up -d --build`.
4. Check `docker compose ps`, `http://localhost:1337`, and
   `http://localhost:8000/healthz`.
5. Check `http://localhost:8000/readyz` separately. `/healthz` proves only that
   the HTTP process is alive; `/readyz` requires accepted authentication on the
   Nightscout entries path, responsive MongoDB, and a fresh in-process glucose
   snapshot. Transport reachability alone is not provider readiness.

The machine-readable health output reports `ready` for core monitoring and
`neural_ready` for validated loaded weights plus a warm inference buffer.
Kinematic fallback can operate when core readiness is true and neural readiness
is false. An unexpected live-runtime or embedded TWA-server failure terminates the
process after one idempotent teardown; Compose then owns process replacement. Bio-Quant
does not attempt to reconstruct the singleton runtime or restart the API thread in the
same process.

## Local profile persistence

Compose sets the Vessel Registry `DATABASE_URL` to
`sqlite+aiosqlite:////app/storage/vessel_registry.db`. The file is therefore inside
the `bio_quant_storage` volume mounted at `/app/storage`, alongside other durable
local application state. The Docker build excludes database files, so a new volume
starts with an empty Registry schema and the configured `TELEGRAM_CHAT_ID` plus
patient traits are imported idempotently from `.env` at core startup.

Direct host launches keep the existing module-local fallback unless
`DATABASE_URL` is set explicitly. Compose does not copy or overwrite an ignored
checkout database at `diabetic/storage/vessel_registry.db`. An external PostgreSQL
or test database remains selectable through the same `DATABASE_URL` owner.

Static Compose inspection and a SQLite close/reopen test prove the configured file
path and file-level persistence contract. They do not prove survival across an
actual container recreation; that remains a separate runtime qualification gate.

For access from a phone or another LAN device, set
`NIGHTSCOUT_BIND_ADDRESS=0.0.0.0` only on a trusted network, keep
`AUTH_DEFAULT_ROLES=denied`, use a strong secret, and restrict port 1337 with
the host firewall. Leave Bio-Quant itself loopback-only unless its authenticated
HUD must also be reached from the LAN.

Automatic model training is disabled by default. Inspect the last result with
`python -m diabetic.cli ml status`; explicitly train with
`python -m diabetic.cli ml train --source mongo`.

## Bounded migration

Use a read-only source account where possible. The export never copies auth,
session, token, or role collections.

```bash
SOURCE_MONGODB_URI='mongodb+srv://...' \
  .venv/bin/python scripts/ops/migrate_nightscout.py export \
  --since 2026-06-01 \
  --destination storage/migrations/from-2026-06-01
```

Archive verification accepts only the canonical Nightscout data collections and
requires every record to have a MongoDB identity. Hashes, counts, schema, paths,
and identities are checked before the restore opens a database connection.

After the Compose runtime is healthy and an operator has explicitly authorized a
staging restore, run:

```bash
scripts/ops/stage_restore_local_nightscout.sh \
  storage/migrations/from-2026-06-01
```

The wrapper mounts only the selected archive read-only into a profile-gated
one-off container and does not start dependencies; the existing MongoDB service
must already be healthy. MongoDB remains private to the Compose network; port
27017 is not published. Restore always creates a new timestamped staging
database and prints aggregate counts only. It does not cut over or replace the
active
`nightscout` database. Compare the staged counts with the verified manifest
before any separately authorized cutover.

## Validated local backups

Take a local backup with `scripts/ops/backup_local_nightscout.sh`. The wrapper writes
into a private same-directory temporary file, rejects empty output, and requires a
successful `mongorestore --dryRun` containing the `nightscout.entries` namespace before
publishing. It publishes a `0600` archive, matching SHA-256 file, and aggregate JSON
metadata (size, checksum, database, timestamp, and validator). Failed, interrupted,
truncated, corrupt, or wrong-namespace attempts leave no published bundle.

Retention defaults to 30 days and can be changed with a non-negative integer
`BACKUP_RETENTION_DAYS`; deletion occurs only after a new bundle is validated and
published, and removes only matching archive companions. A checksum and dry-run prove
local archive readability, not recoverability of a running deployment. Periodic
isolated restore/count comparison remains a separately authorized operator drill; do
not overwrite or cut over the active database as part of routine backup validation.
