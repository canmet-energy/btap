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

    def test_collection_is_non_vacuous_and_covers_both_editions(self):
        records = coverage.collect_records(REPO_ROOT)
        self.assertGreater(len(records), 200)
        self.assertEqual({"2020", "2025"}, {row["edition"] for row in records})
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

    def test_implemented_negation_needs_a_row_level_disposition(self):
        records = coverage.collect_records(REPO_ROOT)
        mutated = [dict(row) for row in records]
        row = next(
            row for row in mutated
            if row["edition"] == "2020" and row["article"] == "8.4.2.2.(3)"
        )
        row["how"] = "the hourly requirement does not yet evaluate its inputs"
        with self.assertRaisesRegex(
            ValueError,
            r"8\.4\.2\.2\.\(3\).*how.*does not yet evaluate",
        ):
            coverage.validate_implemented_negations(mutated)

    def test_part3_cited_not_declared_is_rejected(self):
        records = coverage.collect_records(REPO_ROOT)
        citations = coverage.literal_part3_citations(REPO_ROOT)
        self.assertEqual(13, len(citations["3.2.3.3"]))
        mutated = [
            row for row in records
            if not (
                row["edition"] == "2020"
                and coverage.PART_3_ARTICLE.search(row["article"])
                and coverage.PART_3_ARTICLE.search(row["article"]).group(1) == "3.2.3.3"
            )
        ]
        with self.assertRaisesRegex(
            ValueError,
            r"NECB 2020 3\.2\.3\.3 cited at .*prescriptive\.py",
        ):
            coverage.validate_part3_declarations(mutated, citations)

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