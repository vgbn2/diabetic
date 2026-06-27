"""
diabetic/cli/tui/engine.py

Interactive rich TUI driven by the manifest — the Python analogue of
personal_finance_draft's `backend/cli/tui/engine/engine.js`, kept proportionate
to this project. Navigation uses numbered selection via rich.prompt (robust on
the win32 shell) rather than raw-tty arrow keys.

Flow:  header → category picker → command picker (status badges) →
       per-flag prompts (select/text/confirm) → dispatcher.dispatch() → repeat.
       [b] back · [q] quit.
"""
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from diabetic.cli import dispatcher
from diabetic.cli.tui import manifest as M

console = Console()

_STATUS_BADGE = {
    "ok": "[green]OK[/]",
    "partial": "[yellow]~[/]",
    "stub": "[red]![/]",
    "broken": "[red]X[/]",
}


class _Quit(Exception):
    """Raised from a nested menu to unwind to the top-level loop and exit."""


def _header() -> None:
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")
    grid.add_row(
        "[bold cyan]BIO-QUANT[/]  ·  CLI / TUI",
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )
    console.print(Panel(grid, style="white on blue"))


def _select(label: str, options: list) -> str:
    """Numbered single-select. Options may be strings or {'label','value'} dicts."""
    table = Table(title=label, expand=True)
    table.add_column("#", style="cyan", width=4)
    table.add_column("Option")
    for idx, opt in enumerate(options, 1):
        text = opt["label"] if isinstance(opt, dict) else str(opt)
        table.add_row(str(idx), text)
    console.print(table)
    while True:
        choice = Prompt.ask(label, default="1")
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            opt = options[int(choice) - 1]
            return opt["value"] if isinstance(opt, dict) else opt


def _collect_flags(cmd: dict) -> dict:
    flags: dict = {}
    for name, spec in (cmd.get("flags") or {}).items():
        ftype = spec.get("type", "text")
        label = spec.get("label", name)
        if ftype == "confirm":
            flags[name] = Confirm.ask(label, default=bool(spec.get("default", False)))
        elif ftype == "select":
            flags[name] = _select(label, spec.get("options", []))
        else:  # text
            flags[name] = Prompt.ask(label, default=str(spec.get("default", "")))
    return flags


async def _execute(category_id: str, cmd: dict) -> None:
    flags = _collect_flags(cmd)
    console.rule(f"[bold]{cmd['label']}")
    if cmd.get("long_running"):
        console.print("[yellow]Long-running command — it may take over the terminal. Ctrl-C to stop.[/]")
    try:
        rc = await dispatcher.dispatch(category_id, cmd["id"], flags)
        console.print("[green]Done.[/]" if rc == 0 else f"[red]Exited with code {rc}.[/]")
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/]")
    except SystemExit as exc:
        console.print(f"[yellow]Command requested exit (code {exc.code}).[/]")
    except Exception as exc:  # noqa: BLE001 — surface any handler failure to the operator
        console.print(f"[red]Error: {exc.__class__.__name__}: {exc}[/]")
    Prompt.ask("[dim]Press Enter to continue[/]", default="")


async def _command_menu(category: dict) -> None:
    cmds = M.COMMANDS.get(category["id"], [])
    while True:
        console.clear()
        _header()
        table = Table(title=category["label"], expand=True)
        table.add_column("#", style="cyan", width=4)
        table.add_column("", width=4)
        table.add_column("Command")
        table.add_column("Notes", style="dim")
        for idx, cmd in enumerate(cmds, 1):
            table.add_row(
                str(idx),
                _STATUS_BADGE.get(cmd.get("status", ""), ""),
                cmd["label"],
                cmd.get("notes", ""),
            )
        console.print(table)
        choice = Prompt.ask("Command (number, b=back, q=quit)", default="b").strip().lower()
        if choice in ("b", "back"):
            return
        if choice in ("q", "quit", "exit"):
            raise _Quit()
        if choice.isdigit() and 1 <= int(choice) <= len(cmds):
            await _execute(category["id"], cmds[int(choice) - 1])


async def run() -> None:
    """Top-level interactive loop. Returns when the user quits."""
    try:
        while True:
            console.clear()
            _header()
            table = Table(title="Select Category", expand=True)
            table.add_column("#", style="cyan", width=4)
            table.add_column("Category")
            for idx, cat in enumerate(M.CATEGORIES, 1):
                table.add_row(str(idx), cat["label"])
            console.print(table)
            choice = Prompt.ask("Category (number, q=quit)", default="q").strip().lower()
            if choice in ("q", "quit", "exit"):
                break
            if choice.isdigit() and 1 <= int(choice) <= len(M.CATEGORIES):
                await _command_menu(M.CATEGORIES[int(choice) - 1])
    except _Quit:
        pass
    console.print("[dim]Goodbye.[/]")
