"""Byte contract for the Python decisions TOC generator."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT

SCRIPT = REPO_ROOT / "python" / "scripts" / "generate_decisions_toc.py"
SPEC = importlib.util.spec_from_file_location("generate_decisions_toc", SCRIPT)
toc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(toc)


class TestGenerateDecisionsToc(unittest.TestCase):
    def test_current_document_is_byte_current(self):
        document = toc.DEFAULT_DOC.read_text(encoding="utf-8")
        self.assertEqual(document, toc.render(document, toc.DEFAULT_REGISTRY))

    def test_replaces_only_owned_region(self):
        source = "before\n" + toc.BEGIN_MARK + "\nstale\n" + toc.END_MARK + "\nafter\n"
        rendered = toc.render(source, toc.DEFAULT_REGISTRY)
        self.assertTrue(rendered.startswith("before\n" + toc.BEGIN_MARK))
        self.assertTrue(rendered.endswith(toc.END_MARK + "\nafter\n"))
        self.assertNotIn("\nstale\n", rendered)

    def test_check_reports_stale_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions.md"
            path.write_text("intro\n\n## D-01\nbody\n", encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(1, toc.main(["--check", "--doc", str(path)]))
            self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()