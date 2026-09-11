# TUI Feature Map — Bio-Quant

Source of truth: `diabetic/cli/tui/manifest.py` (metadata) + `diabetic/cli/dispatcher.py` (routing).
Contract test: `ops/lab/test_cli_manifest.py` (manifest ↔ handler parity).
Updated: 2026-09-11

Ported from the `personal_finance_draft` CLI/TUI pattern (declarative manifest →
generic menu engine → `commands/` handlers). Fully aligned: 6
categories, 12 commands, every entry wired to real code (no stubs).

Legend:
- ✅ Wired — TUI item maps to a live handler; verified
- 🔧 Partial — handler works but needs live infra / weights / creds to do anything useful
- ⚠️ Stub — TUI item dispatches to an unimplemented handler (rejected by the contract test)
- ❌ Broken — TUI item dispatches and the handler errors out

---

## Launching

```bash
python -m diabetic.cli.tui                        # interactive menu
python -m diabetic.cli <category> <command> [..]  # one-shot CLI
python -m diabetic.main tui                        # convenience (bypasses the service lock)
diabetic                                           # PowerShell function -> the TUI (see diabetic.ps1)
diabetic op status                                 # PowerShell function -> one-shot CLI
```

## Main Menu

```
BIO-QUANT · CLI/TUI | HH:MM:SS UTC | Select Category:
  1. Operational Dashboard & Health
  2. Simulation
  3. Data & Admin
  4. Diagnostics
  5. Model Training
  6. Settings & Preferences
```

---

## 1. Operational Dashboard & Health

Category id: `op`

| TUI Label | CLI Command | Flags | Status | Notes | Exit Code |
|---|---|---|---|---|---|
| Status (rich health dashboard) | `diabetic.cli op status` | `--json` | ✅ | Human table from `get_system_health()`; `--json` for automation | `0` = ok |
| Health (machine-readable JSON) | `diabetic.cli op health` | — | ✅ | Mirrors finance `backend integrity --json` | `0` = ok |
| Live Service + HUD | `diabetic.cli op live` | — | 🔧 | Subprocesses `python -m diabetic.main live`; needs full env (Nightscout/Mongo/weights) | `0` = clean exit |

---

## 2. Simulation

Category id: `sim`

| TUI Label | CLI Command | Flags | Status | Notes | Exit Code |
|---|---|---|---|---|---|
| Hypoglycemic Crash scenario | `diabetic.cli sim crash` | — | ✅ | Reuses `main.run_simulation("crash")` | `0` = ok |
| Hyperglycemic Faint-risk scenario | `diabetic.cli sim faint` | — | ✅ | Reuses `main.run_simulation("faint")` | `0` = ok |
| Normal metabolic stress test | `diabetic.cli sim normal` | — | ✅ | Reuses `main.run_simulation("normal")` | `0` = ok |

---

## 3. Data & Admin

Category id: `admin`

| TUI Label | CLI Command | Flags | Status | Notes | Exit Code |
|---|---|---|---|---|---|
| Export 15-day sensor periods to CSV | `diabetic.cli admin export` | — | 🔧 | Writes to `storage/exports/`; needs MongoDB | `0` = ok, `1` = error |
| Enforce retention policy | `diabetic.cli admin cleanup` | `--retention-days` | 🔧 | Defaults to `config.RETENTION_DAYS`; deletes older data; uses `execute_retention_cleanup` | `0` = ok, `1` = failed/incomplete, `2` = validation error |

---

## 4. Diagnostics

Category id: `diag`

| TUI Label | CLI Command | Flags | Status | Notes | Exit Code |
|---|---|---|---|---|---|
| Hot-Reload Inference Stress Test | `diabetic.cli diag stress` | — | 🔧 | Runs `scripts.simulation.stress_scheduler`; cold-mode if weights absent | `0` = ok, `1` = error |

---

## 5. Model Training

Category id: `ml`

| TUI Label | CLI Command | Flags | Status | Notes | Exit Code |
|---|---|---|---|---|---|
| Last training result | `diabetic.cli ml status` | — | ✅ | Reads local promotion manifest without starting training | `0` = ok, `1` = error |
| Train and promote a candidate | `diabetic.cli ml train` | `--source`, `--epochs` | 🔧 | Serialized, validated, atomic model promotion; needs real data | `0` = ok, `1` = error, `2` = invalid flags |

---

## 6. Settings & Preferences

Category id: `settings`

| TUI Label | CLI Command | Flags | Status | Notes | Exit Code |
|---|---|---|---|---|---|
| Show Current Config (secrets masked) | `diabetic.cli settings show` | `--json` | ✅ | Read-only dump of `config.model_dump()` with secret masking | `0` = ok |

---

## Exit Code Contract

All handlers adhere to standard POSIX-compliant exit codes:
- `0` (`SUCCESS`): Operation completed normally.
- `1` (`RUNTIME_ERROR`): Operational failure (network timeout, database unreachable, incomplete cleanup).
- `2` (`VALIDATION_ERROR`): User input / flag parsing error (e.g. non-numeric `--retention-days`, invalid `--source`).
