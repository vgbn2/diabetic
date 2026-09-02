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

.venv/bin/python scripts/ops/migrate_nightscout.py stage-restore \
  --source storage/migrations/from-2026-06-01
```

Restore always targets a new staging database. Compare its counts with the
manifest before any manual cutover. Take a local backup with
`scripts/ops/backup_local_nightscout.sh`.

## Public Ingress Routing

### Option 1: Tailscale Funnel (Active & Zero-Domain)
Exposes Nightscout securely over Tailscale Public HTTPS with automated Let's Encrypt certificates:
```bash
# Enable Funnel proxy on port 1337
tailscale serve --bg 1337
tailscale funnel --https=443 on
```
- **Public URL**: `https://hpdesk-1.tail285cce.ts.net`
- **Raw API Secret**: `${NIGHTSCOUT_API_SECRET}` (Configure in `.env`)
- **CGM Uploader Secret (SHA-1)**: SHA-1 hash of your configured API secret
- **Direct Entry Webhook**: `https://hpdesk-1.tail285cce.ts.net/api/v1/entries?secret=<sha1_or_raw_secret>`

### Option 2: Cloudflare Zero Trust Named Tunnel (Custom Domain)
For custom vanity domains (e.g. `https://cgm.yourdomain.com`):

1. **Pre-requisite**: An active domain registered or DNS-delegated inside Cloudflare.
2. **Tunnel Infrastructure**:
   `cloudflared` is already installed as a systemd service across:
   - `hpdesk-vm` (`192.168.4.101`)
   - `hpdesk-pve` (`192.168.4.110`)
   - `dell-pve` (`192.168.4.102`)
   Clustered under Tunnel ID: `3d32116d-b8bf-4041-bf0e-338f3d054ee6` (`vgbn-tunnel`).
3. **Adding the Route**:
   - Go to Cloudflare Zero Trust Dashboard -> Networks -> Tunnels -> `vgbn-tunnel`.
   - Under **Public Hostnames**, click **Add a public hostname**.
   - Subdomain: `cgm` (or `ns`).
   - Domain: Select your registered Cloudflare domain from the dropdown.
   - Service: `HTTP` -> `127.0.0.1:1337` (or `192.168.4.101:1337`).
   - Save hostname.
4. **CGM App Settings**:
   - **Base URL**: `https://cgm.<yourdomain>.com`
   - **Raw API Secret**: `${NIGHTSCOUT_API_SECRET}` (from `.env`)
   - **API Secret (SHA-1)**: SHA-1 hash of `${NIGHTSCOUT_API_SECRET}`

### Option 3: Synology NAS (DS220+ / Low-Spec / No-AVX Hardware)
If deploying Nightscout & Bio-Quant on resource-constrained NAS hardware (e.g. Synology DS220+ or Intel Celeron CPUs without AVX):
- **MongoDB Compatibility**: MongoDB 5.0+ requires AVX CPU instructions. Use `mongo:3.6` (e.g. `mongod --smallfiles --oplogSize 128 --wiredTigerCacheSizeGB 0.25`).
- **Memory & CPU Limits**: DS220+ Linux kernel does not support Docker CFS CPU quotas (`deploy.resources.limits.cpus`). Use `mem_limit: 400m` instead.
- **LibreLink Bridge Integration**: When using `timoschlueter/nightscout-librelink-up`:
  - `NIGHTSCOUT_URL`: Must omit protocol prefix (use `nightscout:1337`).
  - `NIGHTSCOUT_API_TOKEN`: Must be the exact 40-character SHA-1 hash of your `API_SECRET`.

