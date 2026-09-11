# Testing Surface Matrix

> **Diátaxis Type**: Reference & How-to | **Status**: Canonical | **Review**: Continuous

---

## Contract Test Suite Inventory

| Test File | Category | Invariant Verified | Execution Time |
|---|---|---|---|
| `ops/lab/test_cli_manifest.py` | CLI Contracts | 12/12 manifest commands wired without stubs | ~5.5s |
| `ops/lab/test_mcp_tools.py` | MCP Protocol | Schema validation and safety bounds | ~0.8s |
| `ops/lab/test_operational_contracts.py` | Unit Authority | Strict mmol/L calculations & display formatting | ~2.7s |
| `ops/lab/test_runtime_lifecycle.py` | Lifecycle | Single-claim startup & task draining | ~2.6s |
| `ops/lab/test_clinical_contracts.py` | Clinical DSP | Kalman 3D & Kovatchev risk transformations | ~1.5s |
| `ops/lab/test_event_integrity.py` | Ingestion | Deduplication hashing & gap detection | ~1.2s |
| `ops/lab/test_retention_cleanup.py` | Operations | Bounded batch deletion & audit logging | ~1.0s |
| `ops/lab/test_alert_delivery.py` | Decision | Faint detection & RLHF dampening | ~1.1s |

---

## Running Test Commands

```bash
# Run full contract test suite
pytest -q ops/lab/ tests/

# Run specific contract suite
pytest -q ops/lab/test_runtime_lifecycle.py

# Run standalone SV Console cleanliness evaluator
python scripts/check_repo_cleanliness.py
```
