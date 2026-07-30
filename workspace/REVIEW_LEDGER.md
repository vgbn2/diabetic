# Deep Review Ledger

_Last updated: 2026-07-23. Scope: full repository blast-through, audit only._

## Promotion Verdict

**Blocked.** A critical glucose-unit inversion and four high-severity
clinical/runtime defects prevent promotion.

## Defect Confidence Score

| Factor | Score | Evidence |
|---|---:|---|
| Freshness | 0.68 | Current source compiled, but live tests, Docker runtime, and semantic graph refresh are unavailable; the local venv is broken. |
| Schema integrity | 0.75 | Core typed models exist, but SGV units, telemetry provenance, and treatment date types violate cross-boundary contracts. |
| Coverage | 0.72 | Historical committed-archive suite is 70 passing; current execution is unavailable and the highest-risk seams have no tests. |

`DCS = 0.30 × 0.68 + 0.40 × 0.75 + 0.30 × 0.72 = 0.720`

Strict promotion gate: **0.950**.

## Section Grades

| Section | Grade | Primary reason |
|---|---:|---|
| Authentication primitives | B | HMAC/authz logic is strong; dev bypass credential is exposed by config surfaces. |
| CLI and MCP | C | Useful parity and read-only MCP tools, but config masking leaks an auth token. |
| Nightscout and Mongo ingestion | D | Ambiguous SGV threshold can invert a severe hypo; treatment retention type mismatch. |
| Cardiac and weather ingestion | D | Mock defaults and missing provenance feed clinical decisions and training. |
| DSP and metabolic math | B | Coherent defensive logic; correctness depends on contaminated upstream context. |
| ML inference | B | Missing/invalid deployed weights fail closed; input provenance remains unguarded. |
| ML training and scheduling | D | Event-loop blocking, duplicate ownership, unsafe in-place artifact promotion. |
| Coordinator | C | Broad integration works conceptually, but owns overlapping maintenance and accepts synthetic inputs. |
| TWA API and frontend | D | Cold zero and stale snapshots are presented as live and can trigger haptics. |
| Storage/audit registry | B | Solid typed SQLite layer; Mongo readiness and date schema contracts are weak. |
| Health/operations | C | Reports configuration and client handles rather than verified connectivity. |
| Tests | C | 70 historical tests, but no current runnable environment and missing critical-seam coverage. |
| Deployment/tooling/docs | D | No env template, floating images, no healthchecks, broken venv, stale graph/docs. |

## Connective Sweep

| Artifact/path | Classification | Disposition |
|---|---|---|
| `diabetic/ingestion/sim_reader.py` and `diabetic/ingestion/offline/sim_reader.py` | Stale duplicate | Select one canonical location and migrate callers. |
| `diabetic/ingestion/plot_glucose.py` and offline variant | Diverged duplicate | Keep the consumed implementation; archive or remove the orphan after caller proof. |
| tracked `diabetic/storage/__pycache__/*.pyc` | Stale generated artifact | Remove from the index; `.gitignore` already excludes replacements. |
| `run_graphify.py`, `.graphifyignore` | Incomplete/dangerous tooling | Harden before commit; refuse to overwrite semantic output without credentials. |
| `.agents/skills/session-orchestrator/` | Untracked mirror | Decide canonical skill location and commit/mirror intentionally. |
| `graphify-out/GRAPH_REPORT.md` | Stale evidence | Do not use for current architecture decisions until semantic refresh succeeds. |
| XGBoost claims and dependency | Incomplete future architecture | No production implementation exists; label docs/dependency as future or remove. |

## Verification Snapshot

- `git diff --check`: passed.
- Working-tree and committed-HEAD `compileall`: passed under system Python 3.14.
- Fresh `git archive HEAD`: extracted and compiled successfully.
- Current pytest: blocked; system Python lacks project dependencies and `.venv`
  links to a deleted `/tmp` CPython 3.11 interpreter.
