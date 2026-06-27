"""Simulation handlers — reuse diabetic.main.run_simulation (main.py:24)."""


async def crash(flags: dict) -> int:
    from diabetic.main import run_simulation
    await run_simulation("crash")
    return 0


async def faint(flags: dict) -> int:
    from diabetic.main import run_simulation
    await run_simulation("faint")
    return 0


async def normal(flags: dict) -> int:
    from diabetic.main import run_simulation
    await run_simulation("normal")
    return 0
