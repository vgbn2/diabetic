"""
diabetic.cli — Structured CLI/TUI surface for Bio-Quant.

Mirrors the personal_finance_draft `backend/cli/` pattern:
- `tui/manifest.py`  : declarative command registry (the "what")
- `dispatcher.py`    : routing from (category, command) -> async handler (the "how")
- `commands/`        : thin handlers that reuse existing Bio-Quant code
- `tui/engine.py`    : rich interactive menu driven by the manifest

Entry points:
    python -m diabetic.cli <category> <command> [--flag value]   # one-shot CLI
    python -m diabetic.cli.tui                                   # interactive TUI
"""
