"""Byte contract for the Python NECB gem-coverage generator."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT

SCRIPT = REPO_ROOT / "python" / "scripts" / "generate_necb_coverage.py"
SPEC = importlib.util.spec_from_file_location("generate_necb_coverage", SCRIPT)
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)


class TestGenerateNecbGemCoverage(unittest.TestCase):
    def test_python_inputs_generate_committed_bytes(self):
        committed = REPO_ROOT / "docs" / "NECB_COVERAGE.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "NECB_COVERAGE.md"
            result = coverage.main([
                "--manifest-root", str(REPO_ROOT),
                "--output", str(output),
            ])
            self.assertEqual(0, result)
            self.assertEqual(committed.read_bytes(), output.read_bytes())

    def test_collection_is_non_vacuous_and_covers_both_vintages(self):
        records = coverage.collect_records(REPO_ROOT)
        self.assertGreater(len(records), 200)
        self.assertEqual({"2020", "2025"}, {row["vintage"] for row in records})
        self.assertGreaterEqual(len({row["gem"] for row in records}), 6)
        self.assertTrue(all(row["article"] for row in records))
        refs = [
            ref
            for row in records
            for ref in (row["code"] if isinstance(row["code"], list) else [row["code"]])
            if ref
        ]
        self.assertTrue(refs)
        self.assertTrue(all(str(ref).startswith("python/btap/") for ref in refs))

    def test_python_is_the_only_input_authority(self):
        self.assertEqual(REPO_ROOT / "docs" / "NECB_COVERAGE.md", coverage.DEFAULT_OUTPUT)
        rendered = coverage.render(coverage.collect_records(REPO_ROOT))
        self.assertIn("python/scripts/generate_necb_coverage.py", rendered)
        self.assertNotRegex(rendered, r"btap-[^/]+/lib/")

    def test_stale_manifest_root_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "no coverage manifests found"):
                coverage.collect_records(Path(tmp))


if __name__ == "__main__":
    unittest.main()