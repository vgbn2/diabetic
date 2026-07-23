"""
diabetic/cli/tui/manifest.py

Declarative command registry — the single source of truth for *what* commands
exist, their flags, and their wiring status. Metadata only; no handler imports.
Routing lives in `diabetic/cli/dispatcher.py`. Mirrors the
`personal_finance_draft/backend/cli/tui/manifest.js` pattern.

Flag spec (per flag name, e.g. "--retention-days"):
    {
      "type":    "select" | "text" | "confirm",
      "label":   str,                       # prompt shown in the TUI
      "options": list[str],                 # select only
      "default": str | bool,                # text/confirm default
    }

Status legend (consumed by docs/engineering/tui_feature_map.md):
    "ok"      -> wired to a live handler, verified
    "partial" -> handler works but needs live infra / weights / creds
    "stub"    -> NOT ALLOWED (the contract test rejects this)
    "broken"  -> NOT ALLOWED
"""

CATEGORIES = [
    {"id": "op",       "label": "Operational Dashboard & Health"},
    {"id": "sim",      "label": "Simulation"},
    {"id": "admin",    "label": "Data & Admin"},
    {"id": "diag",     "label": "Diagnostics"},
    {"id": "ml",       "label": "Model Training"},
    {"id": "settings", "label": "Settings & Preferences"},
]

COMMANDS = {
    "op": [
        {
            "id": "status",
            "label": "Status (rich health dashboard)",
            "status": "ok",
            "flags": {"--json": {"type": "confirm", "label": "JSON output?", "default": False}},
            "notes": "Human-readable snapshot from get_system_health().",
        },
        {
            "id": "health",
            "label": "Health (machine-readable JSON)",
            "status": "ok",
            "notes": "Same data as status, always JSON. Mirrors finance `backend integrity --json`.",
        },
        {
            "id": "live",
            "label": "Live Service + HUD",
            "status": "partial",
            "long_running": True,
            "notes": "Launches the real service via `python -m diabetic.main live`. Needs full env.",
        },
    ],
    "sim": [
        {"id": "crash",  "label": "Hypoglycemic Crash scenario", "status": "ok"},
        {"id": "faint",  "label": "Hyperglycemic Faint-risk scenario", "status": "ok"},
        {"id": "normal", "label": "Normal metabolic stress test", "status": "ok"},
    ],
    "admin": [
        {
            "id": "export",
            "label": "Export 15-day sensor periods to CSV",
            "status": "partial",
            "notes": "Writes to storage/exports/. Needs MongoDB.",
        },
        {
            "id": "cleanup",
            "label": "Enforce retention policy",
            "status": "partial",
            "flags": {
                "--retention-days": {
                    "type": "text",
                    "default": "",
                    "label": "Retention days (blank = config.RETENTION_DAYS)",
                }
            },
            "notes": "Deletes data older than N days. Needs MongoDB.",
        },
    ],
    "diag": [
        {
            "id": "stress",
            "label": "Hot-Reload Inference Stress Test (100 iters)",
            "status": "partial",
            "notes": "Runs scripts.simulation.stress_scheduler. Cold-mode if weights absent.",
        },
    ],
    "ml": [
        {
            "id": "status",
            "label": "Last training result",
            "status": "ok",
            "notes": "Reads the local promotion manifest without starting training.",
        },
        {
            "id": "train",
            "label": "Train and promote a candidate",
            "status": "partial",
            "flags": {
                "--source": {
                    "type": "select",
                    "label": "Training source",
                    "options": ["mongo", "csv"],
                    "default": "mongo",
                },
                "--epochs": {
                    "type": "text",
                    "label": "Epochs",
                    "default": "20",
                },
            },
            "notes": "Serialized, validated, atomic promotion. Mongo needs real cardiac telemetry.",
        },
    ],
    "settings": [
        {
            "id": "show",
            "label": "Show Current Config (secrets masked)",
            "status": "ok",
            "flags": {"--json": {"type": "confirm", "label": "JSON output?", "default": False}},
            "notes": "Read-only dump of the pydantic config singleton.",
        },
    ],
}


def iter_commands():
    """Yield (category_id, command_id, spec) for every declared command."""
    for cat in CATEGORIES:
        for cmd in COMMANDS.get(cat["id"], []):
            yield cat["id"], cmd["id"], cmd


def command_ids():
    """Set of (category_id, command_id) declared in the manifest."""
    return {(cat_id, cmd_id) for cat_id, cmd_id, _ in iter_commands()}


def get_command(category_id, command_id):
    """Return the command spec dict, or None."""
    for cmd in COMMANDS.get(category_id, []):
        if cmd["id"] == command_id:
            return cmd
    return None
