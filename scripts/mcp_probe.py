"""
scripts/mcp_probe.py

Lists the Bio-Quant MCP tools and verifies the server module imports cleanly,
without needing a full MCP client. Mirrors finance's `scripts/mcp_stdio_probe.js`.

Usage:
    python scripts/mcp_probe.py
"""
import pathlib
import sys

# Allow running as a bare script (`python scripts/mcp_probe.py`) from anywhere:
# put the repo root on sys.path so `diabetic` is importable.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from diabetic.mcp.server import TOOL_SPECS, bio_ping  # noqa: E402


def main() -> None:
    print("Bio-Quant MCP server — tool inventory")
    print("=" * 44)
    for spec in TOOL_SPECS:
        print(f"  - {spec['name']:<12} {spec['description']}")
    print("=" * 44)
    print("healthz (bio_ping):", bio_ping())
    print(f"\n{len(TOOL_SPECS)} tools registered. Server imports cleanly.")


if __name__ == "__main__":
    main()
