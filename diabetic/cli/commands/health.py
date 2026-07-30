"""
Operational & Health handlers.

`status` and `health` both render diabetic.utils.health.get_system_health():
status is human-readable (rich table) with an optional --json toggle; health is
always JSON. `live` launches the real service through its own entrypoint so the
singleton lock + boot validation + HUD all run exactly as in production.
"""
import json


async def _snapshot() -> dict:
    from diabetic.utils.health import get_system_health
    return await get_system_health()


async def health(flags: dict) -> int:
    snap = await _snapshot()
    print(json.dumps(snap, indent=2, default=str))
    return 0


async def status(flags: dict) -> int:
    snap = await _snapshot()
    if flags.get("--json"):
        print(json.dumps(snap, indent=2, default=str))
        return 0

    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Bio-Quant System Status", expand=True)
    table.add_column("Subsystem", style="cyan")
    table.add_column("Value")

    mw = snap.get("ml_weights") or {}
    table.add_row("Nightscout", str(snap.get("nightscout")))
    table.add_row("MongoDB", str(snap.get("mongodb")))
    table.add_row(
        "ML Weights",
        f"{mw.get('version')}  ·  {mw.get('status')}  ·  age {mw.get('age_days')}d",
    )
    table.add_row("Snapshot Buffer", str(snap.get("snapshot_buffer")))
    table.add_row("Inference Active", str(snap.get("inference_active")))
    table.add_row("Core Ready", str(snap.get("ready")))
    table.add_row("Neural Ready", str(snap.get("neural_ready")))
    table.add_row("Last Reading", str(snap.get("last_reading_ts")))
    table.add_row("Last Reading Age (min)", str(snap.get("last_reading_age_mins")))
    table.add_row("Readiness Reasons", ", ".join(snap.get("readiness_reasons") or []))
    treatment = snap.get("treatments") or {}
    table.add_row(
        "Treatments",
        f"{treatment.get('state')} ({treatment.get('source') or 'none'})",
    )
    console.print(table)
    return 0


async def live(flags: dict) -> int:
    import subprocess
    import sys

    # Run through the real service entrypoint (lock file, validate_config, HUD).
    proc = subprocess.run([sys.executable, "-m", "diabetic.main", "live"])
    return proc.returncode
