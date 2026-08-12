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
   the HTTP process is alive; `/readyz` requires healthy providers and a fresh
   in-process glucose snapshot.

The machine-readable health output reports `ready` for core monitoring and
`neural_ready` for validated loaded weights plus a warm inference buffer.
Kinematic fallback can operate when core readiness is true and neural readiness
is false.

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
before any separately authorized cutover. Take a local backup with
`scripts/ops/backup_local_nightscout.sh`.