- Historical committed archive on 2026-07-18: 70 passed; not revalidated today.
- Docker Compose CLI: 2.40.3 available.
- Docker daemon: inaccessible (`permission denied` on `/var/run/docker.sock`).
- Semantic graph refresh: blocked; `graphify` command absent and required API key
  is not exported.
- Counted source: 9,507 production Python LOC, 909 test LOC, 3,783 script LOC,
  and 574 TWA HTML/CSS/JS LOC.

## Remediation Order

1. R17 glucose-unit contract and parity tests.
2. R18 secret serialization and dev-auth profile gate.
3. R19 telemetry provenance and synthetic-data exclusion.
4. R20 single-owner atomic model promotion off the live event loop.
5. R21 explicit HUD readiness/freshness contract.
6. R22-R24 retention, health truthfulness, and reproducibility cleanup.

## 2026-07-23 Superseding Verification

The code-level promotion defects R17-R23 are remediated and the full suite now
passes (85 tests plus 5 subtests). R24 remains partial because Docker runtime
access is denied. Live readiness is also false: MongoDB is reachable but the
configured Nightscout endpoint is not, and the existing model predates the
promotion manifest. Therefore this is a verified implementation candidate, not
a production-ready deployment.

## 2026-07-24 Superseding Full Audit

### Promotion Verdict

**Blocked.** R17-R24 remain materially improved, but R25 exposes cross-user
patient access and R26-R27 can suppress or degrade safety-relevant state without
an explicit failed contract. The lowest critical-path gate is **failed**.

### Defect Confidence Score

Starting ledger DCS: **0.720**.

| Factor | Score | Current evidence |
|---|---:|---|
| Freshness | 0.72 | HEAD archive compiles and Compose config passes, but the graph is stale, both Python 3.12 links are broken, pytest cannot run, and Docker/live readiness remain unavailable. |
| Schema integrity | 0.86 | SGV, provenance, timestamps, and atomic promotion are improved; identity ownership, treatment failure state, alert provenance, and readiness semantics remain invalid. |
| Coverage | 0.80 | 85 test functions and five historical subtests exist, but the current suite is not executable and R25-R29 lack active-path tests. |

`DCS = 0.30 x 0.72 + 0.40 x 0.86 + 0.30 x 0.80 = 0.800`

Strict promotion gate: **0.950**.

### Current Section Grades

| Section | Grade | Primary reason |
|---|---:|---|
| Authentication primitives | A | Telegram HMAC, replay age, and development-token profile gate are coherent. |
| Authorization and identity ownership | D | Any registry user reaches the one-patient pipeline and calibration targets `config.USER_ID`. |
| Nightscout and Mongo ingestion | B | SGV/timestamp contracts are repaired; provider failure still collapses into valid-empty treatment state. |
| Cardiac and weather ingestion | B | Synthetic provenance is explicit and persistence-gated; real five-day weather remains an orphaned incomplete path. |
| DSP and metabolic math | B | Defensive signal logic is coherent, but critical-path tests do not exercise the coordinator directly. |
| ML inference and training | C | Atomic off-loop promotion is strong; predicted HR suppression and placeholder temporal features remain untrusted. |
| Coordinator | C | The central path is wired, but degraded treatment state and signal provenance are not represented explicitly. |
| Alert decision matrix | D | Predicted HR and RLHF can suppress safety alerts without dedicated regression gates. |
| TWA API and frontend | C | Freshness rendering is repaired; single-patient identity is not enforced at the API boundary. |
| Storage and registry | B | Async persistence and write allowlisting are solid; multi-tenant schema conflicts with single-pipeline authorization. |
| CLI and MCP | C | Command/tool parity is clean, but both publish the misleading system-ready contract. |
| Tests | C | 85 test functions exist historically; current interpreter is broken and high-risk active paths are uncovered. |
| Deployment, tooling, and docs | D | Compose is statically valid, but runtime is blocked and Python/graph/architecture evidence is stale. |

