# Documentation Standard

> **Diátaxis Type**: Standard & Policy | **Status**: Canonical | **Review**: Continuous

## Purpose

This standard defines how Bio-Quant documents code, architecture, operations, and clinical models. Documentation is maintained with the code: versioned, reviewed, tested, and updated when its owning contract changes.

---

## Research Basis & Frameworks

This standard adapts four established documentation practices:

- **Diátaxis**: Separates tutorials, how-to guides, factual reference, and conceptual explanation.
- **Google Developer Documentation Style**: Focuses on direct language, clear structure, and verified examples.
- **ISO/IEC/IEEE 42010**: Defines viewpoints, architectural descriptions, and stakeholder concerns.
- **Docs-as-Code**: Version-controlled in Git, tested through CI, built strictly under `mkdocs build --strict`.

---

## Documentation Taxonomy

| Type | Purpose | Location |
|---|---|---|
| **Orientation** | "What is this system and where do I start?" | `README.md`, `docs/index.md`, `docs/ARCHITECTURE.md` |
| **Explanation** | "Why is the system designed this way?" | `docs/engineering/architecture/` |
| **Reference** | "Give me the exact contracts, schemas, and routes." | `docs/engineering/specs/` |
| **How-to / Runbook**| "Help me complete, monitor, or recover a task." | `docs/operational/guides/`, `docs/OPERATIONAL_SOAK_RUNBOOK.md` |
| **Code Atlas** | "How does this mathematical algorithm or protocol work?" | `docs/atlas/` |

---

## Style & Invariant Rules
- Every page must declare Diátaxis Type, Status, and Owner.
- Mathematical equations must use valid MathJax $\LaTeX$ syntax ($...$ or $$...$$).
- State transitions and architectures must use GitHub-native Mermaid diagrams.
- No raw relative links to non-doc source files that break `mkdocs build --strict`.
