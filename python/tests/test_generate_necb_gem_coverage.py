"""Byte contract for the Python NECB gem-coverage generator."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT

SCRIPT = REPO_ROOT / "python" / "scripts" / "generate_necb_gem_coverage.py"
SPEC = importlib.util.spec_from_file_location("generate_necb_gem_coverage", SCRIPT)
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)


class TestGenerateNecbGemCoverage(unittest.TestCase):
    def test_legacy_inputs_generate_committed_bytes(self):
        committed = REPO_ROOT / "btap-necb" / "docs" / "NECB_GEM_COVERAGE.md"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / committed.name
            result = coverage.main([
                "--input-mode", "legacy-ruby",
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

    def test_stale_manifest_root_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "no coverage manifests found"):
                coverage.collect_records(Path(tmp))


if __name__ == "__main__":
    unittest.main()