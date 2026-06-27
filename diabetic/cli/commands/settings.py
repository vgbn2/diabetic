"""
Settings handlers (read-only for now).

`show` dumps the pydantic config singleton via model_dump(), masking secret
fields. Writing settings is not yet implemented (config is env/.env-driven) —
tracked under Open Gaps in docs/engineering/tui_feature_map.md, not faked.
"""
import json

# Field names whose values must never be printed in full.
_SECRET_KEYS = {
    "API_SECRET",
    "TELEGRAM_TOKEN",
    "MONGO_URI",
    "MONGODB_URI",
    "USER_ID",
    "NIGHTSCOUT_API_SECRET",
}


def _masked_config() -> dict:
    from diabetic.config import config

    data = config.model_dump()
    masked = {}
    for key, value in data.items():
        if key.upper() in _SECRET_KEYS and value not in (None, "", 0):
            masked[key] = "***"
        else:
            masked[key] = value
    return masked


async def show(flags: dict) -> int:
    data = _masked_config()
    if flags.get("--json"):
        print(json.dumps(data, indent=2, default=str))
        return 0

    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Bio-Quant Configuration (secrets masked)", expand=True)
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    for key in sorted(data):
        table.add_row(key, str(data[key]))
    console.print(table)
    return 0
