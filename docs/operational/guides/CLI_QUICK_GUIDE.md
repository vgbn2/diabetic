# CLI Quick Guide

> **Diátaxis Type**: How-to Guide / Reference | **Status**: Canonical | **Review**: Continuous

Bio-Quant provides a unified command line interface via `diabetic.main`.

---

## Command Matrix

| Command | Syntax | Description |
|---|---|---|
| **live** | `python -m diabetic.main live [--port 8000]` | Start continuous monitoring coordinator & TWA server |
| **ingest** | `python -m diabetic.main ingest --file <path>` | Ingest raw CSV/BSON entries into MongoDB |
| **replay** | `python -m diabetic.main replay --file <path>` | Replay historical stream through Kalman & ML engine |
| **retention** | `python -m diabetic.main retention [--days 90]` | Run bounded historical cleanup with pre/post audit |
| **admin** | `python -m diabetic.main admin <subcommand>` | Tenant profile management and secret configuration |
| **cleanliness**| `python scripts/check_repo_cleanliness.py` | Run 7-gate SV Console cleanliness evaluator |

---

## Exit Code Conventions
- `0`: Success / Clean Termination
- `1`: Validation Failure / Missing Arguments / Already Running
- `2`: Hardware / Connection Unreachable
