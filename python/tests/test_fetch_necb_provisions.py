"""Tests for the authenticated NECB provision fetch/index maintainer path."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT / "scripts"))

import fetch_necb_provisions as script  # noqa: E402


def _section(
    edition: str,
    division: str,
    number: str,
    *,
    text: str,
    title: str,
    level: str = "article",
) -> dict:
    record = {
        "edition": edition,
        "division": division,
        "section_number": number,
        "article_number": number,
        "hierarchy_level": level,
        "title": title,
        "full_text": text,
    }
    if level == "note":
        record["normative"] = False
        record["explains"] = number.removeprefix("A-")
    return record


def _cache_article(title: str, sentences: list[dict], raw: str = "") -> dict:
    return {
        "title": title,
        "parse_ok": True,
        "sentences": sentences,
        "raw": raw,
    }


def section_cache(edition: str) -> dict:
    spec = script.EDITION_SPECS[edition]
    reference = spec["reference_article"]
    table = spec["table"]
    articles = {
        reference: _cache_article(
            "Reference systems",
            [{"num": 1, "clauses": []}],
            raw=(
                f"1) Select a system using Table {table}.\n"
                f"Notes to Table {table}:\n"
                "(1) First note.\n"
                "(2) Second note.\n"
                "(3) Third note.\n"
                "2) Continue with the article.\n"
            ),
        ),
        spec["structured_article"]: _cache_article(
            "Heat pumps",
            [
                {"num": 1, "clauses": []},
                {
                    "num": 2,
                    "clauses": [
                        {"id": "a", "subclauses": []},
                        {"id": "b", "subclauses": []},
                        {"id": "c", "subclauses": []},
                        {"id": "d", "subclauses": []},
                        {"id": "e", "subclauses": []},
                        {"id": "f", "subclauses": []},
                        {"id": "g", "subclauses": [{"id": "i"}]},
                    ],
                },
            ],
        ),
    }
    if edition == "2025":
        articles[spec["inventory_probe"]] = _cache_article(
            "Process loads",
            [{"num": 1, "clauses": []}],
        )
    return {
        "provenance": {
            "code": "necb",
            "edition": edition,
            "retrieved": "2026-08-20",
        },
        "articles": articles,
    }


class FakeClient:
    def __init__(self, edition: str):
        self.edition = edition
        self.spec = script.EDITION_SPECS[edition]
        self.mutate = None
        self.calls = []

    def call(self, tool: str, arguments: dict):
        self.calls.append((tool, copy.deepcopy(arguments)))
        if tool == "get_section" and arguments["section_number"] == "1.1.1.1":
            division = arguments["division"]
            result = _section(
                self.edition,
                division,
                "1.1.1.1",
                title=f"Division {division} application",
                text=(
                    "1) Requirement:\n"
                    "a) first clause:\n"
                    "i) first subclause.\n"
                    "2) Second sentence.\n"
                ),
            )
        elif tool == "get_section":
            result = _section(
                self.edition,
                "B",
                self.spec["appendix_note"],
                title="Heat-pump definitions",
                text="Explanatory material.",
                level="note",
            )
        elif tool == "get_table":
            result = {
                "edition": self.edition,
                "division": "B",
                "table_number": self.spec["table"],
                "title": "Reference systems",
                "row_count": 1,
                "rows": [{"System": "1"}],
                "headers": ["System"],
            }
        elif tool == "query_sections":
            numbers = ["8.4.1.1", "8.4.1.2", "8.4.1.3", "8.4.1.4"]
            if self.edition == "2025":
                numbers.append("8.4.1.5")
            result = [
                {
                    "edition": self.edition,
                    "division": "B",
                    "section_number": number,
                    "article_number": number,
                    "hierarchy_level": "article",
                    "title": f"Article {number}",
                }
                for number in numbers
            ]
        else:
            raise AssertionError((tool, arguments))

        if self.mutate is not None:
            result = self.mutate(tool, arguments, result)
        return result


class TestStructureExtraction(unittest.TestCase):
    def test_sentence_clause_and_subclause_structure_contains_no_text(self):
        structure = script.structure_from_text(
            {"full_text": "1) Sentence:\na) Clause:\ni) Subclause.\n2) Next."}
        )
        self.assertEqual(
            {"1": {"clauses": {"a": ["i"]}}, "2": {"clauses": {}}},
            structure,
        )

    def test_non_contiguous_sentence_numbers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "not contiguous"):
            script.structure_from_text(
                {"full_text": "1) First.\n3) Third."}
            )

    def test_non_contiguous_subclauses_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected subclause"):
            script.structure_from_text(
                {"full_text": "1) Sentence:\na) Clause:\ni) First.\niii) Third."}
            )

    def test_non_contiguous_cached_clauses_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected Clause"):
            script.structure_from_cache(
                _cache_article(
                    "Mutated",
                    [
                        {
                            "num": 1,
                            "clauses": [
                                {"id": "a", "subclauses": []},
                                {"id": "c", "subclauses": []},
                            ],
                        }
                    ],
                )
            )

    def test_table_note_inventory_is_exact_and_contiguous(self):
        article = {
            "raw": (
                "1) Sentence.\n"
                "Notes to Table 8.4.4.7.-B:\n"
                "(1) One.\n"
                "(2) Two.\n"
                "2) Next sentence.\n"
            )
        }
        self.assertEqual(
            ["1", "2"],
            script.table_note_ids(article, "8.4.4.7.-B"),
        )
        article["raw"] = article["raw"].replace("(2)", "(3)")
        with self.assertRaisesRegex(ValueError, "not contiguous"):
            script.table_note_ids(article, "8.4.4.7.-B")


class TestProvisionDocumentBuilder(unittest.TestCase):
    def test_2020_build_marks_real_inventory_gap_absent(self):
        client = FakeClient("2020")
        archive, index = script.build_documents(
            client,
            "2020",
            section_cache("2020"),
            retrieved="2026-10-13",
        )
        self.assertEqual(5, len(archive))
        self.assertEqual(
            "absent",
            index["provisions"]["8.4.1.5"]["status"],
        )
        self.assertIn("Division A 1.1.1.1.(1)(a)(i)", index["provisions"])
        self.assertIn("1.1.1.1.(1)(a)(i)", index["provisions"])
        self.assertIn("Table 8.4.4.7.-B Note (3)", index["provisions"])
        self.assertIn("Note A-8.4.4.13", index["provisions"])

    def test_2025_build_reuses_existing_8_4_cache_for_present_article(self):
        client = FakeClient("2025")
        _archive, index = script.build_documents(
            client,
            "2025",
            section_cache("2025"),
            retrieved="2026-10-13",
        )
        probe = index["provisions"]["8.4.1.5"]
        self.assertEqual("present", probe["status"])
        self.assertEqual(
            [
                {
                    "source": "mcp",
                    "record": "query_sections:necb:2025:article:8.4.1.%",
                },
                {"source": "section-8.4", "record": "articles.8.4.1.5"},
            ],
            probe["evidence"],
        )

    def test_table_presence_and_note_inventory_share_both_sources(self):
        client = FakeClient("2020")
        _archive, index = script.build_documents(
            client,
            "2020",
            section_cache("2020"),
            retrieved="2026-10-13",
        )
        expected = [
            {
                "source": "mcp",
                "record": "get_table:necb:2020:B:8.4.4.7.-B",
            },
            {"source": "section-8.4", "record": "articles.8.4.4.7"},
        ]
        self.assertEqual(
            expected,
            index["provisions"]["Table 8.4.4.7.-B"]["evidence"],
        )
        self.assertEqual(
            expected,
            index["provisions"]["Table 8.4.4.7.-B Note (1)"]["evidence"],
        )

    def test_normalized_index_does_not_duplicate_requirement_text(self):
        client = FakeClient("2020")
        _archive, index = script.build_documents(
            client,
            "2020",
            section_cache("2020"),
            retrieved="2026-10-13",
        )
        serialized = json.dumps(index)
        self.assertNotIn("first clause", serialized)
        self.assertNotIn("First note", serialized)
        self.assertNotIn("full_text", serialized)
        self.assertNotIn('"raw"', serialized)

    def test_table_identity_mutation_is_rejected(self):
        client = FakeClient("2020")

        def mutate(tool, _arguments, result):
            if tool == "get_table":
                result["table_number"] = "8.4.4.7.-A"
            return result

        client.mutate = mutate
        with self.assertRaisesRegex(ValueError, "table payload identity mismatch"):
            script.build_documents(
                client,
                "2020",
                section_cache("2020"),
                retrieved="2026-10-13",
            )

    def test_division_identity_mutation_is_rejected(self):
        client = FakeClient("2020")

        def mutate(tool, arguments, result):
            if (
                tool == "get_section"
                and arguments["section_number"] == "1.1.1.1"
                and arguments["division"] == "A"
            ):
                result["division"] = "B"
            return result

        client.mutate = mutate
        with self.assertRaisesRegex(ValueError, "section payload identity mismatch"):
            script.build_documents(
                client,
                "2020",
                section_cache("2020"),
                retrieved="2026-10-13",
            )

    def test_incomplete_inventory_cannot_establish_absence(self):
        client = FakeClient("2020")

        def mutate(tool, _arguments, result):
            if tool == "query_sections":
                return [item for item in result if item["section_number"] != "8.4.1.2"]
            return result

        client.mutate = mutate
        with self.assertRaisesRegex(ValueError, "inventory is not contiguous"):
            script.build_documents(
                client,
                "2020",
                section_cache("2020"),
                retrieved="2026-10-13",
            )


class TestCommittedProvisionReplay(unittest.TestCase):
    def test_committed_indexes_replay_from_both_sources_byte_for_byte(self):
        for edition in script.EDITION_SPECS:
            with self.subTest(edition=edition):
                snapshot = script.DATA_ROOT / f"necb{edition}"
                archive_path = snapshot / script.ARCHIVE_PATH
                cache_path = snapshot / script.SECTION_CACHE_PATH
                index_path = snapshot / script.INDEX_PATH
                manifest_path = snapshot / "manifest.json"

                archive_bytes = archive_path.read_bytes()
                cache_bytes = cache_path.read_bytes()
                index_bytes = index_path.read_bytes()
                archive = json.loads(archive_bytes)
                cache = json.loads(cache_bytes)
                committed = json.loads(index_bytes)
                manifest = json.loads(manifest_path.read_bytes())

                rebuilt = script.build_index_from_archive(
                    archive,
                    edition,
                    cache,
                    retrieved=committed["generated"],
                    section_cache_sha256=hashlib.sha256(cache_bytes).hexdigest(),
                )
                self.assertEqual(index_bytes, script._json_bytes(rebuilt))
                self.assertEqual(archive_bytes, script._archive_bytes(archive))

                archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
                cache_sha256 = hashlib.sha256(cache_bytes).hexdigest()
                self.assertEqual(
                    archive_sha256,
                    rebuilt["sources"]["mcp"]["sha256"],
                )
                self.assertEqual(
                    cache_sha256,
                    rebuilt["sources"]["section-8.4"]["sha256"],
                )

                artifacts = script._source_artifacts(
                    archive_sha256=archive_sha256,
                    section_cache_sha256=cache_sha256,
                )
                provenance = manifest["provenance"][script.INDEX_PATH.as_posix()]
                self.assertEqual(artifacts, provenance["source_artifacts"])
                self.assertEqual(
                    script._source_set_sha256(artifacts),
                    provenance["source_sha256"],
                )
                self.assertEqual(
                    hashlib.sha256(index_bytes).hexdigest(),
                    provenance["result_sha256"],
                )


if __name__ == "__main__":
    unittest.main()
