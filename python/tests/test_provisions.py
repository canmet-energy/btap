"""Offline code-provision citation and evidence-state tests."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path

import btap.codes.necb as necb
from btap.codes.coverage import verify_source
from btap.codes.provisions import (
    MalformedCitation,
    ProvisionAbsent,
    ProvisionIndexError,
    ProvisionIndexUnavailable,
    ProvisionNotIndexed,
    StaleProvisionEvidence,
    check_citation,
    parse_citation,
    validate_citation,
)


def _record(
    citation: str,
    *,
    parent: str | None,
    status: str = "present",
    complete: bool = False,
    evidence: list[dict[str, str]],
) -> dict:
    parsed = parse_citation(citation, family="necb")
    return {
        "citation": parsed.canonical,
        "division": parsed.division,
        "kind": parsed.kind,
        "parent": parent,
        "status": status,
        "title": None,
        "children_complete": complete,
        "evidence": evidence,
    }


class ProvisionFixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="provision-index-")
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "necb2020"
        (self.snapshot / "coverage").mkdir(parents=True)
        (self.snapshot / "provenance").mkdir()
        self.source = self.snapshot / "provenance" / "provisions.result.json"
        archive = {
            "get_section:necb:2020:A:1.1.1.1": {
                "edition": "2020",
                "division": "A",
                "section_number": "1.1.1.1",
                "article_number": "1.1.1.1",
                "hierarchy_level": "article",
                "title": "Application of this Code",
                "full_text": "1) Division A sentence.",
            },
            "get_section:necb:2020:B:1.1.1.1": {
                "edition": "2020",
                "division": "B",
                "section_number": "1.1.1.1",
                "article_number": "1.1.1.1",
                "hierarchy_level": "article",
                "title": "Application",
                "full_text": "1) Division B sentence.",
            },
            "get_section:necb:2020:B:A-8.4.1.1": {
                "edition": "2020",
                "division": "B",
                "section_number": "A-8.4.1.1",
                "article_number": "A-8.4.1.1",
                "hierarchy_level": "note",
                "title": "Explanatory note",
                "full_text": "Explanatory material.",
                "normative": False,
                "explains": "8.4.1.1",
            },
            "get_table:necb:2020:B:8.4.1.1.-A": {
                "edition": "2020",
                "division": "B",
                "table_number": "8.4.1.1.-A",
                "title": "Fixture table",
                "row_count": 1,
                "rows": [{"value": "fixture"}],
            },
            "query_sections:necb:2020:article:8.4.1.%": [
                {
                    "edition": "2020",
                    "division": "B",
                    "section_number": f"8.4.1.{number}",
                    "article_number": f"8.4.1.{number}",
                    "hierarchy_level": "article",
                    "title": f"Article {number}",
                }
                for number in range(1, 5)
            ],
        }
        self.source.write_bytes(
            json.dumps(
                archive,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
        self.source_original = self.source.read_bytes()

        self.cache_path = self.snapshot / "coverage" / "articles_8_4.json"
        cache = {
            "provenance": {
                "code": "necb",
                "edition": "2020",
                "retrieved": "2026-08-20",
            },
            "articles": {
                "8.4.1.1": {
                    "title": "Fixture article",
                    "parse_ok": True,
                    "sentences": [{"num": 1, "clauses": []}],
                    "raw": (
                        "1) Fixture sentence.\n"
                        "Notes to Table 8.4.1.1.-A:\n"
                        "(1) Fixture note.\n"
                        "2) Following article text.\n"
                    ),
                }
            },
        }
        self.cache_path.write_text(
            json.dumps(cache, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.cache_original = self.cache_path.read_bytes()

        def mcp(record: str) -> list[dict[str, str]]:
            return [{"source": "mcp", "record": record}]

        cache_evidence = [{"source": "section-8.4", "record": "articles.8.4.1.1"}]
        table_evidence = [
            *mcp("get_table:necb:2020:B:8.4.1.1.-A"),
            *cache_evidence,
        ]

        provisions = {
            "1.1.1.1": _record(
                "1.1.1.1",
                parent=None,
                complete=True,
                evidence=mcp("get_section:necb:2020:B:1.1.1.1"),
            ),
            "1.1.1.1.(1)": _record(
                "1.1.1.1.(1)",
                parent="1.1.1.1",
                complete=True,
                evidence=mcp("get_section:necb:2020:B:1.1.1.1"),
            ),
            "Division A 1.1.1.1": _record(
                "Division A 1.1.1.1",
                parent=None,
                complete=True,
                evidence=mcp("get_section:necb:2020:A:1.1.1.1"),
            ),
            "Division A 1.1.1.1.(1)": _record(
                "Division A 1.1.1.1.(1)",
                parent="Division A 1.1.1.1",
                complete=True,
                evidence=mcp("get_section:necb:2020:A:1.1.1.1"),
            ),
            "8.4.1.1": _record(
                "8.4.1.1",
                parent=None,
                complete=True,
                evidence=cache_evidence,
            ),
            "8.4.1.1.(1)": _record(
                "8.4.1.1.(1)",
                parent="8.4.1.1",
                complete=True,
                evidence=cache_evidence,
            ),
            "Table 8.4.1.1.-A": _record(
                "Table 8.4.1.1.-A",
                parent="8.4.1.1",
                complete=True,
                evidence=table_evidence,
            ),
            "Table 8.4.1.1.-A Note (1)": _record(
                "Table 8.4.1.1.-A Note (1)",
                parent="Table 8.4.1.1.-A",
                evidence=table_evidence,
            ),
            "Note A-8.4.1.1": _record(
                "Note A-8.4.1.1",
                parent="8.4.1.1",
                evidence=mcp("get_section:necb:2020:B:A-8.4.1.1"),
            ),
            "8.4.1.5": _record(
                "8.4.1.5",
                parent=None,
                status="absent",
                evidence=mcp("query_sections:necb:2020:article:8.4.1.%"),
            ),
        }
        self.index = {
            "schema": 1,
            "code": {"family": "necb", "id": "necb2020", "edition": "2020"},
            "generated": "2026-10-13",
            "sources": {
                "mcp": {
                    "kind": "authorized-mcp-payload",
                    "path": "provenance/provisions.result.json",
                    "retrieved": "2026-10-13",
                    "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                },
                "section-8.4": {
                    "kind": "existing-authorized-cache",
                    "path": "coverage/articles_8_4.json",
                    "retrieved": "2026-08-20",
                    "sha256": hashlib.sha256(
                        self.cache_path.read_bytes()
                    ).hexdigest(),
                }
            },
            "provisions": provisions,
        }
        self.write_index()
        source_artifacts = [
            {
                "path": "coverage/articles_8_4.json",
                "sha256": hashlib.sha256(self.cache_path.read_bytes()).hexdigest(),
            },
            {
                "path": "provenance/provisions.result.json",
                "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            },
        ]
        source_sha256 = hashlib.sha256(
            json.dumps(
                source_artifacts,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.manifest = {
            "id": "necb2020",
            "family": "necb",
            "edition": "2020",
            "label": "NECB 2020",
            "provision_index": "coverage/provisions.json",
            "provenance": {
                "coverage/provisions.json": {
                    "source": "mcp:necb:2020",
                    "request": None,
                    "source_revision": None,
                    "source_sha256": source_sha256,
                    "source_artifacts": source_artifacts,
                    "extractor": "fixture",
                    "retrieved": "2026-10-13",
                    "method": "generated",
                    "source_verification": "archived",
                    "result_sha256": hashlib.sha256(
                        self.index_path.read_bytes()
                    ).hexdigest(),
                }
            },
        }
        self.write_manifest()

    @property
    def index_path(self):
        return self.snapshot / "coverage" / "provisions.json"

    def write_index(self, *, update_manifest: bool = False):
        self.index_path.write_text(
            json.dumps(self.index, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if update_manifest:
            self.manifest["provenance"]["coverage/provisions.json"][
                "result_sha256"
            ] = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
            self.write_manifest()

    def write_manifest(self):
        (self.snapshot / "manifest.json").write_text(
            json.dumps(self.manifest, indent=2) + "\n",
            encoding="utf-8",
        )

    def close(self):
        self.temp.cleanup()


class TestNecbCitationGrammar(unittest.TestCase):
    def test_distinct_kinds_have_distinct_canonical_identities(self):
        cases = {
            "Article 8.4.4.13.": ("8.4.4.13", "article", "B"),
            "Sentence 8.4.4.13.(2)": ("8.4.4.13.(2)", "sentence", "B"),
            "8.4.4.13.(2)(G)": ("8.4.4.13.(2)(g)", "clause", "B"),
            "Subclause 8.4.4.13.(2)(g)(ii)": (
                "8.4.4.13.(2)(g)(ii)",
                "subclause",
                "B",
            ),
            "Table 8.4.4.7.-b": ("Table 8.4.4.7.-B", "table", "B"),
            "Table 8.4.4.7.-B Note (3)": (
                "Table 8.4.4.7.-B Note (3)",
                "table-note",
                "B",
            ),
            "Appendix Note a-8.4.4.13.": (
                "Note A-8.4.4.13",
                "appendix-note",
                "B",
            ),
            "Division A 1.1.1.1.(1)": (
                "Division A 1.1.1.1.(1)",
                "sentence",
                "A",
            ),
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                parsed = parse_citation(value, family="necb")
                self.assertEqual(expected, (parsed.canonical, parsed.kind, parsed.division))

    def test_division_a_must_be_explicitly_qualified(self):
        self.assertEqual("B", parse_citation("1.1.1.1.(1)", family="necb").division)
        self.assertEqual(
            "A",
            parse_citation("Division A 1.1.1.1.(1)", family="necb").division,
        )
        with self.assertRaises(MalformedCitation):
            parse_citation("A-1.1.1.1.(1)", family="necb")

    def test_unregistered_family_does_not_claim_necb_syntax_or_access(self):
        with self.assertRaisesRegex(ProvisionIndexUnavailable, "no provision-citation parser"):
            parse_citation("1.1.1.1", family="future-related-code")

    def test_malformed_citations_are_fullmatch_rejected(self):
        bad = (
            "",
            "8.4.4",
            "8.4.4.13.(0)",
            "8.4.4.13.(2) trailing",
            "junk 8.4.4.13.(2)",
            "Article 8.4.4.13.(2)",
            "Sentence 8.4.4.13",
            "Clause 8.4.4.13.(2)",
            "Table 8.4.4.7.-B Note 3",
            "Table 8.4.4.7.-B Note (0)",
            "Division C 1.1.1.1",
            "Note 8.4.4.13",
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(MalformedCitation):
                parse_citation(value, family="necb")


class TestOfflineProvisionEvidence(unittest.TestCase):
    def setUp(self):
        self.fixture = ProvisionFixture()
        necb._set_data_root(self.fixture.root, _testing=True)

    def tearDown(self):
        necb._set_data_root(None, _testing=True)
        self.fixture.close()

    def test_article_table_and_division_identities_do_not_collapse(self):
        article = validate_citation("necb2020", "8.4.1.1")
        table = validate_citation("necb2020", "Table 8.4.1.1.-A")
        division_b = validate_citation("necb2020", "1.1.1.1")
        division_a = validate_citation("necb2020", "Division A 1.1.1.1")
        self.assertEqual("article", article["kind"])
        self.assertEqual("table", table["kind"])
        self.assertEqual("B", division_b["division"])
        self.assertEqual("A", division_a["division"])

    def test_note_existence_uses_a_complete_parent_inventory(self):
        self.assertEqual(
            "table-note",
            validate_citation(
                "necb2020", "Table 8.4.1.1.-A Note (1)"
            )["kind"],
        )
        missing_note = check_citation(
            "necb2020", "Table 8.4.1.1.-A Note (2)"
        )
        self.assertEqual("absent", missing_note.status)
        with self.assertRaises(ProvisionAbsent):
            validate_citation("necb2020", "Table 8.4.1.1.-A Note (2)")

    def test_missing_cache_data_is_not_authority_confirmed_absence(self):
        explicit_absence = check_citation("necb2020", "8.4.1.5")
        uncached = check_citation("necb2020", "7.7.7.7")
        self.assertEqual("absent", explicit_absence.status)
        self.assertEqual("not-indexed", uncached.status)
        with self.assertRaises(ProvisionNotIndexed):
            validate_citation("necb2020", "7.7.7.7")

    def test_stale_source_does_not_degrade_into_absence(self):
        self.assertEqual("absent", check_citation("necb2020", "8.4.1.5").status)
        self.fixture.source.write_text('{"fixture":"mutated"}\n', encoding="utf-8")
        stale = check_citation("necb2020", "8.4.1.5")
        self.assertEqual("stale", stale.status)
        with self.assertRaises(StaleProvisionEvidence):
            validate_citation("necb2020", "8.4.1.5")

    def test_stale_section_cache_is_reported_distinctly(self):
        self.fixture.cache_path.write_bytes(self.fixture.cache_original + b" ")
        stale = check_citation("necb2020", "8.4.1.1")
        self.assertEqual("stale", stale.status)
        self.assertIn("coverage/articles_8_4.json hashes", stale.detail)
        with self.assertRaises(StaleProvisionEvidence):
            validate_citation("necb2020", "8.4.1.1")

    def test_verify_source_checks_both_normalization_inputs(self):
        out = StringIO()
        self.assertEqual(
            0,
            verify_source("necb2020", "coverage/provisions.json", out=out),
            out.getvalue(),
        )

        self.fixture.source.write_bytes(self.fixture.source_original + b" ")
        out = StringIO()
        self.assertEqual(
            1,
            verify_source("necb2020", "coverage/provisions.json", out=out),
        )
        self.assertIn("provenance/provisions.result.json hashes", out.getvalue())
        self.assertEqual("stale", check_citation("necb2020", "8.4.1.1").status)

        self.fixture.source.write_bytes(self.fixture.source_original)
        self.fixture.cache_path.write_bytes(self.fixture.cache_original + b" ")
        out = StringIO()
        self.assertEqual(
            1,
            verify_source("necb2020", "coverage/provisions.json", out=out),
        )
        self.assertIn("coverage/articles_8_4.json hashes", out.getvalue())
        self.assertEqual("stale", check_citation("necb2020", "8.4.1.1").status)

    def test_mutated_normalized_index_is_stale_even_when_sources_are_unchanged(self):
        self.fixture.index["generated"] = "2026-10-14"
        self.fixture.write_index()
        stale = check_citation("necb2020", "8.4.1.5")
        self.assertEqual("stale", stale.status)
        self.assertIn("manifest records", stale.detail)

    def test_index_kind_mutation_is_rejected(self):
        self.fixture.index["provisions"]["8.4.1.1"]["kind"] = "table"
        self.fixture.write_index(update_manifest=True)
        with self.assertRaisesRegex(ProvisionIndexError, "does not match"):
            check_citation("necb2020", "8.4.1.1")

    def test_article_parent_mutation_is_rejected(self):
        self.fixture.index["provisions"]["8.4.1.1"]["parent"] = "1.1.1.1"
        self.fixture.write_index(update_manifest=True)
        with self.assertRaisesRegex(ProvisionIndexError, "must be null for an article"):
            check_citation("necb2020", "8.4.1.1")

    def test_present_alias_is_rejected_before_canonical_absence_can_be_inferred(self):
        record = self.fixture.index["provisions"].pop("8.4.1.1.(1)")
        alias = "Sentence 8.4.1.1.(1)"
        record["citation"] = alias
        self.fixture.index["provisions"][alias] = record
        self.fixture.write_index(update_manifest=True)
        with self.assertRaisesRegex(ProvisionIndexError, "is an alias; use canonical"):
            check_citation("necb2020", "8.4.1.1.(1)")

    def test_duplicate_normalized_identities_are_rejected(self):
        alias = "Sentence 8.4.1.1.(1)"
        record = copy.deepcopy(
            self.fixture.index["provisions"]["8.4.1.1.(1)"]
        )
        record["citation"] = alias
        self.fixture.index["provisions"][alias] = record
        self.fixture.write_index(update_manifest=True)
        with self.assertRaisesRegex(
            ProvisionIndexError,
            "duplicate normalized identity",
        ):
            check_citation("necb2020", "8.4.1.1.(1)")

    def test_custom_parent_alias_is_rejected(self):
        self.fixture.index["provisions"]["Table 8.4.1.1.-A"][
            "parent"
        ] = "Article 8.4.1.1."
        self.fixture.write_index(update_manifest=True)
        with self.assertRaisesRegex(ProvisionIndexError, "parent .* is an alias"):
            check_citation("necb2020", "Table 8.4.1.1.-A")

    def test_unknown_source_kind_is_rejected(self):
        self.fixture.index["sources"]["mcp"]["kind"] = "authorized-mpc-payload"
        self.fixture.write_index(update_manifest=True)
        with self.assertRaisesRegex(ProvisionIndexError, "kind must be one of"):
            check_citation("necb2020", "8.4.1.1")

    def test_evidence_locator_mutation_is_rejected(self):
        self.fixture.index["provisions"]["1.1.1.1"]["evidence"][0][
            "record"
        ] = "missing.result"
        self.fixture.write_index(update_manifest=True)
        with self.assertRaisesRegex(ProvisionIndexError, "not in the authorized"):
            check_citation("necb2020", "8.4.1.1")

    def test_fake_present_sentence_or_clause_absent_from_authority_is_rejected(self):
        cases = (
            (
                "1.1.1.1.(2)",
                "1.1.1.1",
                self.fixture.index["provisions"]["1.1.1.1"]["evidence"],
            ),
            (
                "8.4.1.1.(1)(a)",
                "8.4.1.1.(1)",
                self.fixture.index["provisions"]["8.4.1.1.(1)"]["evidence"],
            ),
        )
        for citation, parent, evidence in cases:
            with self.subTest(citation=citation):
                self.fixture.index["provisions"][citation] = _record(
                    citation,
                    parent=parent,
                    evidence=copy.deepcopy(evidence),
                )
                self.fixture.write_index(update_manifest=True)
                with self.assertRaisesRegex(
                    ProvisionIndexError,
                    "does not semantically witness",
                ):
                    check_citation("necb2020", citation)
                del self.fixture.index["provisions"][citation]


class TestCommittedNecbProvisionCorpus(unittest.TestCase):
    def test_representative_corpus_is_fresh_and_end_to_end(self):
        expected = {
            "necb2020": {
                "present": (
                    "Division A 1.1.1.1.(1)",
                    "1.1.1.1.(1)",
                    "8.4.4.13.(2)(g)",
                    "Table 8.4.4.7.-B",
                    "Table 8.4.4.7.-B Note (3)",
                    "Note A-8.4.4.13",
                ),
                "absent": "8.4.1.5",
            },
            "necb2025": {
                "present": (
                    "Division A 1.1.1.1.(1)(a)(i)",
                    "1.1.1.1.(1)",
                    "8.4.5.13.(2)(g)",
                    "Table 8.4.5.7.-B",
                    "Table 8.4.5.7.-B Note (3)",
                    "Note A-8.4.5.13",
                    "8.4.1.5",
                ),
                "absent": None,
            },
        }
        for code, cases in expected.items():
            with self.subTest(code=code):
                for citation in cases["present"]:
                    self.assertEqual(
                        "present",
                        check_citation(code, citation).status,
                        citation,
                    )
                if cases["absent"] is not None:
                    self.assertEqual(
                        "absent",
                        check_citation(code, cases["absent"]).status,
                    )


if __name__ == "__main__":
    unittest.main()
