# Engineering Standards

> **Diátaxis Type**: Standard & Policy | **Status**: Canonical | **Review**: Continuous

This document outlines the core coding, performance, and testing standards for the Bio-Quant platform.

---

## 1. Zero-Stub & Declarative Manifest Invariant

- Every CLI command in `diabetic/cli/manifest.py` must have an implemented handler in `diabetic/cli/commands/`.
- Every FastMCP diagnostic tool in `diabetic/mcp/server.py` must have typed schema validation.
- Zero mock placeholders or `TODO` stubs in production paths.

---

## 2. Resource Clamping & Single-Threaded Constraints

- Multi-threaded linear algebra libraries (OpenBLAS, MKL, OMP) must be clamped to `1` thread on constrained deployment targets.
- Per-test explicit garbage collection (`gc.collect()`) in test suites to prevent RAM ballooning and SSD thrashing.

---

## 3. Strict Unit Authority

- All calculations, internal models, and persistence must use **$\text{mmol/L}$**.
- Conversions to $\text{mg/dL}$ take place solely in `diabetic.ui.glucose_display` for presentation.