System-design grade: **F / promotion blocked**. Component repairs do not clear
the mandatory safety path because identity ownership and alert suppression are
currently bypassable.

### Connective and Orphan Matrix

| Artifact/path | Classification | Evidence/disposition |
|---|---|---|
| `run_graphify.py`, `.graphifyignore` | Incomplete/dangerous | Untracked; must not overwrite semantic output without credentials. |
| `graphify-out/GRAPH_REPORT.md`, `manifest.json` | Stale | 2026-06-05 Windows-path graph still describes removed topology. |
| `WeatherIngestor.fetch_forecast_5d` | Incomplete | No caller; real provider branch logs not implemented and returns empty. |
| `holidays` integration | Incomplete | Optional undeclared dependency changes production model features by environment. |
| Offline PDF parser dependencies | Intentional developer tooling | Declared in `requirements-dev`; not reachable from live/container entrypoints. |
| `docs/architecture.md` | Stale | Windows-only links, missing roadmap target, and outdated trust claims. |
| `.venv` and user-local `python3.12` | Stale generated environment | Both resolve to a deleted temporary interpreter. |

### Verification Snapshot

- `git fsck --strict`, `git diff --check`, Compose config, and backup-shell
  syntax pass.
- Fresh `git archive HEAD` extracted and compiled under system Python 3.14.
- v15 artifact hash matches between working tree and clean archive:
  `54c686cca61e0d226838d659ae7149a71e342971c76a8b92b45b71d62e600f1e`.
- Current pytest and package compatibility checks are blocked by the deleted
  Python 3.12 interpreter; system Python 3.14 has no pytest.
- Docker daemon access remains denied at `/var/run/docker.sock`.
- Static inventory: 85 test functions; historical execution remains 85 tests
  plus five subtests.
- LOC inventory: 9,546 production Python lines under `diabetic/`, 1,172 test
  lines under `ops/lab/`, 3,718 Python lines under `scripts/`, and 589 TWA
  HTML/CSS/JavaScript lines.

### Next Cleanup Move

Fix R25 first by enforcing the declared single-patient ownership contract, then
lock R26 with direct decision-matrix tests. R27 treatment degradation and R28
readiness truthfulness follow before rebuilding the runtime and rerunning the
full clean-archive suite.

## 2026-07-24 Post-Implementation Ledger

### Defect Confidence Score

| Factor | Score | Current evidence |
|---|---:|---|
| Freshness | 0.90 | Durable Python and current working-tree/archive-equivalent tests pass; graph and Docker/live runtime remain stale or unavailable. |
| Schema integrity | 0.96 | Ownership, alert provenance, treatment degradation, readiness, and temporal contracts are explicit and tested. |
| Coverage | 0.96 | 105 tests plus 10 subtests pass in both working tree and isolated HEAD-plus-patch source; external runtime scenarios remain unexecuted. |

`DCS = 0.30 x 0.90 + 0.40 x 0.96 + 0.30 x 0.96 = 0.942`

Strict promotion gate: **0.950**. Code verification is green; promotion remains
blocked on Docker/live-provider, restart/recovery, backup/restore, real cardiac,
and semantic-graph evidence.

### Grade Movement

| Section | Before | After | Evidence |
|---|---:|---:|---|
| Authorization and ownership | D | A | Registry-only denial plus patient/caregiver contracts. |
| Alert decision matrix | D | A | Critical and cardiac-provenance regression tests. |
| Nightscout/Mongo treatment ingestion | B | A | Explicit provider state, fallback, and bounded retention. |
| Coordinator | C | B | Degraded treatment state is represented; decomposition remains deferred. |
| CLI/MCP readiness | C | A | Shared core/neural readiness output. |
| Tests | C | A | Current and isolated-source 105-test runs. |
| Deployment/tooling/docs | D | C | Python/docs repaired; Docker and graph evidence remain open. |

System-design grade: **C / code verified, promotion blocked**.

