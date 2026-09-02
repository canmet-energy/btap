import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from btap.necb import coverage


class TestCoverageReference(unittest.TestCase):
    def test_editions_articles_and_provenance(self):
        self.assertEqual(("2020", "2025"), coverage.editions())
        for edition, expected_count in (("2020", 52), ("2025", 57)):
            numbers = coverage.article_numbers(edition)
            self.assertEqual(expected_count, len(numbers))
            self.assertEqual("8.4.1.1", numbers[0])
            article = coverage.get_article(edition, numbers[0])
            self.assertEqual("General", article["title"])
            self.assertTrue(article["raw"].startswith("1)"))
            self.assertEqual(edition, coverage.provenance(edition)["edition"])

    def test_invalid_edition_and_article_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, "unsupported NECB edition"):
            coverage.article_numbers("2017")
        with self.assertRaisesRegex(ValueError, "is not included"):
            coverage.get_article("2025", "8.4.99.99")

    def test_disposition_and_attribution_are_packaged_references(self):
        document = coverage.disposition()
        self.assertIn("provenance", document)
        self.assertEqual(document["dispositions"], coverage.dispositions())
        self.assertEqual("modeller", coverage.disposition("8.4.1.3")["category"])
        self.assertIsNone(coverage.disposition("8.4.1.1"))
        notice = coverage.attribution()
        self.assertIn("National Energy Code of Canada for Buildings", notice)
        self.assertIn("Crown copyright", notice)
        self.assertIn("not licensed under", notice)


class TestCoverageCLI(unittest.TestCase):
    def run_cli(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        code = coverage.main(list(args), out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def test_list_and_get_support_text_and_json(self):
        code, text, err = self.run_cli("list", "2020")
        self.assertEqual(0, code, err)
        self.assertEqual(52, len(text.splitlines()))

        code, text, err = self.run_cli("get", "2025", "8.4.1.1")
        self.assertEqual(0, code, err)
        self.assertTrue(text.startswith("1)"))

        code, text, err = self.run_cli(
            "get", "2025", "8.4.1.1", "--format", "json"
        )
        self.assertEqual(0, code, err)
        self.assertEqual("General", json.loads(text)["title"])

    def test_missing_article_is_a_cli_error(self):
        code, _, err = self.run_cli("get", "2025", "8.4.99.99")
        self.assertEqual(2, code)
        self.assertIn("is not included", err)

    def test_fetch_delegates_to_the_maintainer_script_with_explicit_output(self):
        destination = Path("/tmp/necb-coverage-test.json")
        completed = subprocess.CompletedProcess([], 0)
        with patch("btap.necb.coverage.subprocess.run", return_value=completed) as run:
            code, _, err = self.run_cli(
                "fetch", "2020", "--out", str(destination)
            )
        self.assertEqual(0, code, err)
        command = run.call_args.args[0]
        self.assertEqual(sys.executable, command[0])
        self.assertEqual(["--edition", "2020", "--out", str(destination)], command[-4:])

    def test_module_help_works(self):
        proc = subprocess.run(
            [sys.executable, "-m", "btap.necb.coverage", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("get", proc.stdout)
        self.assertIn("fetch", proc.stdout)


if __name__ == "__main__":
    unittest.main()