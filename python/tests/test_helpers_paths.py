"""Path safety for HermesDesk builtin helpers (no full agent runtime)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Repo layout: python/helpers, python/tests
_PY_ROOT = Path(__file__).resolve().parents[1]
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))


class TestBuiltinHelperPaths(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.ws = Path(self._td.name) / "w"
        self.ws.mkdir(parents=True, exist_ok=True)
        os.environ["HERMESDESK_WORKSPACE"] = str(self.ws.resolve())

    def tearDown(self) -> None:
        self._td.cleanup()
        os.environ.pop("HERMESDESK_WORKSPACE", None)

    def test_folder_organize_rejects_escape(self) -> None:
        from helpers.folder_organize import run

        r = run({"folder": ".."})
        self.assertFalse(r.get("ok"))

    def test_excel_to_word_rejects_escape(self) -> None:
        from helpers.excel_to_word import run

        r = run({"excel_path": "../outside.xlsx"})
        self.assertFalse(r.get("ok"))

    def test_excel_to_word_requires_path(self) -> None:
        from helpers.excel_to_word import run

        r = run({"excel_path": "  "})
        self.assertFalse(r.get("ok"))

    def test_pdf_digest_rejects_escape(self) -> None:
        from helpers.pdf_digest import run

        r = run({"folder": ".."})
        self.assertFalse(r.get("ok"))

    def test_image_batch_rejects_escape(self) -> None:
        from helpers.image_batch import run

        r = run({"folder": "..", "action": "info"})
        self.assertFalse(r.get("ok"))

    def test_folder_organize_dry_run_ok_empty(self) -> None:
        from helpers.folder_organize import run

        r = run({"folder": ".", "dry_run": True})
        self.assertTrue(r.get("ok"))
        self.assertTrue(r.get("dry_run"))
        self.assertIsInstance(r.get("planned"), list)


if __name__ == "__main__":
    unittest.main()
