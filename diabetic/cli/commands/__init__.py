"""
diabetic.cli.commands — thin async handlers.

Each handler has the signature `async def handler(flags: dict) -> int` and
returns a process-style exit code (0 = success). Handlers contain no new
business logic: they reuse existing Bio-Quant code. Heavy imports are performed
lazily inside the handler bodies so importing this package (e.g. for the
manifest<->handler contract test) stays cheap and side-effect-free.
"""
