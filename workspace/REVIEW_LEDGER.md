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
