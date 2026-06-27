"""
diabetic/mcp/server.py

Bio-Quant MCP server (FastMCP, stdio transport). Registers read-only `bio_*`
tools that reuse existing code. Tool functions are kept as importable
module-level callables (registered via `add_tool`) so they can be unit-tested
directly without an MCP client.

Namespacing: tool names are `bio_*` per CROSS_PROJECT_LEARNINGS §5.
DB-agnostic: tools read through `get_system_health()` / config, so a future
MongoDB→Supabase migration does not change this surface.
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("bio-quant")


# --- tool implementations (thin; reuse existing Bio-Quant code) --------------

def bio_ping() -> dict:
    """Liveness probe — confirms the Bio-Quant MCP server is up and lists tools."""
    return {
        "ok": True,
        "service": "bio-quant",
        "tools": [spec["name"] for spec in TOOL_SPECS],
    }


async def bio_health() -> dict:
    """System health snapshot: Nightscout, MongoDB, ML weights, snapshot buffer,
    and last-reading freshness. Read-only, side-effect-free."""
    from diabetic.utils.health import get_system_health
    return await get_system_health()


def bio_config() -> dict:
    """Current Bio-Quant configuration with secret fields masked. Read-only."""
    from diabetic.cli.commands.settings import _masked_config
    return _masked_config()


# --- registry (single source of truth for tools; used by the probe + tests) --

TOOL_SPECS = [
    {"name": "bio_ping",   "fn": bio_ping,   "description": "Liveness probe; lists registered tools."},
    {"name": "bio_health", "fn": bio_health, "description": "System health snapshot (read-only)."},
    {"name": "bio_config", "fn": bio_config, "description": "Configuration dump with secrets masked (read-only)."},
]

for _spec in TOOL_SPECS:
    mcp.add_tool(_spec["fn"], name=_spec["name"], description=_spec["description"])


def main() -> None:
    """Run the server over stdio (the transport Claude Desktop / Code expect)."""
    mcp.run()


if __name__ == "__main__":
    main()