## 2026-07-25 Historical-Data And Hygiene Ledger

Starting and ending repository DCS: **0.942**. This audit changed no runtime
code or evidence, so the established score is unchanged. Promotion remains
blocked by the same external runtime gates.

### Data Source Classification

| Path | Classification | Trust/use |
|---|---|---|
| `storage/migrations/from-2026-06-01/` | Intentional, canonical source archive | Best real historical source. 7,204 entries and one profile; six hashes reverified. Not wired into tests. |
| `storage/exports/*.csv` | Intentional, derived clinical chapters | Canonical legacy CSV set: 11,781 unique Mongo-derived readings, April 11-May 27. No manifest and incompatible with `MetabolicDataset` until normalized. |
| `storage/data/processed/*.csv` | Derived PDF extraction | Useful for offline parser/backtest experiments, not source-preserving ground truth. Missing real cardiac telemetry. |
| `storage/data/processed/archive/` | Stale experiment archive | Multiple parser generations, no active consumers, duplicate/drift risk. |
| `data/forecasts/`, `storage/raw/forecasts/` | Synthetic/derived | Simulation output only; never historical clinical truth. |
| `storage/raw/backtest_neural_overlay.csv` | Derived model output | Backtest result, not an input truth source. |
| Nested `test_audit` and troubleshooting exports | Stale shadows/fixtures | All clinical rows are subsets of `storage/exports/*.csv`; infrastructure files are repeated two-row synthetic fixtures. |
| `consolidated_training.csv` | Dangerous/incomplete | Mixed incompatible schemas; active loader discards the Mongo-export half. |

### Orphan Matrix

| Artifact/path | Classification | Evidence/disposition |
|---|---|---|
| `scripts/analysis/neural_refresh_cycle.py` | Dangerous | Mixed-schema merge and un-awaited async training produce false success. |
| `diabetic/ingestion/offline/sim_reader.py` | Incomplete | No caller; JSON-array-only implementation contradicts JSON/CSV claim. |
| `scripts/tools/extract_historical.py` | Stale | Input root moved to `storage/raw/test/ottai_data`. |
| Three Windows-path CSV validators | Stale | Target checkout and filenames do not exist. |
| `visualize_lag.py`, `verify_predictive_power.py` | Incomplete | Required synthetic CSV is absent. |
| `neural_backtest_14day.py`, `fidelity_audit.py` | Stale/incomplete | Old output root and legacy claims; exceptions can hide zero inference. |
| `WeatherIngestor.fetch_forecast_5d` | Incomplete | Previous finding remains: no production caller or real implementation. |
| `diabetic/ingestion/sim_reader.py` | Resolved stale finding | File is absent; only the offline reader remains. |

### Reviewed Section Grades

| Section | Grade | Primary reason |
|---|---:|---|
| Migration archive | B | Source-preserving and hash-manifested, but replay is unwired and restore ignores hashes. |
| Mongo clinical CSV exports | B | Clean canonical chapters exist, but lack a manifest and loader adapter. |
| Processed/PDF data | C | Useful derived datasets are mixed with experimental archive versions and overstated as ground truth. |
| Analysis/troubleshooting scripts | D | Multiple broken paths, missing inputs, orphan tools, and one false-success trainer. |
| Historical-data tests | D | Active suite has no artifact-backed replay or dataset-lineage test. |
| CLI/TUI wiring | A | Manifest/dispatcher contract remains clean; focused suite passed 8 tests. |
| General runtime tests | A | Current full suite exited successfully; 105 tests collected. |

Historical-data hygiene grade: **C**. A trustworthy source archive exists, but
the active testing/training boundary does not consume it and the surrounding
CSV/script landscape obscures that fact.

### Next Cleanup Move

Create one manifest-driven, de-identified replay-fixture builder from the June
JSONL archive. Then add an artifact-backed ingestion test before deleting or
archiving redundant CSV shadows and dead analysis scripts.
