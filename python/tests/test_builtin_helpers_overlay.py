"""Whitelist dispatch for ``run_builtin_helper`` (needs ``hermes/`` submodule on sys.path)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_HERMES = _REPO / "hermes"
_PYTHON = _REPO / "python"


def _ensure_paths() -> None:
    for p in (str(_HERMES), str(_PYTHON)):
        if p not in sys.path:
            sys.path.insert(0, p)


@unittest.skipUnless(_HERMES.is_dir() and (_HERMES / "tools" / "registry.py").is_file(), "hermes submodule missing")
class TestBuiltinHelpersOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ensure_paths()
        from overlays import builtin_helpers

        builtin_helpers.install()

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.ws = Path(self._td.name) / "w"
        self.ws.mkdir(parents=True, exist_ok=True)
        os.environ["HERMESDESK_WORKSPACE"] = str(self.ws.resolve())

    def tearDown(self) -> None:
        self._td.cleanup()
        os.environ.pop("HERMESDESK_WORKSPACE", None)

    def test_unknown_helper_returns_error_json(self) -> None:
        from overlays.builtin_helpers import _handle_run_builtin_helper

        raw = _handle_run_builtin_helper({"name": "os.system", "args": {}})
        data = json.loads(raw)
        self.assertIn("error", data)

    def test_folder_organize_dry_run_via_handler(self) -> None:
        from overlays.builtin_helpers import _handle_run_builtin_helper

        raw = _handle_run_builtin_helper({"name": "folder_organize", "args": {"folder": ".", "dry_run": True}})
        data = json.loads(raw)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("helper"), "folder_organize")


if __name__ == "__main__":
    unittest.main()
