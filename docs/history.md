# Documentation History And Recovery

The active project documentation is intentionally small:

- `README.md` explains installation and the supported entrypoints.
- `docs/architecture.md` and `docs/engineering/architecture.md` describe the
  executable design.
- `docs/local-nightscout.md` is the local deployment and migration runbook.
- `workspace/HANDOFF.md`, `workspace/STATE.md`, and
  `workspace/SESSION_MEMORY.md` carry current session truth.
- `workspace/DEV_REVIEW.md` and `workspace/REVIEW_LEDGER.md` carry audit
  findings and grades.

## Retired GSD Archive

The former `.gsd/` planning system and the flattened
`storage/archive/docs/` copy are retired. They conflicted with the current
workspace files and contained obsolete production-readiness claims.

Fifty-four flattened archive documents are recoverable from Git history. For
example:

```bash
git show cf2262d0:.gsd/docs/ARCHITECTURE.md
git show cf2262d0:.gsd/phases/9/03-SUMMARY.md
git show da59f8b:.gsd/STATE.md
```

Two local-only notes, `diabetic_dsp_verify.md` and
`diabetic_ingestion_verify.md`, were not retained verbatim. Their March 2026
claims were superseded by the current clinical-contract tests and review
ledger. In particular, the old ingestion note described magnitude-based unit
detection and a CSV-capable simulation reader, both of which are no longer
valid contracts.

## Audit Policy

Per-folder `AUDIT.md` snapshots are retired because they drifted independently
and repeatedly labelled incomplete paths `SOLID`. New findings belong in
`workspace/DEV_REVIEW.md`; grade changes belong in
`workspace/REVIEW_LEDGER.md`. Git history remains the archive for removed
snapshots.
