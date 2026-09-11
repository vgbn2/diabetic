# Bio-Quant Engine

Institutional-grade, real-time metabolic intelligence, physical-chemical digital twin simulation, and neural faint risk prediction for Type 1 Diabetes management.

---

## Core System Invariants

Bio-Quant operates under five non-negotiable architectural invariants:

1. **Fail-Closed Safety Invariant**: Missing telemetry, sensor detachment, stale cache, or neural divergence aborts automated projection and falls back strictly to physical-chemical kinematics. Zero unvalidated neural forecasts reach the patient alert pipeline.
2. **Single-Claim Startup Authority**: Only one coordinator instance may run at any time. An atomic POSIX PID file lock with process validation (`diabetic.lock`) prevents multiple pollers or split-brain coordination.
3. **Strict Presentation Unit Authority**: The core mathematical and biological pipeline computes exclusively in **mmol/L**. Unit conversion to **mg/dL** occurs strictly at presentation boundaries (`diabetic.ui.glucose_display`) and never leaks into storage or risk calculations.
4. **Alpha Gate Confidence Pre-Conditioning**: Confidence index over the 90-minute historical horizon is computed *before* evaluating neural vs. kinematic divergence, ensuring the safety shield operates on deterministic, temporal-decayed confidence metrics.
5. **Zero-Stub Engineering & Declarative Contracts**: Every CLI command, MCP tool, ingestion route, and API endpoint is declaratively registered with strict validation schemas. Zero placeholder stubs exist across production paths.

---

## Documentation Navigation

The documentation corpus follows the **Diátaxis Documentation Framework**, partitioning knowledge into four distinct quadrants:

<div class="grid cards" markdown>

-   :material-compass: __[Architecture Summary](ARCHITECTURE.md)__

    ---

    System architecture overview, 5-layer intelligence hierarchy, operational data flow, and Diátaxis structure map.

-   :material-book-open-page-variant: __[Architecture Suite](engineering/architecture/01_ARCHITECTURE_AND_CODEBASE.md)__

    ---

    7-section deep-dive covering C4 topologies, Ingestion, 3D Kalman DSP, ML Twin & CNN, Decision Matrix, Ingress, and Clinical Primer.

-   :material-file-document-check: __[Specifications](engineering/specs/product_spec.md)__

    ---

    Canonical contracts: Product Spec, Technical Spec, Web REST & TWA Bridge API, Capability and Stack manifests, and Tenancy Roadmap.

-   :material-hammer-wrench: __[Operations & Runbooks](OPERATIONAL_SOAK_RUNBOOK.md)__

    ---

    Operational soak runbook, Dockerized Nightscout deployment, data ingestion & retention, CLI quick guide, and testing surface matrix.

</div>

---

## Fast Start

Initialize development environment, verify dependencies, and execute full contract test suite:

```bash
# Set up virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Run complete repository cleanliness and hygiene evaluator
python scripts/check_repo_cleanliness.py

# Run contract and integration test suite
pytest -q ops/lab/ tests/
```

### Serve Documentation Locally

Serve this documentation site locally with live reload:

```bash
# Start live-reloading MkDocs server at http://localhost:8000
mkdocs serve

# Build static HTML site under strict link validation
mkdocs build --strict
```

---

## Verification Matrix

```bash
python scripts/check_repo_cleanliness.py          # SV Console 7/7 Cleanliness Gate (Grade A+)
pytest -q ops/lab/test_cli_manifest.py           # CLI Manifest ↔ Dispatcher Parity
pytest -q ops/lab/test_mcp_tools.py              # FastMCP Tool Schemas & Safety Boundary
pytest -q ops/lab/test_runtime_lifecycle.py      # Coordinator Lifecycle State Machine
pytest -q ops/lab/test_operational_contracts.py  # Presentation Unit Authority & Glucose Display
pytest -q ops/lab/test_event_integrity.py        # Ingestion Deduplication & Gap Tracking
pytest -q ops/lab/test_clinical_contracts.py     # Kovatchev Risk Transform & Kinematics
```
