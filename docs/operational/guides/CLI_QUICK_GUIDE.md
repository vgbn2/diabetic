# CLI Quick Guide

> **Diátaxis Type**: How-to Guide / Reference | **Status**: Canonical | **Review**: Continuous

Bio-Quant provides a unified structured command line interface via `diabetic.cli` and service runner via `diabetic.main`.

---

## 1. Interactive Terminal UI (TUI)

Launch the full-screen interactive operator console:
```bash
python -m diabetic.cli.tui
# Or alias:
python -m diabetic.main tui
```

---

## 2. Structured CLI Matrix (`diabetic.cli <category> <command>`)

Syntax: `python -m diabetic.cli <category> <command> [--flag value]`

| Category (`category`) | Command (`command`) | Flags / Options | Description |
|---|---|---|---|
| **op** | `status` | `--json` | Display health dashboard (human-readable or JSON) |
| **op** | `health` | | Machine-readable system health JSON snapshot |
| **op** | `live` | | Start continuous monitoring coordinator & TWA server |
| **sim** | `crash` | | Run synthetic rapid hypoglycemic crash scenario |
| **sim** | `faint` | | Run synthetic hyperglycemic faint-risk scenario |
| **sim** | `normal` | | Run synthetic normal metabolic stress test |
| **admin** | `export` | | Export 15-day sensor periods to CSV in `storage/exports/` |
| **admin** | `cleanup` | `--retention-days <N>` | Enforce bounded retention policy cleanup |
| **diag** | `stress` | | Run hot-reload inference stress test (100 iterations) |
| **ml** | `status` | | View last model training result and promotion manifest |
| **ml** | `train` | | Train and evaluate candidate model against validation split |
| **settings** | `show` | | Display active configuration settings and paths |

---

## 3. Direct Service Orchestration (`diabetic.main`)

Direct execution aliases for containerized runtimes and systemd units:

| Command | Syntax | Description |
|---|---|---|
| **live** | `python -m diabetic.main live` | Start continuous monitoring coordinator & TWA server |
| **export** | `python -m diabetic.main export` | Administrative sensor period export |
| **cleanup** | `python -m diabetic.main cleanup` | Retention policy cleanup |
| **health** | `python -m diabetic.main health` | System health JSON snapshot |
| **cleanliness** | `python scripts/check_repo_cleanliness.py` | Run 7-gate SV Console cleanliness evaluator |

---

## 4. Exit Code Conventions
- `0`: Success / Clean Termination
- `1`: Validation Failure / Missing Arguments / Already Running
- `2`: Hardware / Connection Unreachable
