"""Tests for scripts/fetch_necb_8_4_text.py — parsing, sanity checks, cache output.

Includes mocked MCP protocol tests (no key required) and parse verification
tests using realistic article text samples.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT / "scripts"))

# Import the script module
import fetch_necb_8_4_text as script  # noqa: E402


class TestArticleParsing(unittest.TestCase):
    """Parse verification: sentence/clause tree extraction with sanity checks."""

    def test_simple_article(self):
        """Simple article with sentences only."""
        record = {
            "full_text": (
                "8.4.3.2. Title\n"
                "1) First sentence.\n"
                "2) Second sentence.\n"
            ),
            "title": "Test Article",
            "page_start": 8,
            "page_end": 8,
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertTrue(parsed["parse_ok"])
        self.assertEqual(len(parsed["sentences"]), 2)
        self.assertEqual(parsed["sentences"][0]["num"], 1)
        self.assertEqual(parsed["sentences"][0]["text"], "First sentence.")
        self.assertEqual(parsed["sentences"][1]["num"], 2)
        self.assertEqual(parsed["sentences"][1]["text"], "Second sentence.")

    def test_article_with_clauses(self):
        """Article with clauses under sentences."""
        record = {
            "full_text": (
                "8.4.3.2. Title\n"
                "1) The sentence:\n"
                "  a) first clause,\n"
                "  b) second clause, and\n"
                "  c) third clause.\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertTrue(parsed["parse_ok"])
        self.assertEqual(len(parsed["sentences"]), 1)
        self.assertEqual(len(parsed["sentences"][0]["clauses"]), 3)
        self.assertEqual(parsed["sentences"][0]["clauses"][0]["id"], "a")
        self.assertEqual(parsed["sentences"][0]["clauses"][1]["id"], "b")
        self.assertEqual(parsed["sentences"][0]["clauses"][2]["id"], "c")

    def test_article_with_roman_subclauses(self):
        """Article with roman numeral subclauses."""
        record = {
            "full_text": (
                "8.4.5.13. Title\n"
                "1) Sentence:\n"
                "  a) clause:\n"
                "    i) first subclause,\n"
                "    ii) second subclause, and\n"
                "    iii) third subclause.\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.5.13", record)

        self.assertTrue(parsed["parse_ok"])
        self.assertEqual(len(parsed["sentences"][0]["clauses"]), 1)
        clause = parsed["sentences"][0]["clauses"][0]
        self.assertEqual(len(clause["subclauses"]), 3)
        self.assertEqual(clause["subclauses"][0]["id"], "i")
        self.assertEqual(clause["subclauses"][1]["id"], "ii")
        self.assertEqual(clause["subclauses"][2]["id"], "iii")

    def test_line_continuation(self):
        """Lines without sentence/clause markers continue previous text."""
        record = {
            "full_text": (
                "8.4.3.2. Title\n"
                "1) This sentence spans\n"
                "multiple lines and should be\n"
                "joined together.\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertTrue(parsed["parse_ok"])
        self.assertEqual(
            parsed["sentences"][0]["text"],
            "This sentence spans multiple lines and should be joined together."
        )

    def test_furniture_stripping(self):
        """Document furniture is stripped."""
        record = {
            "full_text": (
                "National Energy Code of Canada for Buildings 2025\n"
                "Division B\n"
                "8-42    Division B\n"
                "© His Majesty the King in Right of Canada, 2024\n"
                "42\n"
                "8.4.3.2. Title\n"
                "8.4.3.2.\n"  # running header
                "1) The sentence.\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertTrue(parsed["parse_ok"])
        self.assertEqual(len(parsed["sentences"]), 1)

    def test_preamble_notes(self):
        """Code notes before sentence 1 are captured."""
        record = {
            "full_text": (
                "8.4.3.2. Title\n"
                "(See Sentence 8.4.3.3.(1) for additional requirements.)\n"
                "(See Article 8.4.3.5. for exceptions.)\n"
                "1) The sentence.\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertTrue(parsed["parse_ok"])
        self.assertEqual(len(parsed["preamble_notes"]), 2)
        self.assertTrue(parsed["preamble_notes"][0].startswith("(See Sentence"))

    def test_trailing_heading_trim(self):
        """Trailing subsection heading bleed is trimmed."""
        record = {
            "full_text": (
                "8.4.3.2. Title\n"
                "1) Sentence ends here. Interior Lighting\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertTrue(parsed["parse_ok"])
        self.assertEqual(parsed["sentences"][0]["text"], "Sentence ends here.")

    def test_embedded_article_rejection(self):
        """Article with embedded start of different article is rejected."""
        record = {
            "full_text": (
                "8.4.3.2. Title\n"
                "1) First sentence.\n"
                "8.4.3.3.\n"
                "Next Article Title\n"
                "1) Embedded article start.\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertFalse(parsed["parse_ok"])
        self.assertIn("embedded start", parsed["reason"])
        self.assertIn("8.4.3.3", parsed["reason"])

    def test_no_sentences_rejection(self):
        """Article with no sentences is rejected."""
        record = {
            "full_text": (
                "8.4.3.2. Title\n"
                "Just some preamble text without sentences.\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertFalse(parsed["parse_ok"])
        self.assertEqual(parsed["reason"], "no sentences found")

    def test_first_sentence_not_one_rejection(self):
        """Article not starting with sentence 1 is rejected."""
        record = {
            "full_text": (
                "8.4.3.2. Title\n"
                "2) Second sentence comes first.\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertFalse(parsed["parse_ok"])
        self.assertIn("first sentence is 2)", parsed["reason"])

    def test_non_contiguous_sentences_rejection(self):
        """Article with non-contiguous sentence numbers is rejected."""
        record = {
            "full_text": (
                "8.4.3.2. Title\n"
                "1) First sentence.\n"
                "2) Second sentence.\n"
                "4) Fourth sentence (skipped 3).\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertFalse(parsed["parse_ok"])
        self.assertIn("not contiguous", parsed["reason"])
        self.assertIn("1,2,4", parsed["reason"])

    def test_clause_i_vs_roman_numeral_disambiguation(self):
        """An unexpected i) after clause b is a roman subclause."""
        record = {
            "full_text": (
                "8.4.3.2. Title\n"
                "1) Sentence:\n"
                "  a) clause a,\n"
                "  b) clause b:\n"
                "    i) subclause under b.\n"
            ),
            "title": "Test",
            "equations": []
        }

        parsed = script.parse_article("8.4.3.2", record)

        self.assertTrue(parsed["parse_ok"])
        clauses = parsed["sentences"][0]["clauses"]

        self.assertEqual(clauses[1]["id"], "b")
        self.assertEqual(len(clauses[1]["subclauses"]), 1)
        self.assertEqual(clauses[1]["subclauses"][0]["id"], "i")


class TestMCPIntegration(unittest.TestCase):
    """Mocked MCP calls: no key required, verify request/response handling."""

    @patch("fetch_necb_8_4_text.MCPClient")
    def test_get_section_request(self, mock_client_class):
        """get_section makes correct MCP call."""
        mock_client = Mock()
        mock_client.call.return_value = {
            "title": "Test Article",
            "full_text": "1) Sentence.",
            "page_start": 8,
            "page_end": 8,
            "equations": []
        }
        mock_client_class.return_value = mock_client

        client = script.MCPClient("codes")
        result = script.get_section(client, "8.4.3.2", "2025")

        mock_client.call.assert_called_once_with(
            "get_section",
            {
                "code": "necb",
                "edition": "2025",
                "division": "B",
                "section_number": "8.4.3.2",
                "include_sentences": False
            }
        )
        self.assertEqual(result["title"], "Test Article")

    @patch("fetch_necb_8_4_text.MCPClient")
    def test_edition_2020_articles(self, mock_client_class):
        """2020 edition uses correct article list."""
        self.assertEqual(len(script.ARTICLES_2020), 52)
        self.assertIn("8.4.4.1", script.ARTICLES_2020)
        self.assertIn("8.4.4.20", script.ARTICLES_2020)
        self.assertNotIn("8.4.4.21", script.ARTICLES_2020)
        self.assertNotIn("8.4.6.1", script.ARTICLES_2020)

    @patch("fetch_necb_8_4_text.MCPClient")
    def test_edition_2025_articles(self, mock_client_class):
        """2025 edition uses correct article list."""
        self.assertEqual(len(script.ARTICLES_2025), 57)
        self.assertIn("8.4.4.1", script.ARTICLES_2025)
        self.assertIn("8.4.4.2", script.ARTICLES_2025)
        self.assertNotIn("8.4.4.3", script.ARTICLES_2025)
        self.assertIn("8.4.5.20", script.ARTICLES_2025)
        self.assertIn("8.4.6.9", script.ARTICLES_2025)


class TestCacheSchema(unittest.TestCase):
    """Cache output format matches Ruby original."""

    @patch("fetch_necb_8_4_text.MCPClient")
    @patch("sys.argv", ["fetch_necb_8_4_text.py", "--out", "/tmp/test.json"])
    def test_cache_structure(self, mock_client_class):
        """Cache has provenance and articles with required fields."""
        mock_client = Mock()
        mock_client.call.return_value = {
            "title": "Test Article",
            "full_text": "1) Sentence.",
            "page_start": 8,
            "page_end": 9,
            "equations": [{"text": "E = mc^2"}]
        }
        mock_client_class.return_value = mock_client

        with patch("pathlib.Path.write_text") as mock_write, \
             patch("pathlib.Path.mkdir"):

            # Run with minimal article list
            with patch.object(script, "ARTICLES_2025", ["8.4.1.1"]):
                script.main()

            # Verify write was called
            self.assertTrue(mock_write.called)
            written_json = mock_write.call_args[0][0]
            cache = json.loads(written_json)

            # Check provenance
            self.assertIn("provenance", cache)
            prov = cache["provenance"]
            self.assertEqual(prov["code"], "necb")
            self.assertEqual(prov["edition"], "2025")
            self.assertIn("retrieved", prov)
            self.assertIn("source", prov)

            # Check articles
            self.assertIn("articles", cache)
            self.assertIn("8.4.1.1", cache["articles"])
            article = cache["articles"]["8.4.1.1"]
            self.assertEqual(article["title"], "Test Article")
            self.assertEqual(article["pages"], [8, 9])
            self.assertEqual(article["equations"], ["E = mc^2"])
            self.assertIn("raw", article)
            self.assertIn("parse_ok", article)


if __name__ == "__main__":
    unittest.main()
