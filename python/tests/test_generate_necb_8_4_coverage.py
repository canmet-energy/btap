"""Byte contract and self-checks for the Python NECB 8.4 coverage generator."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT

SCRIPT = REPO_ROOT / "python" / "scripts" / "generate_necb_8_4_coverage.py"
SPEC = importlib.util.spec_from_file_location("generate_necb_8_4_coverage", SCRIPT)
coverage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = coverage
SPEC.loader.exec_module(coverage)


class TestGenerateNecb84Coverage(unittest.TestCase):
    def test_legacy_inputs_generate_committed_bytes(self):
        committed = REPO_ROOT / "btap-necb" / "docs" / "NECB_8_4_COVERAGE.html"
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / committed.name
            result = coverage.main([
                "--input-mode", "legacy-ruby",
                "--source-root", str(REPO_ROOT),
                "--manifest-root", str(REPO_ROOT),
                "--cache-2020", str(coverage.DEFAULT_CACHE_2020),
                "--cache-2025", str(coverage.DEFAULT_CACHE_2025),
                "--disposition", str(coverage.DEFAULT_DISPOSITION),
                "--output", str(output),
            ])
            self.assertEqual(0, result)
            self.assertEqual(committed.read_bytes(), output.read_bytes())

    def test_evidence_and_state_accounting_are_non_vacuous(self):
        generator = coverage.CoverageGenerator(coverage.Inputs())
        _html, parts = generator.render()
        self.assertGreater(len(generator.raw_citations), 50)
        for vintage, expected_articles in (("2020", 52), ("2025", 57)):
            part = parts[vintage]
            self.assertEqual(expected_articles, len(part["articles"]))
            self.assertEqual(expected_articles, sum(part["counts"].values()))
            self.assertGreater(sum(map(len, part["declarations"].values())), 40)
            self.assertGreater(sum(map(len, part["citations"].values())), 20)
            self.assertEqual(set(part["articles"]), set(part["states"]))

    def test_stale_source_root_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs = coverage.Inputs(source_root=Path(tmp))
            with self.assertRaisesRegex(ValueError, "RAW_CITATIONS is empty"):
                coverage.CoverageGenerator(inputs)


if __name__ == "__main__":
    unittest.main()