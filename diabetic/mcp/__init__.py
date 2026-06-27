"""
diabetic.mcp — Model Context Protocol server for Bio-Quant.

Exposes read-only `bio_*` tools (system health, masked config) to Claude over
stdio, mirroring the personal_finance_draft MCP pattern (CROSS_PROJECT_LEARNINGS
§5). Tools are thin wrappers that reuse existing Bio-Quant code — no new
business logic. Mutating tools (when added) must call an auth gate first.

Run:
    python -m diabetic.mcp        # stdio MCP server
    python scripts/mcp_probe.py   # list tools without a client
"""
