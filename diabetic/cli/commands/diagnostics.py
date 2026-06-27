"""Diagnostics handlers — reuse the Phase 5 hot-reload stress harness."""


async def stress(flags: dict) -> int:
    # scripts.simulation.stress_scheduler.main raises SystemExit(1) on failure
    # and prints its own PASS/FAIL report.
    from scripts.simulation.stress_scheduler import main as stress_main
    await stress_main()
    return 0
