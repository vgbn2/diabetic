"""
Contract tests for the structured CLI/TUI surface.

Fills the "medical has no CLI tests" gap noted in CROSS_PROJECT_LEARNINGS.md §4.
Institutionalizes the blast-through Surface Parity check: every manifest command
must map to a real dispatcher handler and vice versa, every handler must be a
coroutine function, and no command may be marked as a stub.
"""
import inspect
import unittest

from diabetic.cli import dispatcher
from diabetic.cli.tui import manifest as M


class TestCliManifestParity(unittest.TestCase):
    def test_every_manifest_command_has_handler(self):
        registered = dispatcher.registered()
        for cat_id, cmd_id, _ in M.iter_commands():
            self.assertIn(
                (cat_id, cmd_id),
                registered,
                f"Manifest command ({cat_id}, {cmd_id}) has no dispatcher handler",
            )

    def test_no_orphan_handlers(self):
        manifest_ids = M.command_ids()
        for key in dispatcher.registered():
            self.assertIn(key, manifest_ids, f"Handler {key} has no manifest entry")

    def test_handlers_are_coroutine_functions(self):
        for key, fn in dispatcher.HANDLERS.items():
            self.assertTrue(
                inspect.iscoroutinefunction(fn),
                f"Handler {key} is not an async function",
            )

    def test_categories_unique(self):
        ids = [c["id"] for c in M.CATEGORIES]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate category id")

    def test_command_ids_unique_per_category(self):
        for cat_id, cmds in M.COMMANDS.items():
            ids = [c["id"] for c in cmds]
            self.assertEqual(len(ids), len(set(ids)), f"Duplicate command id in {cat_id}")

    def test_every_command_category_is_declared(self):
        cat_ids = {c["id"] for c in M.CATEGORIES}
        for cat_id in M.COMMANDS:
            self.assertIn(cat_id, cat_ids, f"COMMANDS has undeclared category {cat_id}")

    def test_no_stub_or_broken_status(self):
        """Audit ethos: the manifest must not advertise stub/broken commands."""
        for cat_id, cmd_id, spec in M.iter_commands():
            self.assertNotIn(
                spec.get("status"),
                ("stub", "broken"),
                f"({cat_id}, {cmd_id}) is marked {spec.get('status')!r}",
            )

    def test_flag_specs_are_well_formed(self):
        valid_types = {"select", "text", "confirm"}
        for cat_id, cmd_id, spec in M.iter_commands():
            for name, fspec in (spec.get("flags") or {}).items():
                self.assertTrue(name.startswith("--"), f"{cat_id}.{cmd_id}: flag {name} missing -- prefix")
                self.assertIn(fspec.get("type"), valid_types, f"{cat_id}.{cmd_id}: bad flag type for {name}")
                if fspec.get("type") == "select":
                    self.assertTrue(fspec.get("options"), f"{cat_id}.{cmd_id}: select {name} has no options")


if __name__ == "__main__":
    unittest.main()
