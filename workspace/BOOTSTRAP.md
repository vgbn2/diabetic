# Bootstrap — Bio-Quant Hyperglycemia Faint Predictor

## Project Identity
- **Repo**: hyperglycemia-faint-predictor
- **Stack**: Python, PyTorch CNN (v15), SQLAlchemy async, MongoDB, Telegram Bot, Nightscout
- **Purpose**: Real-time physiological monitoring, glucose trend prediction, and faint-risk alerting for diabetic patients

## Directory Map
```
diabetic/           — Core runtime: coordinator, ingestion, ML engine, storage, utils
diabetic/ml_engine/ — CNN inference, training, scheduler, hot-reload
diabetic/storage/   — VesselRegistry (SQLAlchemy async + aiosqlite), MongoDB client
diabetic/ingestion/ — Nightscout, MongoDB, BLE data sources
ops/lab/            — Unit/integration tests
scripts/            — Simulation, backtest, data-transform utilities
graphify-out/       — Knowledge graph output (may be stale; regenerate after code changes)
workspace/          — Session continuity files (this directory)
```

## Source of Truth
- **Current phase & task**: `workspace/STATE.md`
- **Session history**: `workspace/PROMPT_LOG.md`
- **Live objectives**: `workspace/HANDOFF.md`
- **Cumulative cautions**: `workspace/SESSION_MEMORY.md`
- **Audit findings**: `workspace/DEV_REVIEW.md`

## Boot Rules
1. Read `workspace/STATE.md` → `workspace/HANDOFF.md` → `workspace/SESSION_MEMORY.md`
2. Check `git log --oneline -5` to surface any recent untracked changes
3. Regenerate `graphify-out` when code changed since last graph refresh
4. Log the session prompt into `workspace/PROMPT_LOG.md` before starting work

## Hard Constraints
- Windows execution environment — PowerShell syntax; Bash tool for POSIX scripts
- ML weights live at absolute path resolved from project root (`config.py`)
- 3 AM nightly training loop — Timezone must pass boot check or system halts
- No mocking the database in tests (integration tests hit real DB)
- Terse responses; no trailing summaries; no multi-line comment blocks
