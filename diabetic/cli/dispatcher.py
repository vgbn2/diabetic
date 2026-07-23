"""
diabetic/cli/dispatcher.py

Routing layer — maps (category_id, command_id) -> async handler. This is the
Python analogue of personal_finance_draft's `backend/cli/sovereign_cli.js`:
the manifest declares the metadata, the dispatcher owns the wiring.

One-shot CLI usage:
    python -m diabetic.cli <category> <command> [--flag value] [--bool-flag]
e.g.
    python -m diabetic.cli settings show --json
    python -m diabetic.cli admin cleanup --retention-days 90
"""
import sys

from diabetic.cli.commands import admin, diagnostics, health, ml, settings, simulation
from diabetic.cli.tui import manifest as M

# (category_id, command_id) -> async handler(flags: dict) -> int
HANDLERS = {
    ("op", "status"): health.status,
    ("op", "health"): health.health,
    ("op", "live"): health.live,
    ("sim", "crash"): simulation.crash,
    ("sim", "faint"): simulation.faint,
    ("sim", "normal"): simulation.normal,
    ("admin", "export"): admin.export,
    ("admin", "cleanup"): admin.cleanup,
    ("diag", "stress"): diagnostics.stress,
    ("ml", "train"): ml.train,
    ("ml", "status"): ml.status,
    ("settings", "show"): settings.show,
}


def registered():
    """Set of (category_id, command_id) that have a wired handler."""
    return set(HANDLERS.keys())


async def dispatch(category: str, command: str, flags: dict | None = None) -> int:
    """Invoke the handler for (category, command). Raises KeyError if unwired."""
    handler = HANDLERS.get((category, command))
    if handler is None:
        raise KeyError(f"No handler for ({category!r}, {command!r})")
    result = await handler(flags or {})
    return result if isinstance(result, int) else 0


def _parse_argv(argv: list[str]):
    """Parse [category, command, --flag, value, --bool, ...] -> (cat, cmd, flags)."""
    if len(argv) < 2:
        return None, None, {}
    category, command = argv[0], argv[1]
    flags: dict = {}
    rest = argv[2:]
    i = 0
    while i < len(rest):
        token = rest[i]
        if token.startswith("--"):
            if i + 1 < len(rest) and not rest[i + 1].startswith("--"):
                flags[token] = rest[i + 1]
                i += 2
            else:
                flags[token] = True  # bare boolean flag
                i += 1
        else:
            i += 1
    return category, command, flags


def _print_usage():
    print("Usage: python -m diabetic.cli <category> <command> [--flag value]\n")
    for cat in M.CATEGORIES:
        cmds = ", ".join(c["id"] for c in M.COMMANDS.get(cat["id"], []))
        print(f"  {cat['id']:<10} ({cat['label']}): {cmds}")
    print("\nInteractive menu: python -m diabetic.cli.tui")


async def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    category, command, flags = _parse_argv(argv)
    if not category or not command:
        _print_usage()
        return 2
    try:
        return await dispatch(category, command, flags)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        _print_usage()
        return 2
