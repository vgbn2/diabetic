# Data Ingestion & Retention Operations

> **Diátaxis Type**: How-to Guide | **Status**: Canonical | **Review**: Continuous

---

## 1. Multi-Source Ingestion Ingestion Commands

```bash
# Ingest historical CSV dataset into local MongoDB
python -m diabetic.main ingest --file ops/lab/fixtures/historical_chapter.csv

# Replay historical chapter in simulated real-time mode
python -m diabetic.main replay --file ops/lab/fixtures/historical_chapter.csv --speed 10.0
```

---

## 2. Retention Cleanup Execution

To prevent unbounded database growth on edge NAS hardware, execute scheduled retention cleanup:

```bash
# Dry-run retention cleanup (audits candidate records older than 90 days)
python -m diabetic.main retention --days 90 --dry-run

# Execute bounded batch cleanup
python -m diabetic.main retention --days 90 --batch-size 500
```
