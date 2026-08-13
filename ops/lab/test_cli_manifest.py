"""
Contract tests for the structured CLI/TUI surface.

Fills the "medical has no CLI tests" gap noted in CROSS_PROJECT_LEARNINGS.md §4.
Institutionalizes the blast-through Surface Parity check: every manifest command
must map to a real dispatcher handler and vice versa, every handler must be a
coroutine function, and no command may be marked as a stub.
"""
import builtins
import inspect
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, call, patch

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


class TestCrossPlatformCliImports(unittest.TestCase):
    @staticmethod
    def _without_fcntl(source: str):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        bootstrap = textwrap.dedent(
            """
            import builtins
            original_import = builtins.__import__
            def guarded_import(name, *args, **kwargs):
                if name == "fcntl":
                    raise ModuleNotFoundError("No module named 'fcntl'")
                return original_import(name, *args, **kwargs)
            builtins.__import__ = guarded_import
            """
        )
        return subprocess.run(
            [sys.executable, "-c", bootstrap + source],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_settings_command_runs_when_fcntl_is_unavailable(self):
        result = self._without_fcntl(
            """
import asyncio
from diabetic.cli.dispatcher import dispatch
raise SystemExit(asyncio.run(dispatch("settings", "show", {"--json": True})))
"""
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"LOG_LEVEL"', result.stdout)

    def test_ml_status_runs_when_fcntl_is_unavailable(self):
        result = self._without_fcntl(
            """
import asyncio
from diabetic.cli.dispatcher import dispatch
raise SystemExit(asyncio.run(dispatch("ml", "status", {})))
"""
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"status"', result.stdout)

    def test_ml_train_reports_unavailable_lock_without_training(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        source = textwrap.dedent(
            """
            import asyncio
            import builtins
            import tempfile
            from pathlib import Path
            from unittest.mock import AsyncMock, patch
            from diabetic.cli.dispatcher import dispatch
            from diabetic.config import config
            from diabetic.ml_engine import training_service

            original_import = builtins.__import__
            def guarded_import(name, *args, **kwargs):
                if name in {"fcntl", "msvcrt"}:
                    raise ModuleNotFoundError(f"No module named '{name}'")
                return original_import(name, *args, **kwargs)

            async def main():
                with tempfile.TemporaryDirectory() as temporary, patch.object(
                    config,
                    "ML_WEIGHTS_PATH",
                    str(Path(temporary) / "weights.pth"),
                ), patch.object(
                    training_service,
                    "train_metabolic_cnn",
                    AsyncMock(side_effect=AssertionError("training started")),
                ), patch.object(builtins, "__import__", side_effect=guarded_import):
                    return await dispatch("ml", "train", {"--epochs": "1"})

            raise SystemExit(asyncio.run(main()))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", source],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("supported process file lock", result.stdout)
        self.assertNotIn("training started", result.stderr)

    def test_posix_training_lock_rejects_contention(self):
        from diabetic.ml_engine.training_service import _training_file_lock

        with tempfile.TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "training.lock"
            with _training_file_lock(lock_path):
                with self.assertRaisesRegex(RuntimeError, "another training process"):
                    with _training_file_lock(lock_path):
                        self.fail("contended lock entered critical section")

    def test_windows_directory_fsync_falls_back_without_o_directory(self):
        from diabetic.ml_engine import training_service

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            training_service.os,
            "O_DIRECTORY",
            None,
        ), patch.object(training_service.os, "open") as open_file:
            training_service._fsync_directory(Path(temporary))
        open_file.assert_not_called()

    def test_windows_training_lock_uses_one_byte_and_releases(self):
        from diabetic.ml_engine.training_service import _lock_training_stream

        fake_msvcrt = SimpleNamespace(
            LK_NBLCK=1,
            LK_UNLCK=2,
            locking=MagicMock(),
        )
        original_import = builtins.__import__

        def windows_import(name, *args, **kwargs):
            if name == "fcntl":
                raise ModuleNotFoundError("No module named 'fcntl'")
            if name == "msvcrt":
                return fake_msvcrt
            return original_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "training.lock"
            with path.open("a+", encoding="utf-8") as stream:
                with patch.object(builtins, "__import__", side_effect=windows_import):
                    release = _lock_training_stream(stream)
                    release()

        self.assertEqual(
            fake_msvcrt.locking.call_args_list,
            [
                call(ANY, fake_msvcrt.LK_NBLCK, 1),
                call(ANY, fake_msvcrt.LK_UNLCK, 1),
            ],
        )


if __name__ == "__main__":
    unittest.main()
