"""
Contract tests for the Bio-Quant MCP server.

Mirrors the CLI manifest parity tests: the declared tool registry must match
what FastMCP knows about, every tool must be callable and `bio_*`-namespaced,
the config tool must mask secrets, and bio_ping must report a sane shape.
"""
import inspect
import unittest

from diabetic.mcp import server as S


class TestMcpTools(unittest.TestCase):
    EXPECTED = {"bio_ping", "bio_health", "bio_config"}

    def test_expected_tools_registered(self):
        names = {spec["name"] for spec in S.TOOL_SPECS}
        self.assertSetEqual(names, self.EXPECTED)

    def test_tool_specs_well_formed(self):
        for spec in S.TOOL_SPECS:
            self.assertTrue(spec["name"].startswith("bio_"), f"{spec['name']} not bio_-namespaced")
            self.assertTrue(callable(spec["fn"]), f"{spec['name']} fn not callable")
            self.assertTrue(spec["description"], f"{spec['name']} missing description")

    def test_tool_names_unique(self):
        names = [spec["name"] for spec in S.TOOL_SPECS]
        self.assertEqual(len(names), len(set(names)))

    def test_bio_ping_shape(self):
        out = S.bio_ping()
        self.assertTrue(out["ok"])
        self.assertEqual(out["service"], "bio-quant")
        self.assertEqual(set(out["tools"]), self.EXPECTED)

    def test_bio_config_masks_secrets(self):
        cfg = S.bio_config()
        self.assertIn("NIGHTSCOUT_URL", cfg)  # sanity: real config returned
        if cfg.get("API_SECRET"):
            self.assertEqual(cfg["API_SECRET"], "***", "API_SECRET must be masked")

    def test_bio_health_is_coroutine(self):
        self.assertTrue(inspect.iscoroutinefunction(S.bio_health))


if __name__ == "__main__":
    unittest.main()
