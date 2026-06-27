# TUI Feature Map — Bio-Quant

Source of truth: `diabetic/cli/tui/manifest.py` (metadata) + `diabetic/cli/dispatcher.py` (routing).
Contract test: `ops/lab/test_cli_manifest.py` (manifest ↔ handler parity).
Updated: 2026-06-05

Ported from the `personal_finance_draft` CLI/TUI pattern (declarative manifest →
generic menu engine → `commands/` handlers). Proportionate to this project: 5
categories, 10 commands, every entry wired to real code (no stubs).

Legend:
- ✅ Wired — TUI item maps to a live handler; verified
- 🔧 Partial — handler works but needs live infra / weights / creds to do anything useful
- ⚠️ Stub — TUI item dispatches to an unimplemented handler (rejected by the contract test)
- ❌ Broken — TUI item dispatches and the handler errors out

---

## Launching

```
python -m diabetic.cli.tui                        # interactive menu
python -m diabetic.cli <category> <command> [..]  # one-shot CLI
python -m diabetic.main tui                        # convenience (bypasses the service lock)
diabetic                                           # PowerShell function -> the TUI (see diabetic.ps1)
diabetic op status                                 # PowerShell function -> one-shot CLI
```

## Main Menu

```
BIO-QUANT · CLI/TUI | HH:MM:SS UTC | Select Category:
  Operational Dashboard & Health
  Simulation
  Data & Admin
  Diagnostics
  Settings & Preferences
```

---

## 1. Operational Dashboard & Health

Category id: `op`

| TUI Label | CLI Command | Flags | Status | Notes |
|---|---|---|---|---|
| Status (rich health dashboard) | `diabetic.cli op status` | `--json` | ✅ | Human table from `get_system_health()`; `--json` for automation |
| Health (machine-readable JSON) | `diabetic.cli op health` | — | ✅ | Mirrors finance `backend integrity --json` |
| Live Service + HUD | `diabetic.cli op live` | — | 🔧 | Subprocesses `python -m diabetic.main live`; needs full env (Nightscout/Mongo/weights) |

---

## 2. Simulation

Category id: `sim`

| TUI Label | CLI Command | Flags | Status | Notes |
|---|---|---|---|---|
| Hypoglycemic Crash scenario | `diabetic.cli sim crash` | — | ✅ | Reuses `main.run_simulation("crash")` |
| Hyperglycemic Faint-risk scenario | `diabetic.cli sim faint` | — | ✅ | Reuses `main.run_simulation("faint")` |
| Normal metabolic stress test | `diabetic.cli sim normal` | — | ✅ | Reuses `main.run_simulation("normal")` |

---

## 3. Data & Admin

Category id: `admin`

| TUI Label | CLI Command | Flags | Status | Notes |
|---|---|---|---|---|
| Export 15-day sensor periods to CSV | `diabetic.cli admin export` | — | 🔧 | Writes to `storage/exports/`; needs MongoDB |
| Enforce retention policy | `diabetic.cli admin cleanup` | `--retention-days` | 🔧 | Defaults to `config.RETENTION_DAYS`; deletes older data; needs MongoDB |

---

## 4. Diagnostics

Category id: `diag`

| TUI Label | CLI Command | Flags | Status | Notes |
|---|---|---|---|---|
| Hot-Reload Inference Stress Test | `diabetic.cli diag stress` | — | 🔧 | Runs `scripts.simulation.stress_scheduler`; cold-mode if weights absent |

---

## 5. Settings & Preferences

Category id: `settings`

| TUI Label | CLI Command | Flags | Status | Notes |
|---|---|---|---|---|
| Show Current Config (secrets masked) | `diabetic.cli settings show` | `--json` | ✅ | Read-only `config.model_dump()` with secret masking |

---

## Open Gaps (vs the finance reference)

| Item | Gap | Effort |
|---|---|---|
| Settings write commands | Only `show` exists; finance has `timezone/layout/params/flags/alerts/reset`. Config here is env/.env-driven, so writes need a `user_settings.json` overlay layer first. | M |
| `live` / `export` / `cleanup` / `stress` | 🔧 because they need MongoDB / full env / weights — not a code gap, an environment gap. Clears when run against real infra. | env |
| Arrow-key navigation + search | Engine uses numbered selection (win32-robust); finance has arrow-key + `/`-search. | M |
| Per-command `--json` everywhere | Only `status`/`settings show` emit JSON; finance has `--json` on every command. | S |

---

## Recent Changes

| Change | Date | Impact |
|---|---|---|
| Initial CLI/TUI section ported from finance | 2026-06-05 | ✅ Manifest + dispatcher + rich engine + 10 commands across 5 categories; contract test added |
