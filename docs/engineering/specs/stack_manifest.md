# Stack & Toolchain Manifest

> **Diátaxis Type**: Reference & Specification | **Status**: Canonical | **Owner**: Systems Architecture | **Review**: Continuous

---

## 1. Core Technology Stack

| Layer | Component | Version | Role in Platform |
|---|---|---|---|
| **Runtime** | CPython | 3.11+ | High-performance async runtime |
| **Deep Learning** | PyTorch | 2.2.0+ | 1D-CNN temporal sequence inference |
| **Signal Processing** | NumPy / SciPy | 1.26+ / 1.12+ | Kalman 3D linear algebra and curve fitting |
| **Database** | MongoDB | 6.0 (Docker) | Primary document store for time-series telemetry |
| **Database** | SQLite 3 | 3.40+ | Local vessel registry & audit journal |
| **ORM** | SQLAlchemy | 2.0+ | Async database session management |
| **Web Framework** | FastAPI | 0.110+ | REST API & WebSocket ingress gateway |
| **Server** | Uvicorn | 0.28+ | ASGI production server |
| **CLI / TUI** | Rich / Click | 13.7+ / 8.1+ | Terminal HUD, ANSI tables, and progress bars |
| **MCP Integration** | FastMCP | 0.4+ | Model Context Protocol diagnostic tool server |
| **Documentation** | MkDocs Material | 9.5+ | Static site generator with MathJax & Mermaid |

---

## 2. Testing & Quality Toolchain

| Tool | Version | Purpose |
|---|---|---|
| **pytest** | 8.0+ | Core test runner and contract assertion engine |
| **pytest-asyncio** | 0.23+ | Async event loop test harness |
| **coverage** | 7.4+ | Structural statement and branch coverage tracking |
| **compileall** | stdlib | Bytecode compilation and syntax verification gate |
| **cleanliness script** | `scripts/check_repo_cleanliness.py` | SV Console 7-gate repository hygiene evaluator |
