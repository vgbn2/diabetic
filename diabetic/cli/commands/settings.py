"""
Settings handlers (read-only for now).

`show` dumps the pydantic config singleton via model_dump(), masking secret
fields. Writing settings is not yet implemented (config is env/.env-driven) —
tracked under Open Gaps in docs/engineering/tui_feature_map.md, not faked.
"""
import json

# Deny by default: only explicitly non-sensitive operational fields are shown.
# Newly added settings therefore remain masked until reviewed.
_SAFE_CONFIG_KEYS = {
    "AUTO_TRAIN_ENABLED",
    "BACKFILL_MAX_HOURS",
    "BIO_ENVIRONMENT",
    "BLE_RECONNECT_SECS",
    "CARDIAC_ENABLED",
    "DATA_POLLING_INTERVAL",
    "HUD_STALE_AFTER_SECS",
    "LIVE_HISTORY_HOURS",
    "LOCAL_GUI_ENABLED",
    "LOG_LEVEL",
    "MAINTENANCE_LOCAL_HOUR",
    "ML_WEIGHTS_VERSION",
    "PREFER_MMOL",
    "RETENTION_DAYS",
    "SAMPLING_INTERVAL_MINS",
    "TRAIN_STALE_DAYS",
    "TWA_AUTH_MAX_AGE_SECS",
    "USER_TIMEZONE",
    "WEATHER_ENABLED",
    "WEATHER_MOCK_MODE",
}


def _masked_config() -> dict:
    from diabetic.config import config

    data = config.model_dump()
    masked = {}
    for key, value in data.items():
        if key.upper() in _SAFE_CONFIG_KEYS:
            masked[key] = value
        else:
            masked[key] = "" if value in (None, "", 0, [], {}) else "***"
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
