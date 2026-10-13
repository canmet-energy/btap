"""The decision generator's own behaviour: parser, TOML writer, validation.

``test_decisions_registry_sync.py`` gates the repository's committed state.
This module attacks the machinery instead, on synthetic sources, so that each
rule is shown to REJECT something rather than merely to pass over real files
that happen to comply.
"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import sys
import tempfile
import tomllib
import types
import unittest
from pathlib import Path
from unittest import mock

PYTHON_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PYTHON_ROOT / "scripts"))
import generate_decisions as G  # noqa: E402

# G put this checkout's python/ first on sys.path.
from btap.codes import decisions as Loader  # noqa: E402

EM = G.EM_DASH

GOOD_META = {
    "id": "D-01",
    "title": "A compact registry title",
    "kind": "process",
    # `articles` is a MAP from code id to that edition's own citations: the
    # same number can name different requirements in different editions, so a
    # flat list cannot say which numbering it uses. The fixture uses a real
    # code id and a real article so the validated path is exercised rather
    # than skipped.
    # `articles` groups by an AUTHORED requirement identity, then by code id
    # inside it. Correspondence across editions is asserted by the author,
    # not inferred from title vocabulary, which could not be made safe.
    "articles": {"hydronic_pumps": {
        "label": "Hydronic pump power",
        "necb2020": ["8.4.4.14."]}},
    "editions": ["necb2020"],
    "summary": "A paraphrase of what was decided.",
}
GOOD_BODY = "## D-01 {} An authored heading, not the title\n\nBody text.\n".format(EM)


def write(directory, meta=None, body=None, name=None):
    meta = dict(GOOD_META if meta is None else meta)
    body = GOOD_BODY if body is None else body
    path = Path(directory) / (name or (meta["id"] + ".md"))
    path.write_text(G.source_text(meta, body), encoding="utf-8")
    return path


KEY = "heat_pump_reference_by_source"

#: The structured form (docs/plans/DECISION_APPLICABILITY_PLAN.md). Every NECB
#: reference is one its edition's committed provision index records as
#: PRESENT -- sentences, an Appendix note, a Division A sentence, a table and
#: a table note -- so the validated path runs rather than being skipped. The
#: related NECB record and the incorporated external standard show that
#: neither role establishes an edition: `editions` is derived from the two
#: governing records alone, and none is authored.
STRUCTURED_META = {
    "id": "D-01",
    "title": "A compact registry title",
    "kind": "runtime",
    "articles": {KEY: {
        "label": "Reference system for a proposed heat pump, by heat source",
        "decided": ("Water-loop and other heat pumps follow different "
                    "reference-system selection branches."),
        "sources": [
            {"code": "necb", "edition": "2020", "role": "governing",
             "references": ["8.4.4.13.(1)", "8.4.4.13.(2)", "Note A-8.4.4.13"]},
            {"code": "necb", "edition": "2025", "role": "governing",
             "references": ["8.4.5.13.(1)", "8.4.5.13.(2)", "Note A-8.4.5.13"]},
            {"code": "necb", "edition": "2020", "role": "related",
             "references": ["Division A 1.1.1.1.(1)", "Table 8.4.4.7.-B",
                            "Table 8.4.4.7.-B Note (1)"]},
            {"code": "ashrae-62.1", "edition": "2016",
             "role": "incorporated-reference", "references": ["6.2.2.1"]},
        ]}},
    "summary": "A paraphrase of what was decided.",
}


def structured(edit=None, **over):
    """A deep copy of `STRUCTURED_META` with top-level overrides, then
    `edit(meta)` applied in place, so no test leaks a mutation into another."""
    meta = copy.deepcopy(STRUCTURED_META)
    meta.update(copy.deepcopy(over))
    if edit is not None:
        edit(meta)
    return meta


def requirement(meta, key=KEY):
    return meta["articles"][key]


def record(meta, index, key=KEY):
    return meta["articles"][key]["sources"][index]


def inner(front):
    """The TOML between a front matter's two fences."""
    lines = front.split("\n")
    assert lines[0] == lines[-1] == G.FENCE, front
    return "\n".join(lines[1:-1])


class TestTomlWriter(unittest.TestCase):
    """Authored text must not be able to break out of a TOML string."""

    def round_trip(self, value):
        raw = "value = " + G.toml_string(value)
        return tomllib.loads(raw)["value"]

    def test_hostile_strings_survive_exactly(self):
        hostile = [
            'a "quoted" phrase',
            "trailing backslash \\",
            "\\\" escaped quote lookalike",
            'value = "injected"\nid = "D-99"',
            '"""a bare multi-line delimiter"""',
            "+++\nid = \"D-02\"\n+++",
            "tab\there and newline\nhere",
            "carriage\rreturn",
            "a null-adjacent \x01 control char",
            "unicode " + EM + " em dash and × times",
            "",
            "'single' quotes",
            "#not a comment",
            "[not-a-table]",
        ]
        for value in hostile:
            with self.subTest(value=value):
                self.assertEqual(value, self.round_trip(value))

    def test_a_quote_cannot_terminate_the_string(self):
        smuggled = 'x", id = "D-99'
        parsed = tomllib.loads("value = " + G.toml_string(smuggled) + "\n")
        self.assertEqual({"value": smuggled}, parsed,
                         "a quote in authored text injected a second key")

    def test_arrays_round_trip_including_hostile_members(self):
        members = ['8.4.4.14.', 'a "quoted" article', "back\\slash"]
        raw = "value = " + G.toml_value(members)
        self.assertEqual(members, tomllib.loads(raw)["value"])

    def test_non_strings_are_refused_rather_than_coerced(self):
        for value in (3, None, True, {"a": 1}, ["ok", 3]):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    G.toml_value(value)

    def test_front_matter_emits_the_scalars_then_the_articles_table(self):
        """`articles` is a TOML TABLE and must come last: a table header
        captures every key that follows it, so a scalar after it would be read
        as an articles key."""
        lines = G.front_matter(GOOD_META).split("\n")
        self.assertEqual(G.FENCE, lines[0])
        self.assertEqual(G.FENCE, lines[-1])
        inner = [ln for ln in lines[1:-1] if ln.strip()]
        header = next(i for i, ln in enumerate(inner)
                      if ln.startswith("[articles"))
        scalars = [ln.split(" = ")[0] for ln in inner[:header]]
        self.assertEqual([f for f in G.FIELDS if f != "articles"], scalars)
        allowed = G.registered_codes() | {G.ARTICLES_UNVERIFIED, "label"}
        for line in inner[header + 1:]:
            if line.startswith("["):
                continue        # a further requirement table
            self.assertIn(line.split(" = ")[0], allowed)


class TestSourceValidation(unittest.TestCase):
    """Each rule is shown to reject a source that violates only that rule."""

    def parse(self, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            return G.parse_source(write(directory, **kwargs))

    def test_a_correct_source_parses(self):
        meta, body = self.parse()
        self.assertEqual(GOOD_META, meta)
        self.assertEqual(GOOD_BODY, body)

    def test_the_heading_text_need_not_equal_the_title(self):
        """69 of the 97 real decisions differ here; that is a source fact."""
        meta, _ = self.parse()
        self.assertNotIn(meta["title"], GOOD_BODY.split("\n")[0])

    def rejects(self, message, **kwargs):
        with self.assertRaises(ValueError) as caught:
            self.parse(**kwargs)
        self.assertIn(message, str(caught.exception))

    def accepts(self, **kwargs):
        """The control. A validator is only as good as what it still admits,
        and the rule this file replaced was caught by what it WRONGLY
        refused, not by what it let through."""
        self.parse(**kwargs)

    # ---------------------------------------------------------------- the
    # `not_applicable` sentinel (Sol, `169`). It is a CATEGORY statement —
    # this decision adopts no operative Code proposition whose numbering,
    # content or result can vary by edition — and NOT a verification state.
    # Each rule is paired with a control, because the rule this file replaced
    # was caught by what it wrongly REFUSED, not by what it let through.

    @staticmethod
    def na(**over):
        base = dict(GOOD_META, editions=["not_applicable"],
                    articles={"not_applicable": []})
        base.update(over)
        return base

    def test_not_applicable_is_accepted_on_a_process_decision(self):
        meta, _ = self.parse(meta=self.na())
        self.assertEqual(["not_applicable"], meta["editions"])
        self.assertEqual({"not_applicable": []}, meta["articles"])

    def test_not_applicable_may_not_be_mixed_with_a_code_id(self):
        self.rejects("may not mix",
                     meta=self.na(editions=["not_applicable", "necb2020"]))

    def test_not_applicable_may_not_be_mixed_with_unverified(self):
        self.rejects("may not mix",
                     meta=self.na(editions=["not_applicable", "unverified"]))

    def test_a_not_applicable_decision_may_not_cite_an_article(self):
        """An empty list, in both directions.

        A cited article IS a Code proposition whose numbering can move
        between editions, which is exactly what this sentinel denies. The
        control proves the empty list is still accepted, so this does not
        pass by refusing the key outright.
        """
        self.rejects("must be EMPTY",
                     meta=self.na(articles={"not_applicable": ["8.4.4.9.(7)"]}))
        self.accepts(meta=self.na())

    def test_not_applicable_may_not_sit_beside_an_authored_requirement(self):
        """The articles-side exclusivity rule, which nothing else pins.

        Found by mutation rather than by review: neutering
        `if not_applicable_articles and len(articles) > 1:` left all six
        other sentinel tests green, so the rule was shipping unpinned. A
        decision carrying BOTH the sentinel and a real requirement is
        asserting the edition axis does not apply and then citing something
        that varies by edition.
        """
        self.rejects("may not mix", meta=self.na(articles={
            "not_applicable": [],
            "hydronic_pumps": {"label": "Hydronic pump power",
                               "necb2020": ["8.4.4.14.(1)"],
                               "necb2025": ["8.4.5.14.(1)"]}}))
        self.accepts(meta=self.na())

    def test_the_two_halves_must_agree(self):
        """`editions` and the articles key go together or not at all."""
        self.rejects("go together or not at all",
                     meta=self.na(articles={"unverified": []}))
        self.rejects("go together or not at all",
                     meta=self.na(editions=["unverified"]))

    def test_only_a_process_decision_may_be_not_applicable(self):
        """Sol's restriction: a runtime or data decision HAS a Code
        proposition to establish, so the sentinel is initially process-only.
        The control keeps `kind` from being the thing that decides — process
        is necessary, never sufficient, and the classification is authored
        per decision.
        """
        for kind in ("runtime", "runtime_unwired", "data"):
            self.rejects("only a kind='process' decision",
                         meta=self.na(kind=kind))
        self.accepts(meta=self.na(kind="process"))

    def test_a_process_decision_may_still_be_unverified(self):
        """The sentinel must not swallow its own category.

        13 of the 38 real process decisions stay `unverified` because they
        cite an article or their classification is uncertain. If `process`
        implied `not_applicable`, this control would fail.
        """
        meta, _ = self.parse(meta=dict(
            GOOD_META, kind="process", editions=["unverified"],
            articles={"unverified": ["8.4.4.9.(7)"]}))
        self.assertEqual(["unverified"], meta["editions"])

    def test_a_missing_or_unexpected_field_is_refused(self):
        # A missing field cannot be written through source_text, which needs
        # all five, so this one is assembled by hand.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "D-01.md"
            short = "\n".join(
                [G.FENCE]
                + ["{} = {}".format(f, G.toml_value(GOOD_META[f]))
                   for f in G.FIELDS if f != "articles"]
                + [G.FENCE, "", GOOD_BODY])
            path.write_text(short, encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                G.parse_source(path)
            self.assertIn("missing", str(caught.exception))

        # An unexpected field must not be droppable either: the writer refuses
        # it rather than quietly omitting it, and the parser refuses a
        # hand-written file that carries one.
        with self.assertRaises(ValueError):
            G.front_matter(dict(GOOD_META, extra="x"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "D-01.md"
            path.write_text(
                # inserted BEFORE the [articles] table: a TOML table
                # header captures every key that follows it, so appending
                # before the closing fence would make this an articles key
                # rather than an unexpected top-level field
                G.source_text(GOOD_META, GOOD_BODY).replace(
                    "\n[articles", '\nextra = "x"\n\n[articles'),
                encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                G.parse_source(path)
            self.assertIn("unexpected", str(caught.exception))

    def test_a_malformed_id_is_refused(self):
        """`D-1` and `D-100` used to be refused by `^D-\\d{2}$`. They are VALID
        now: D-01..D-99 were all taken, so the grammar widened to `^D-\\d+$`
        rather than move the wall to 999. What is still malformed is anything
        that is not D- followed by digits."""
        for bad in ("D-", "D-x", "D-1a", "Dx1", "99", "D--1"):
            self.rejects("malformed id",
                         meta=dict(GOOD_META, id=bad), name=bad + ".md")

    def test_a_THREE_digit_id_is_now_accepted(self):
        """The widening, pinned: D-01..D-99 are all taken, so a new decision
        needs an id the old grammar refused."""
        with tempfile.TemporaryDirectory() as d:
            body = "## D-100 {} An authored heading\n\nBody text.\n".format(EM)
            write(d, meta=dict(GOOD_META, id="D-100"), body=body,
                  name="D-100.md")
            parsed = G.parse_source(Path(d) / "D-100.md")
            self.assertIsNotNone(parsed)

    def test_a_filename_that_disagrees_with_the_id_is_refused(self):
        self.rejects("filename does not match", name="D-02.md")

    def test_an_unknown_kind_is_refused(self):
        self.rejects("unknown kind", meta=dict(GOOD_META, kind="runtimeish"))

    def test_empty_or_non_string_text_fields_are_refused(self):
        self.rejects("title must be", meta=dict(GOOD_META, title="  "))
        self.rejects("summary must be", meta=dict(GOOD_META, summary=""))

    def test_articles_must_be_a_MAP_of_lists(self):
        """A flat list cannot say which edition's numbering it uses, and the
        same number can name different requirements in different editions."""
        self.rejects("articles must be",
                     meta=dict(GOOD_META, articles="8.4.4.14."))
        self.rejects("articles must be",
                     meta=dict(GOOD_META, articles=["8.4.4.14."]))
        self.rejects("non-empty list of strings",
                     meta=dict(GOOD_META, articles={"hydronic_pumps": {
                         "label": "x", "necb2020": "8.4.4.14."}}))

    def test_a_requirement_must_cover_every_edition_the_decision_claims(self):
        """Checked PER REQUIREMENT. A global check let one requirement's
        missing edition hide behind another that listed it."""
        self.rejects("lists no article for",
                     meta=dict(GOOD_META,
                               articles={"hydronic_pumps": {
                                   "label": "Hydronic pump power",
                                   "necb2025": ["8.4.5.14."]}}))

    def test_a_requirement_need_NOT_correspond_by_NUMBERING(self):
        """The suffix-correspondence rule this replaces was wrong in BOTH
        directions (Sol, `124`.5). It admitted unrelated articles that happened
        to share suffixes, and it REFUSED a real migration: D-89's
        modulating-boiler part-load requirement is 8.4.5.2.(3) in NECB 2020 and
        8.4.6.2.(2) in NECB 2025, because the 2020 article has three sentences
        and the 2025 article has two. Correspondence is the authored key and
        its label; numbering cannot carry it."""
        self.accepts(meta=dict(
            GOOD_META, editions=["necb2020", "necb2025"],
            articles={"boiler_part_load": {
                "label": "Modulating boiler part-load efficiency curve",
                "necb2020": ["8.4.5.2.(3)"],
                "necb2025": ["8.4.6.2.(2)"]}}))

    def test_a_citation_may_not_be_blank_or_repeated(self):
        """A blank cites nothing; a repeat counts one piece of evidence
        twice. Both were accepted before."""
        for values in (["   "], [""], ["8.4.4.9.(5)", "8.4.4.9.(5)"]):
            self.rejects("blank citation" if not values[0].strip()
                         else "twice",
                         meta=dict(GOOD_META, articles={"heating": {
                             "label": "Heating system",
                             "necb2020": values}}))

    def test_a_nonexistent_SENTENCE_of_a_real_article_is_refused(self):
        """Validating only the bare article admitted Sentence (999) of an
        article that does exist."""
        self.rejects("has sentences",
                     meta=dict(GOOD_META, articles={"heating": {
                         "label": "Heating system",
                         "necb2020": ["8.4.4.9.(999)"]}}))

    def test_a_citation_PREFIX_is_normalised_both_ways(self):
        """`Article 8.4.4.9.(5)` and `8.4.4.9.(5)` are one citation. Not
        normalising admitted `Article 8.4.999.1.(5)`, whose prefix hid it from
        the existence check, and refused a correct prefixed citation."""
        self.accepts(meta=dict(GOOD_META, articles={"heating": {
            "label": "Heating system",
            "necb2020": ["Article 8.4.4.9.(5)"]}}))
        self.rejects("does not exist in that edition",
                     meta=dict(GOOD_META, articles={"heating": {
                         "label": "Heating system",
                         "necb2020": ["Article 8.4.999.1.(5)"]}}))

    def test_a_citation_must_FULLMATCH_the_grammar(self):
        """A prefix match ignored anything after a valid citation and
        downgraded anything before it to unchecked scope, so arbitrary text
        rode along beside a real citation (Sol, `125`.3)."""
        for bad in ("8.4.4.9.(5) THIS IS TRAILING JUNK",
                    "junk before 8.4.4.9.(5)",
                    "not a citation"):
            with self.subTest(bad):
                self.rejects("which is not a citation",
                             meta=dict(GOOD_META, articles={"heating": {
                                 "label": "Heating system",
                                 "necb2020": [bad]}}))

    def test_a_CLAUSE_is_validated_against_ITS_OWN_sentence(self):
        """8.4.x.9's clause letters run a..i across the article, because
        Sentence (6) has nine. An unscoped check would admit `(5)(f)` where
        the Code gives Sentence (5) only clauses (a) and (b)."""
        self.accepts(meta=dict(GOOD_META, articles={"heating": {
            "label": "Heating system", "necb2020": ["8.4.4.9.(5)(a)"]}}))
        self.accepts(meta=dict(GOOD_META, articles={"heating": {
            "label": "Heating system", "necb2020": ["8.4.4.9.(6)(i)"]}}))
        for bad in ("8.4.4.9.(5)(z)", "8.4.4.9.(5)(f)"):
            with self.subTest(bad):
                self.rejects("has clauses",
                             meta=dict(GOOD_META, articles={"heating": {
                                 "label": "Heating system",
                                 "necb2020": [bad]}}))

    def test_a_TABLE_suffix_is_validated_against_the_edition(self):
        """Only Tables -A and -B exist for the system-selection article."""
        self.accepts(meta=dict(GOOD_META, articles={"selection": {
            "label": "Reference system selection",
            "necb2020": ["Table 8.4.4.7.-B"]}}))
        self.rejects("has tables",
                     meta=dict(GOOD_META, articles={"selection": {
                         "label": "Reference system selection",
                         "necb2020": ["Table 8.4.4.7.-Z"]}}))

    def test_a_requirement_key_may_not_be_BLANK(self):
        """The key and its label are the equivalence assertion, so an empty
        key asserts nothing while looking authored.

        Written as a QUOTED TOML key, which is how it reaches the validator.
        A bare whitespace key is a TOML syntax error, so the dict path used by
        `rejects` cannot express this case — the first version of this test
        asserted the wrong refusal and passed for the wrong reason.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "D-99.md"
            real = (Path(G.__file__).resolve().parents[2] / "docs"
                    / "decisions" / "D-99.md").read_text(encoding="utf-8")
            path.write_text(
                real.replace("[articles.multi_energy_heating]",
                             '[articles.""]'),
                encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                G.parse_source(path)
            self.assertIn("blank requirement key", str(caught.exception))

    def test_an_edition_may_not_be_listed_TWICE(self):
        """`check_articles` reduces editions to a set, so a duplicate was
        erased silently before reaching any check."""
        self.rejects("more than once",
                     meta=dict(GOOD_META,
                               editions=["necb2020", "necb2020"]))

    def test_validated_and_unvalidated_scope_may_not_mix_WITHIN_an_edition(self):
        """Comparing scope only ACROSS editions let every edition carry the
        same mixed set and pass."""
        self.rejects("mixes validated Section 8.4",
                     meta=dict(GOOD_META, articles={"heating": {
                         "label": "Heating system",
                         "necb2020": ["8.4.4.9.(5)", "5.2.12.1.(1)"]}}))

    def test_a_requirement_may_not_MIX_validated_and_unvalidated_scope(self):
        """Section 8.4 on one side and an unchecked citation on the other
        means half the claim was verified and half was not, with nothing
        saying which."""
        self.rejects("mixes validated Section 8.4",
                     meta=dict(GOOD_META, editions=["necb2020", "necb2025"],
                               articles={"heating": {
                                   "label": "Heating system",
                                   "necb2020": ["8.4.4.9.(5)"],
                                   "necb2025": ["5.2.12.1.(5)"]}}))

    def test_the_holding_key_and_established_editions_are_exclusive_BOTH_ways(self):
        """Checking one direction let a decision claim two code ids while
        carrying nothing but the holding pen."""
        self.rejects("go together or not at all",
                     meta=dict(GOOD_META, editions=["necb2020"],
                               articles={"unverified": []}))
        self.rejects("go together or not at all",
                     meta=dict(GOOD_META, editions=["unverified"],
                               articles={"heating": {
                                   "label": "Heating system",
                                   "necb2020": ["8.4.4.9.(5)"]}}))

    def test_a_Section_8_4_article_absent_from_that_edition_is_refused(self):
        """`8.4.4.9` is the Heating System article in NECB 2020 and does not
        exist in 2025 at all."""
        self.rejects("does not exist in that edition",
                     meta=dict(GOOD_META, editions=["necb2025"],
                               articles={"heating": {
                                   "label": "Heating system",
                                   "necb2025": ["8.4.4.9.(5)"]}}))

    def test_a_body_without_its_own_titled_heading_is_refused(self):
        self.rejects("must open with", body="Body text.\n")
        self.rejects("must open with", body="## D-01\n\nBody text.\n")
        self.rejects("must open with", body="# D-01 {} Wrong level\n".format(EM))

    def test_a_heading_naming_another_decision_is_refused(self):
        self.rejects("heading declares",
                     body="## D-02 {} Another decision\n\nBody.\n".format(EM))

    def test_trailing_newline_discipline(self):
        self.rejects("exactly one newline", body=GOOD_BODY.rstrip("\n"))
        self.rejects("exactly one newline", body=GOOD_BODY + "\n")

    def test_a_malformed_front_matter_fence_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "D-01.md"
            path.write_text('id = "D-01"\n\n' + GOOD_BODY, encoding="utf-8")
            with self.assertRaises(ValueError):
                G.parse_source(path)
            path.write_text(G.FENCE + '\nid = "D-01"\n\n' + GOOD_BODY, encoding="utf-8")
            with self.assertRaises(ValueError):
                G.parse_source(path)

    def test_the_closing_fence_needs_its_blank_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "D-01.md"
            path.write_text(G.front_matter(GOOD_META) + "\n" + GOOD_BODY,
                            encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                G.parse_source(path)
            self.assertIn("blank line", str(caught.exception))


class TestRendering(unittest.TestCase):
    """Rendering from a small synthetic source set."""

    def build(self, ids):
        directory = Path(tempfile.mkdtemp())
        for decision_id in ids:
            write(directory,
                  meta=dict(GOOD_META, id=decision_id,
                            title="Title for " + decision_id),
                  body="## {} {} Heading for {}\n\nBody of {}.\n".format(
                      decision_id, EM, decision_id, decision_id))
        (directory / G.PREAMBLE_FILE).write_text("# Log\n\nIntro.\n\n---\n\n",
                                                 encoding="utf-8")
        (directory / G.META_FILE).write_text(
            json.dumps({"registry_comment": ["generated"]}) + "\n", encoding="utf-8")
        return directory

    def test_sources_are_emitted_in_id_order_whatever_order_they_are_read_in(self):
        directory = self.build(["D-09", "D-10", "D-02"])
        doc, registry = G.generate(directory)
        self.assertEqual(["D-02", "D-09", "D-10"],
                         [e["id"] for e in json.loads(registry)["decisions"]])
        self.assertLess(doc.index("## D-02"), doc.index("## D-09"))
        self.assertLess(doc.index("## D-09"), doc.index("## D-10"))

    def test_the_order_is_taken_from_the_number_not_the_text(self):
        """Zero padding hides the difference today; the grammar will widen.

        With two-digit ids, lexical and numeric order agree, so sorting the
        strings would pass every current case. D-81 records D-99 as the id
        ceiling and requires the successor format to be adjudicated together
        with the sorting -- at which point the two diverge.
        """
        ids = ["D-100", "D-99", "D-9"]
        self.assertEqual(["D-9", "D-99", "D-100"], G.numeric_order(ids))
        self.assertNotEqual(sorted(ids), G.numeric_order(ids))

    def test_each_section_is_its_anchor_then_its_untouched_body(self):
        directory = self.build(["D-02", "D-09"])
        doc, _ = G.generate(directory)
        self.assertIn('<a id="d-02"></a>\n\n## D-02 {} Heading for D-02\n\n'
                      'Body of D-02.\n'.format(EM), doc)

    def test_the_index_lists_the_front_matter_title_not_the_heading(self):
        directory = self.build(["D-02"])
        doc, _ = G.generate(directory)
        index = doc.split(G.BEGIN_MARK)[1].split(G.END_MARK)[0]
        self.assertIn("Title for D-02", index)
        self.assertNotIn("Heading for D-02", index)

    def test_an_empty_source_directory_is_an_error_not_an_empty_log(self):
        directory = Path(tempfile.mkdtemp())
        (directory / G.PREAMBLE_FILE).write_text("# Log\n", encoding="utf-8")
        (directory / G.META_FILE).write_text('{"registry_comment": []}\n',
                                             encoding="utf-8")
        with self.assertRaises(ValueError):
            G.generate(directory)


class TestStrayFilesAreRefused(unittest.TestCase):
    """A decision the `D-*.md` glob misses must be REFUSED, not skipped.

    This module's contract is that each rule is shown to reject something. The
    first fix for this had no rejection test at all, and the positive assertion
    that "covered" it reimplemented the production expression, so the guard
    could be deleted with the suite green (Fable, PR #64).
    """

    def sources(self):
        directory = Path(tempfile.mkdtemp())
        write(directory)
        (directory / G.PREAMBLE_FILE).write_text("# Log\n\n---\n", encoding="utf-8")
        (directory / G.META_FILE).write_text(
            json.dumps({"registry_comment": ["generated"]}) + "\n", encoding="utf-8")
        return directory

    def test_a_missed_decision_filename_is_refused(self):
        # The list is the THREAT MODEL, not the implementation's coverage. The
        # first version mirrored what the predicate already caught, so four real
        # shapes were missing from it -- including `D-98.md ` with a trailing
        # space, which survives copy-paste and is visually identical to a correct
        # filename (Fable, PR #64).
        for name in ("d-98.md", "D-98.MD", "D98.md", "D-98.markdown",
                     "README.md", "_template.md",
                     "D-98", "D-98.txt", "D-98.md.bak", "D-98.md ", "D_98.md"):
            with self.subTest(name=name):
                directory = self.sources()
                (directory / name).write_text(
                    G.source_text(dict(GOOD_META, id="D-98"),
                                  "## D-98 {} Heading\n".format(EM)),
                    encoding="utf-8")
                self.assertEqual([name], G.stray_files(directory))
                with self.assertRaises(ValueError) as caught:
                    G.read_sources(directory)
                self.assertIn(name, str(caught.exception))

    def test_a_nested_or_symlinked_directory_is_refused(self):
        """`rglob` does not descend a directory symlink and never calls
        `is_file()` on it, so a linked-in directory of sources slipped past."""
        directory = self.sources()
        nested = directory / "sub"
        nested.mkdir()
        (nested / "D-98.md").write_text("x", encoding="utf-8")
        self.assertEqual(["sub/D-98.md"], G.stray_files(directory))

        linked = self.sources()
        elsewhere = Path(tempfile.mkdtemp()) / "held"
        elsewhere.mkdir()
        (elsewhere / "D-98.md").write_text("x", encoding="utf-8")
        (linked / "extra").symlink_to(elsewhere, target_is_directory=True)
        self.assertEqual(["extra (symlink)"], G.stray_files(linked))
        with self.assertRaises(ValueError):
            G.read_sources(linked)

    def test_editor_and_os_debris_is_NOT_refused(self):
        """The predicate must not stop a developer running the gate.

        `.D-01.md.swp` exists while a vim buffer is open. Failing on it trains
        people around the gate rather than through it (Fable, PR #64).
        """
        directory = self.sources()
        for name in (".DS_Store", ".D-01.md.swp", "D-01.md~", ".gitkeep",
                     "notes.txt", "LICENSE", "README.txt",
                     # emacs's lock file, as a PLAIN file
                     ".#D-01.md"):
            (directory / name).write_text("x", encoding="utf-8")
        self.assertEqual([], G.stray_files(directory))
        G.read_sources(directory)          # must not raise
        # and in the shape it actually takes: a symlink to a target that does
        # not exist, which must be skipped BEFORE the symlink arm. The lock is
        # named after the file being edited, so `D-01.md` is a real source here —
        # `.#D-02.md` would correctly be refused, there being no `D-02.md`.
        (directory / ".#D-01.md").unlink()
        (directory / ".#D-01.md").symlink_to("user@host.1234:1700000000")
        self.assertEqual([], G.stray_files(directory))
        G.read_sources(directory)          # must not raise

    def test_an_emacs_lock_exemption_is_bounded_to_real_sources(self):
        """`.#X` is debris only when `X` is a source the glob already reached.

        A bare `.#` prefix was too broad in both directions: a complete decision
        in `.#D-98.md` was silently lost, and `.#extra` pointing at a directory
        escaped the symlink arm entirely, because the exemption precedes it
        (Fable, PR #64). Emacs names its lock after the file being edited, so
        bounding it this way costs the real case nothing.
        """
        directory = self.sources()
        # a decision hidden behind the prefix is NOT debris
        (directory / ".#D-98.md").write_text("x", encoding="utf-8")
        self.assertEqual([".#D-98.md"], G.stray_files(directory))
        (directory / ".#D-98.md").unlink()
        # nor is a symlink that merely wears the prefix
        (directory / ".#extra").symlink_to("/etc")
        self.assertEqual([".#extra (symlink)"], G.stray_files(directory))

    def test_a_dotted_decision_source_still_fires(self):
        """The `.#` exemption must not become a blanket dotfile skip again.

        `.D-98.md` is a decision-shaped Markdown source, invisible to the
        `D-*.md` glob — the case the blanket skip hid (Sol, PR #64).
        """
        directory = self.sources()
        (directory / ".D-98.md").write_text("x", encoding="utf-8")
        self.assertEqual([".D-98.md"], G.stray_files(directory))
        (directory / ".D-98.md").unlink()
        # and a symlink NAMED like a decision is still refused as a symlink
        (directory / "D-98.md").symlink_to("../../elsewhere.md")
        self.assertEqual(["D-98.md (symlink)"], G.stray_files(directory))

    def test_an_unexpected_meta_key_is_refused(self):
        """Front matter refuses one; this refused nothing, so an edit could
        silently take no effect (Fable, PR #64)."""
        directory = self.sources()
        (directory / G.META_FILE).write_text(
            json.dumps({"registry_comment": [], "doc_title": "never appears"}) + "\n",
            encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            G.read_sources(directory)
        self.assertIn("doc_title", str(caught.exception))

    def test_an_underscore_annotation_is_allowed(self):
        """`_`-prefixed keys are the conventional annotation marker, and
        `decisions.json` uses `_comment` for exactly that. Refusing one repeated
        the mistake of refusing a `.DS_Store` (Fable, PR #64)."""
        directory = self.sources()
        (directory / G.META_FILE).write_text(
            json.dumps({"registry_comment": ["x"], "_comment": "a note"}) + "\n",
            encoding="utf-8")
        G.read_sources(directory)          # must not raise

    def test_registry_comment_must_be_a_list_of_strings(self):
        """Every front-matter field is type-checked; this one was not, so a plain
        string shipped a `str` where readers expect a list (Fable, PR #64)."""
        for value in ("a plain string", 42, {"a": 1}, ["ok", 3]):
            with self.subTest(value=value):
                directory = self.sources()
                (directory / G.META_FILE).write_text(
                    json.dumps({"registry_comment": value}) + "\n", encoding="utf-8")
                with self.assertRaises(ValueError) as caught:
                    G.read_sources(directory)
                self.assertIn("registry_comment", str(caught.exception))


class TestCheckReportsStaleWithoutWriting(unittest.TestCase):
    """`--check` must return 1 on drift and write nothing.

    The base had exactly this test against the retired TOC generator
    (`test_check_reports_stale_without_writing`), and it was deleted with that
    module while its two siblings were genuinely superseded. This one was not:
    mutating `main()` so that `stale` is always empty survived all 49 tests
    (Fable, PR #64).

    It matters because `--check` is documented in CLAUDE.md, DEVELOPERS.md and
    the multi-edition plan as a standalone local gate, run as a one-liner
    WITHOUT the pytest modules that redundantly cover the same invariant.
    """

    def scratch(self):
        """A source directory plus a SEPARATE output directory.

        The outputs deliberately do not live beside the sources: the stray-file
        guard refuses anything in the canonical directory that the `D-*.md`
        glob does not reach, and it caught this test's first draft writing
        `doc.md` and `registry.json` in there. Production keeps them apart too.
        """
        root = Path(tempfile.mkdtemp())
        directory, outputs = root / "sources", root / "outputs"
        directory.mkdir()
        outputs.mkdir()
        write(directory)
        (directory / G.PREAMBLE_FILE).write_text("# Log\n\nIntro.\n\n---\n",
                                                 encoding="utf-8")
        (directory / G.META_FILE).write_text(
            json.dumps({"registry_comment": ["generated"]}) + "\n",
            encoding="utf-8")
        doc, registry = outputs / "doc.md", outputs / "registry.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, G.main(["--source-dir", str(directory),
                                        "--doc", str(doc),
                                        "--registry", str(registry)]))
        return directory, doc, registry

    def check(self, directory, doc, registry):
        """``--check``'s exit code, with its reporting captured."""
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return G.main(self.args(directory, doc, registry))

    def args(self, directory, doc, registry):
        return ["--check", "--source-dir", str(directory),
                "--doc", str(doc), "--registry", str(registry)]

    def test_check_passes_when_in_step(self):
        directory, doc, registry = self.scratch()
        self.assertEqual(0, self.check(directory, doc, registry))

    def test_a_hand_edited_document_reports_stale_and_is_not_rewritten(self):
        directory, doc, registry = self.scratch()
        tampered = doc.read_text(encoding="utf-8") + "a hand edit\n"
        doc.write_text(tampered, encoding="utf-8")
        before = doc.read_bytes()

        self.assertEqual(1, self.check(directory, doc, registry),
                         "--check must return 1 on drift")
        self.assertEqual(before, doc.read_bytes(),
                         "--check must not rewrite the file it is checking")

    def test_a_hand_edited_registry_reports_stale_and_is_not_rewritten(self):
        directory, doc, registry = self.scratch()
        data = json.loads(registry.read_text(encoding="utf-8"))
        data["decisions"][0]["title"] = "tampered"
        registry.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        before = registry.read_bytes()

        self.assertEqual(1, self.check(directory, doc, registry))
        self.assertEqual(before, registry.read_bytes())

    def test_a_missing_output_fails_closed(self):
        """It raises rather than reporting stale. Documented, not relied upon:
        the exit is non-zero either way, but a reader should know which."""
        directory, doc, registry = self.scratch()
        doc.unlink()
        with self.assertRaises(FileNotFoundError):
            self.check(directory, doc, registry)


class TestSplitIsNotAWriter(unittest.TestCase):
    def test_split_refuses_a_directory_that_already_holds_sources(self):
        directory = Path(tempfile.mkdtemp())
        write(directory)

        class Args:
            source_dir = directory
            doc = Path("unused")
            registry = Path("unused")

        self.assertEqual(1, G.run_split(Args()))


class TestTheEditionsField(unittest.TestCase):
    """phylroy, 2026-10-07: a decision taken against one edition's text read as
    applying to every edition, because the front matter said nothing about
    which code it governs. An authority has to know WHICH code their project
    is under.

    The field lists CODE IDS, validated against the editions discovered under
    `btap/codes/necb/data/`, or the single literal `unverified`. It is never a
    collective word: "both" would stop meaning anything the moment a third
    edition is registered, and `vintage` is retired vocabulary.
    """

    def test_a_registered_code_id_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, meta=dict(GOOD_META, editions=["necb2025"],
                               articles={"hydronic_pumps": {
                                   "label": "Hydronic pump power",
                                   "necb2025": ["8.4.5.14."]}}))
            G.parse_source(Path(d) / "D-01.md")     # must not raise

    def test_unverified_alone_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, meta=dict(GOOD_META, editions=["unverified"],
                               articles={"unverified": ["8.4.4.14."]}))
            G.parse_source(Path(d) / "D-01.md")

    def test_an_UNREGISTERED_code_id_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, meta=dict(GOOD_META, editions=["necb2030"],
                               articles={"unverified": []}))
            with self.assertRaises(ValueError) as caught:
                G.parse_source(Path(d) / "D-01.md")
            self.assertIn("necb2030", str(caught.exception))

    def test_a_COLLECTIVE_word_is_refused(self):
        """The failure mode this field exists to prevent."""
        with tempfile.TemporaryDirectory() as d:
            write(d, meta=dict(GOOD_META, editions=["both"],
                               articles={"unverified": []}))
            with self.assertRaises(ValueError):
                G.parse_source(Path(d) / "D-01.md")

    def test_unverified_may_not_be_MIXED_with_a_code_id(self):
        """Either it has been checked against that edition or it has not."""
        with tempfile.TemporaryDirectory() as d:
            write(d, meta=dict(GOOD_META,
                               editions=["necb2020", "unverified"],
                               articles={"unverified": []}))
            with self.assertRaises(ValueError):
                G.parse_source(Path(d) / "D-01.md")

    def test_an_empty_list_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, meta=dict(GOOD_META, editions=[],
                               articles={"unverified": []}))
            with self.assertRaises(ValueError):
                G.parse_source(Path(d) / "D-01.md")

    def test_the_allowed_ids_are_DISCOVERED_not_hardcoded(self):
        """So registering a new edition does not leave the validation stale."""
        codes = G.registered_codes()
        self.assertIn("necb2020", codes)
        self.assertIn("necb2025", codes)
        self.assertNotIn("unverified", codes)


class TestStructuredSources(unittest.TestCase):
    """The structured requirement form: ``label``, ``decided`` and one
    ``[[articles.<key>.sources]]`` record per code, edition and role.

    Each refusal is driven by a copy of `STRUCTURED_META` that breaks exactly
    one rule, and the unmodified fixture is the control that the rule does
    not also refuse a correct record.
    """

    def check(self, meta):
        G.validate(meta["id"] + ".md", meta, GOOD_BODY)

    def rejects(self, message, meta):
        with self.assertRaises(ValueError) as caught:
            self.check(meta)
        self.assertIn(message, str(caught.exception))
        return str(caught.exception)

    # ------------------------------------------------------------ accepted

    def test_the_representative_record_round_trips_through_its_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write(directory, meta=structured())
            text = path.read_text(encoding="utf-8")
            meta, body = G.parse_source(path)
        self.assertEqual(STRUCTURED_META, meta)
        self.assertEqual(GOOD_BODY, body)
        self.assertEqual(text, G.source_text(meta, body),
                         "a structured source must rewrite to itself")
        self.assertNotIn("editions", meta, "editions is derived, not authored")

    def test_editions_is_DERIVED_from_the_governing_sources(self):
        self.assertEqual(["necb2020", "necb2025"],
                         G.governing_code_ids(STRUCTURED_META["articles"]))

    def test_an_authored_editions_EQUAL_to_the_derivation_is_accepted(self):
        self.check(structured(editions=["necb2020", "necb2025"]))

    def test_an_authored_editions_that_CONFLICTS_is_refused(self):
        for editions in (["necb2020"], ["necb2025"], ["unverified"],
                         ["necb2025", "necb2020"]):
            with self.subTest(editions=editions):
                self.rejects("but the governing sources derive",
                             structured(editions=editions))

    def test_related_and_incorporated_sources_never_establish_an_edition(self):
        def demote_2025(meta):
            record(meta, 1)["role"] = "related"

        meta = structured(demote_2025)
        self.check(meta)
        self.assertEqual(["necb2020"], G.governing_code_ids(meta["articles"]))
        self.check(structured(demote_2025, editions=["necb2020"]))
        self.rejects("but the governing sources derive",
                     structured(demote_2025, editions=["necb2020", "necb2025"]))

    def test_a_FUTURE_edition_may_be_cited_as_related_and_is_disclosed(self):
        """Its reference repeats a governing 2020 citation, which is the
        control that one-role-per-provision is keyed by edition as well."""
        def cite_2030(meta):
            requirement(meta)["sources"].append(
                {"code": "necb", "edition": "2030", "role": "related",
                 "references": ["8.4.4.13.(1)"]})

        meta = structured(cite_2030)
        self.check(meta)
        self.assertEqual(["necb2020", "necb2025"],
                         G.governing_code_ids(meta["articles"]))
        self.assertIn(("D-01", KEY, "necb", "2030", "related"),
                      G.unvalidated_sources({"D-01": (meta, GOOD_BODY)}))

    def test_only_sources_no_index_validates_are_disclosed(self):
        """The registered necb 2020 related record is validated, so it is not
        listed; the external standard is carried as authored, so it is."""
        self.assertEqual(
            [("D-01", KEY, "ashrae-62.1", "2016", "incorporated-reference")],
            G.unvalidated_sources({"D-01": (structured(), GOOD_BODY),
                                   "D-02": (dict(GOOD_META, id="D-02"),
                                            GOOD_BODY)}))

    def test_an_external_standard_keeps_its_own_citation_grammar(self):
        self.check(structured(lambda m: record(m, 3).update(
            references=["Section 6.2.2.1", "Table 6-1"])))

    def test_an_addendum_style_edition_string_is_accepted(self):
        self.check(structured(lambda m: record(m, 3).update(
            edition="2016-addendum-a1")))

    def test_one_code_and_edition_may_carry_two_roles(self):
        """The fixture's necb 2020 governing and related records: the record
        identity is code, edition AND role."""
        roles = [(r["code"], r["edition"], r["role"])
                 for r in requirement(STRUCTURED_META)["sources"]]
        self.assertIn(("necb", "2020", "governing"), roles)
        self.assertIn(("necb", "2020", "related"), roles)
        self.check(structured())

    def test_requirements_that_govern_the_same_editions_are_accepted(self):
        self.check(structured(self.second_requirement(both_editions=True)))

    # ------------------------------------------- mixing the legacy forms

    def test_the_legacy_holding_keys_may_not_sit_beside_sources(self):
        for reserved, value in (("unverified", ["8.4.4.13.(1)"]),
                                ("not_applicable", [])):
            with self.subTest(reserved=reserved):
                meta = structured(
                    lambda m, r=reserved, v=value: m["articles"].update({r: v}))
                self.rejects("may not mix the legacy {!r} key".format(reserved),
                             meta)
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaises(ValueError) as caught:
                        G.parse_source(write(directory, meta=meta))
                self.assertIn("may not mix the legacy", str(caught.exception))

    def test_a_legacy_requirement_may_not_sit_beside_a_structured_one(self):
        def add_legacy(meta):
            meta["articles"]["hydronic_pumps"] = {
                "label": "Hydronic pump power", "necb2020": ["8.4.4.14."]}

        for over in ({}, {"editions": ["necb2020", "necb2025"]}):
            with self.subTest(**over):
                message = self.rejects(
                    "convert every requirement of a decision together",
                    structured(add_legacy, **over))
                self.assertIn("hydronic_pumps", message)

    def test_a_half_converted_requirement_is_refused_by_name(self):
        """``decided`` beside per-edition lists reaches the structured
        validator, which names the leftover key, rather than the legacy one,
        which would call ``decided`` an unregistered code id."""
        def half(meta):
            requirement(meta).pop("sources")
            requirement(meta)["necb2020"] = ["8.4.4.13.(1)"]

        self.rejects("has unexpected key(s) ['necb2020']", structured(half))

    def second_requirement(self, both_editions):
        def add(meta):
            sources = [{"code": "necb", "edition": "2020", "role": "governing",
                        "references": ["8.4.4.13.(2)(a)"]}]
            if both_editions:
                sources.append({"code": "necb", "edition": "2025",
                                "role": "governing",
                                "references": ["8.4.5.13.(2)"]})
            meta["articles"]["water_loop_branch"] = {
                "label": "Water-loop heat pump branch",
                "decided": "The water-loop branch is selected by heat source.",
                "sources": sources}
        return add

    def test_requirements_must_govern_the_same_editions(self):
        self.rejects("requirements govern different editions",
                     structured(self.second_requirement(both_editions=False)))

    # -------------------------------------------------- the requirement

    def test_a_requirement_key_must_be_a_stable_id(self):
        for key in ("Heat_pump", "heat-pump", "1heat", "heat pump", ""):
            with self.subTest(key=key):
                self.rejects("must match", structured(
                    lambda m, k=key: m.update(articles={k: requirement(m)})))

    def test_a_requirement_carries_only_label_decided_and_sources(self):
        self.rejects("has unexpected key(s) ['necb2020']", structured(
            lambda m: requirement(m).update(necb2020=["8.4.4.13.(1)"])))

    def test_label_and_decided_must_be_non_empty_strings(self):
        for field in ("label", "decided"):
            for value in ("", "   ", 3, None, ["text"]):
                with self.subTest(field=field, value=value):
                    self.rejects(
                        "needs a non-empty {} string".format(field),
                        structured(lambda m, f=field, v=value:
                                   requirement(m).update({f: v})))
            with self.subTest(field=field, value="missing"):
                self.rejects("needs a non-empty {} string".format(field),
                             structured(lambda m, f=field:
                                        requirement(m).pop(f)))

    def test_decided_may_not_repeat_the_decision_wide_summary(self):
        for decided in (STRUCTURED_META["summary"],
                        "  a PARAPHRASE of what\nwas decided.  "):
            with self.subTest(decided=decided):
                self.rejects("repeats the decision-wide summary", structured(
                    lambda m, d=decided: requirement(m).update(decided=d)))

    def test_a_requirement_needs_at_least_one_source_record(self):
        message = "needs at least one [[articles.{}.sources]] record".format(KEY)
        for sources in ([], "necb 2020", {"code": "necb"}):
            with self.subTest(sources=sources):
                self.rejects(message, structured(
                    lambda m, s=sources: requirement(m).update(sources=s)))
        self.rejects(message, structured(
            lambda m: requirement(m).pop("sources")))

    def test_one_record_per_code_edition_and_role(self):
        self.rejects(
            "repeats code='necb' edition='2020' role='governing'",
            structured(lambda m: requirement(m)["sources"].append(
                {"code": "necb", "edition": "2020", "role": "governing",
                 "references": ["8.4.4.13.(2)(a)"]})))

    def test_a_governing_source_must_be_a_registered_runtime_edition(self):
        for code, edition, reference in (("necb", "2030", "8.4.4.13.(1)"),
                                         ("ashrae-62.1", "2016", "6.2.2.1")):
            with self.subTest(code=code, edition=edition):
                message = self.rejects(
                    "is not a registered runtime edition",
                    structured(lambda m, c=code, e=edition, r=reference:
                               requirement(m)["sources"].append(
                                   {"code": c, "edition": e,
                                    "role": "governing", "references": [r]})))
                self.assertIn("(necb 2020, necb 2025)", message)

    def test_one_provision_has_one_role_in_a_requirement(self):
        self.rejects("one provision has one role", structured(
            lambda m: record(m, 2)["references"].append("8.4.4.13.(1)")))

    def test_a_requirement_needs_a_governing_source(self):
        self.rejects("has no governing source", structured(
            lambda m: requirement(m).update(sources=requirement(m)["sources"][2:])))

    # -------------------------------------------------------- one record

    def test_a_source_record_must_be_a_table(self):
        for value in ("necb 2020", ["necb", "2020"], 7):
            with self.subTest(value=value):
                self.rejects("source 1 must be a table", structured(
                    lambda m, v=value: requirement(m)["sources"].__setitem__(0, v)))

    def test_a_source_record_has_exactly_its_four_fields(self):
        self.rejects("unexpected ['note'] / missing []", structured(
            lambda m: record(m, 0).update(note="x")))
        for field in ("code", "edition", "role", "references"):
            with self.subTest(missing=field):
                self.rejects("unexpected [] / missing [{!r}]".format(field),
                             structured(lambda m, f=field: record(m, 0).pop(f)))

    def test_code_is_a_stable_lower_case_family_id(self):
        for code in ("NECB", "Necb", "necb 2020", "", "ashrae_62.1", "-necb",
                     "necb.", 7, None):
            with self.subTest(code=code):
                self.rejects("is not a stable lower-case family id", structured(
                    lambda m, c=code: record(m, 0).update(code=c)))

    def test_a_runtime_code_id_is_not_a_family(self):
        for code_id, family, edition in (("necb2020", "necb", "2020"),
                                         ("necb2025", "necb", "2025")):
            with self.subTest(code=code_id):
                message = self.rejects(
                    "is a runtime code id, not a family",
                    structured(lambda m, c=code_id: record(m, 3).update(code=c)))
                self.assertIn("write code = {!r} and edition = {!r}".format(
                    family, edition), message)

    def test_edition_is_a_QUOTED_string(self):
        for edition, kind in ((2020, "int"), (2020.0, "float")):
            with self.subTest(edition=edition):
                self.rejects(
                    "edition must be a quoted string, got {}".format(kind),
                    structured(lambda m, e=edition: record(m, 0).update(edition=e)))

    def test_a_malformed_edition_is_refused(self):
        for edition in ("", "2020 ", "NECB2020", "2020-", "20 20", "2020/a1"):
            with self.subTest(edition=edition):
                self.rejects("is malformed", structured(
                    lambda m, e=edition: record(m, 3).update(edition=e)))

    def test_role_is_one_of_three(self):
        for role in ("Governing", "incorporated", "informative", "", None):
            with self.subTest(role=role):
                self.rejects(
                    "is not one of governing, incorporated-reference, related",
                    structured(lambda m, r=role: record(m, 3).update(role=r)))

    def test_references_are_a_non_empty_list_of_clean_distinct_strings(self):
        """On a validated record AND an external one: these checks are the
        whole of what an external source gets, so they must not depend on a
        provision index."""
        cases = (
            ([], "references must be a non-empty list"),
            ("8.4.4.13.(1)", "references must be a non-empty list"),
            ([1], "not a non-blank string"),
            ([""], "not a non-blank string"),
            (["  "], "not a non-blank string"),
            ([" 8.4.4.13.(1)"], "carries stray whitespace"),
            (["8.4.4.13.(1) "], "carries stray whitespace"),
            (["Note  A-8.4.4.13"], "carries stray whitespace"),
            (["8.4.4.13.(1)", "8.4.4.13.(1)"], "cites '8.4.4.13.(1)' twice"),
        )
        for index in (0, 3):
            for references, message in cases:
                with self.subTest(record=index, references=references):
                    self.rejects(message, structured(
                        lambda m, i=index, r=references:
                        record(m, i).update(references=r)))

    # -------------------------------------- against the provision index

    def test_a_reference_must_use_the_canonical_spelling(self):
        cases = (
            (0, 0, "Sentence 8.4.4.13.(1)", "8.4.4.13.(1)"),
            (0, 0, "8.4.4.13(1)", "8.4.4.13.(1)"),
            (0, 0, "Division B 8.4.4.13.(1)", "8.4.4.13.(1)"),
            (0, 2, "Note A-8.4.4.13.", "Note A-8.4.4.13"),
            (2, 0, "division a 1.1.1.1.(1)", "Division A 1.1.1.1.(1)"),
        )
        for index, position, written, canonical in cases:
            with self.subTest(written=written):
                message = self.rejects(
                    "is not the canonical spelling -- write {!r}".format(canonical),
                    structured(lambda m, i=index, p=position, w=written:
                               record(m, i)["references"].__setitem__(p, w)))
                self.assertIn(repr(written), message)

    def test_a_malformed_NECB_citation_is_refused(self):
        for reference in ("8.4.4", "Table 8.4.4.7-B", "A-8.4.4.13",
                          "8.4.4.13.(2) (g)"):
            with self.subTest(reference=reference):
                self.rejects("malformed NECB provision citation", structured(
                    lambda m, r=reference: record(m, 0)["references"].append(r)))

    def test_an_unregistered_NECB_edition_still_uses_NECB_grammar(self):
        """No index validates necb 2030, but its family's grammar does: a
        related record cannot carry a spelling no edition would accept."""
        for reference, message in (
                ("Note A-8.4.4.13.", "is not the canonical spelling"),
                ("8.4.4", "malformed NECB provision citation")):
            with self.subTest(reference=reference):
                self.rejects(message, structured(
                    lambda m, r=reference: requirement(m)["sources"].append(
                        {"code": "necb", "edition": "2030", "role": "related",
                         "references": [r]})))

    def test_a_reference_must_be_PRESENT_in_its_edition_index(self):
        cases = (
            (0, "8.4.4.13.(3)",
             "8.4.4.13.(3) is absent from the complete child inventory of "
             "8.4.4.13 in necb2020"),
            (0, "8.4.1.5", "8.4.1.5 is authority-confirmed absent from necb2020"),
            (0, "8.4.4.9.(5)", "8.4.4.9.(5) has no committed evidence in necb2020"),
            (0, "8.4.5.13.(1)", "8.4.5.13.(1) has no committed evidence in necb2020"),
            (1, "8.4.4.13.(1)", "8.4.4.13.(1) has no committed evidence in necb2025"),
            (2, "Table 8.4.4.7.-B Note (9)",
             "Table 8.4.4.7.-B Note (9) is absent from the complete child "
             "inventory of Table 8.4.4.7.-B in necb2020"),
            (0, "Note A-8.4.4.99",
             "Note A-8.4.4.99 has no committed evidence in necb2020"),
            (2, "Table 8.4.4.7.-Z",
             "Table 8.4.4.7.-Z has no committed evidence in necb2020"),
        )
        for index, reference, detail in cases:
            with self.subTest(reference=reference, record=index):
                message = self.rejects(detail, structured(
                    lambda m, i=index, r=reference:
                    record(m, i)["references"].append(r)))
                self.assertIn("a source must cite a provision its edition's "
                              "index records as present", message)
                self.assertNotIn(" is present (", message,
                                 "no present neighbour, so no hint")

    def test_an_ARTICLE_cited_as_a_TABLE_is_refused_with_a_hint(self):
        message = self.rejects(
            "Table 8.4.4.13 has no committed evidence in necb2020",
            structured(lambda m: record(m, 0)["references"].append(
                "Table 8.4.4.13")))
        self.assertIn("; 8.4.4.13 is present (an Article and a Table are "
                      "different provisions)", message)

    def test_an_UNQUALIFIED_Division_A_citation_is_refused_with_a_hint(self):
        message = self.rejects(
            "1.1.1.1.(2) is absent from the complete child inventory",
            structured(lambda m: record(m, 2)["references"].append("1.1.1.1.(2)")))
        self.assertIn("; Division A 1.1.1.1.(2) is present (an unqualified "
                      "number is Division B, so a Division A citation says so)",
                      message)
        self.check(structured(lambda m: record(m, 2)["references"].append(
            "Division A 1.1.1.1.(2)")))

    def stubbed(self, status, provision=None, reference="8.4.4.13.(1)",
                code_id="necb2020"):
        """`check_citation` answering ``status`` for one reference, and the
        committed index for every other: the stale, unsupported and
        unknown-status branches cannot be reached through committed data."""
        real = G.provisions.check_citation

        def fake(code, value):
            if code == code_id and value == reference:
                citation = G.provisions.parse_citation(value, family="necb")
                return G.provisions.ProvisionCheck(
                    code, citation, status, "stub detail for " + value,
                    provision)
            return real(code, value)

        return mock.patch.object(G.provisions, "check_citation", fake)

    def test_the_stub_itself_admits_a_present_record(self):
        with self.stubbed("present", {"kind": "sentence", "status": "present"}):
            self.check(structured())

    def test_a_TABLE_cited_as_an_ARTICLE_is_refused_with_a_hint(self):
        """Neither committed index has a suffix-less table, so the reverse
        direction runs on a stub that holds ``Table 8.4.4.13``."""
        real = G.provisions.check_citation

        def fake(code, value):
            citation = G.provisions.parse_citation(value, family="necb")
            if code == "necb2020" and citation.canonical == "Table 8.4.4.13":
                return G.provisions.ProvisionCheck(
                    code, citation, "present", "present",
                    {"kind": "table", "status": "present"})
            if code == "necb2020" and citation.canonical == "8.4.4.13":
                return G.provisions.ProvisionCheck(
                    code, citation, "not-indexed",
                    "8.4.4.13 has no committed evidence in necb2020")
            return real(code, value)

        with mock.patch.object(G.provisions, "check_citation", fake):
            message = self.rejects(
                "8.4.4.13 has no committed evidence in necb2020",
                structured(lambda m: record(m, 0)["references"].append(
                    "8.4.4.13")))
        self.assertIn("; Table 8.4.4.13 is present (an Article and a Table are "
                      "different provisions)", message)

    def test_a_STALE_index_is_refused(self):
        with self.stubbed("stale"):
            self.rejects("refresh the provision index", structured())

    def test_a_registered_edition_with_NO_index_is_refused(self):
        with self.stubbed("unsupported"):
            self.rejects("its provision index, and there is none", structured())

    def test_an_UNKNOWN_status_fails_closed(self):
        with self.stubbed("plausible"):
            self.rejects("unexpected provision status 'plausible'", structured())

    def test_a_present_record_of_another_KIND_is_refused(self):
        with self.stubbed("present", {"kind": "table", "status": "present"}):
            self.rejects("records '8.4.4.13.(1)' as a table, but the citation "
                         "is a sentence", structured())
        with self.stubbed("present", None):
            self.rejects("records '8.4.4.13.(1)' as a None", structured())

    def test_an_unreadable_index_is_refused_with_its_location(self):
        def broken(code, value):
            raise G.provisions.ProvisionIndexError("index is corrupt")

        with mock.patch.object(G.provisions, "check_citation", broken):
            self.rejects("articles['{}'] source 1: index is corrupt".format(KEY),
                         structured())


class TestStructuredWriter(unittest.TestCase):
    """The writer emits a structured requirement as a table plus a TOML
    ARRAY OF TABLES, and parses back to exactly what it was given."""

    SMALL = {
        "id": "D-01", "title": "T", "kind": "runtime",
        "articles": {"k": {"label": "L", "decided": "D", "sources": [
            {"code": "necb", "edition": "2020", "role": "governing",
             "references": ["8.4.4.13.(1)", "Note A-8.4.4.13"]},
            {"code": "ashrae-62.1", "edition": "2016",
             "role": "incorporated-reference", "references": ["6.2.2.1"]}]}},
        "summary": "S",
    }

    def test_the_exact_layout(self):
        """One record per ``[[...]]`` header, in authored order, one reference
        per line, so a review diff shows exactly which citation moved."""
        self.assertEqual("\n".join([
            "+++",
            'id = "D-01"',
            'title = "T"',
            'kind = "runtime"',
            'summary = "S"',
            "",
            "[articles.k]",
            'label = "L"',
            'decided = "D"',
            "",
            "[[articles.k.sources]]",
            'code = "necb"',
            'edition = "2020"',
            'role = "governing"',
            "references = [",
            '  "8.4.4.13.(1)",',
            '  "Note A-8.4.4.13",',
            "]",
            "",
            "[[articles.k.sources]]",
            'code = "ashrae-62.1"',
            'edition = "2016"',
            'role = "incorporated-reference"',
            "references = [",
            '  "6.2.2.1",',
            "]",
            "+++",
        ]), G.front_matter(self.SMALL))

    def test_an_authored_editions_is_written_in_its_field_position(self):
        lines = G.front_matter(dict(self.SMALL, editions=["necb2020"])).split("\n")
        self.assertEqual('editions = ["necb2020"]', lines[4])
        self.assertEqual('summary = "S"', lines[5])
        self.assertFalse(any(line.startswith("editions")
                             for line in G.front_matter(self.SMALL).split("\n")))

    def test_the_writer_is_the_inverse_of_the_parser(self):
        for case, meta in enumerate((self.SMALL, structured(),
                                     structured(editions=["necb2020", "necb2025"]))):
            with self.subTest(case=case):
                self.assertEqual(meta, tomllib.loads(inner(G.front_matter(meta))))

    def test_requirements_in_key_order_and_records_in_AUTHORED_order(self):
        def shape(meta):
            requirement(meta)["sources"].reverse()
            block = copy.deepcopy(requirement(meta))
            meta["articles"] = {"zeta_req": block, KEY: requirement(meta),
                                "alpha_req": copy.deepcopy(block)}

        meta = structured(shape)
        text = G.front_matter(meta)
        positions = [text.index("[articles.{}]".format(key))
                     for key in ("alpha_req", KEY, "zeta_req")]
        self.assertEqual(sorted(positions), positions)
        parsed = tomllib.loads(inner(text))
        self.assertEqual(["alpha_req", KEY, "zeta_req"], list(parsed["articles"]))
        self.assertEqual(meta["articles"][KEY]["sources"],
                         parsed["articles"][KEY]["sources"])
        self.assertEqual("ashrae-62.1",
                         parsed["articles"][KEY]["sources"][0]["code"])

    def test_hostile_text_cannot_break_out_of_the_array_of_tables(self):
        meta = dict(self.SMALL, articles={"k": {
            "label": 'x"\n[[articles.k.sources]]\ncode = "evil',
            "decided": 'a"]\n[articles.z]\nlabel = "b',
            "sources": [{
                "code": 'necb"\nrole = "governing',
                "edition": "2020\n]",
                "role": "re\\lated",
                "references": ['8.4"\n]\nreferences = ["x', "tab\there", "]"]}]}})
        self.assertEqual(meta, tomllib.loads(inner(G.front_matter(meta))))

    def test_the_writer_refuses_what_it_cannot_write_faithfully(self):
        cases = (
            (ValueError, "must match", lambda m: m.update(
                articles={"a]\n[x": requirement(m)})),
            (ValueError, "must match", lambda m: m.update(
                articles={"Heat_Pump": requirement(m)})),
            (ValueError, "unexpected ['necb2020'] / missing []",
             lambda m: requirement(m).update(necb2020=["8.4.4.13.(1)"])),
            (ValueError, "missing ['decided']",
             lambda m: requirement(m).pop("decided")),
            (ValueError, "sources must be a list of tables",
             lambda m: requirement(m).update(sources="necb")),
            (ValueError, "has a source that is not a table",
             lambda m: requirement(m)["sources"].__setitem__(0, "necb 2020")),
            (ValueError, "source unexpected ['note'] / missing []",
             lambda m: record(m, 0).update(note="x")),
            (ValueError, "source unexpected [] / missing ['role']",
             lambda m: record(m, 0).pop("role")),
            (TypeError, "not a string: 2020",
             lambda m: record(m, 0).update(edition=2020)),
            (TypeError, "not a list of references",
             lambda m: record(m, 0).update(references="8.4.4.13.(1)")),
            (TypeError, "not a string: 1",
             lambda m: record(m, 0).update(references=[1])),
        )
        for error, message, edit in cases:
            with self.subTest(message=message):
                with self.assertRaises(error) as caught:
                    G.front_matter(structured(edit))
                self.assertIn(message, str(caught.exception))


class TestSchemaTwoRegistry(unittest.TestCase):
    """`decisions.json` is schema 2: the root ``decisions`` array the runtime
    reads, a legacy entry exactly as before, and a structured entry carrying
    ``requirements`` with the ``editions`` its governing sources derive."""

    LEGACY_FIELDS = ["id", "title", "kind", "articles", "editions", "summary"]
    STRUCTURED_FIELDS = ["id", "title", "kind", "editions", "summary",
                         "requirements"]

    @classmethod
    def setUpClass(cls):
        cls.metas = [
            dict(GOOD_META, id="D-01"),
            structured(id="D-02"),
            dict(GOOD_META, id="D-03", editions=["unverified"],
                 articles={"unverified": ["8.4.4.14."]}),
            dict(GOOD_META, id="D-04", editions=["not_applicable"],
                 articles={"not_applicable": []}),
        ]
        cls.directory = Path(tempfile.mkdtemp())
        for meta in cls.metas:
            write(cls.directory, meta=meta,
                  body=GOOD_BODY.replace("D-01", meta["id"]))
        (cls.directory / G.PREAMBLE_FILE).write_text("# Log\n", encoding="utf-8")
        (cls.directory / G.META_FILE).write_text(
            json.dumps({"registry_comment": ["generated"]}) + "\n",
            encoding="utf-8")
        _, registry = G.generate(cls.directory)
        cls.payload = json.loads(registry)
        cls.by_id = {entry["id"]: entry for entry in cls.payload["decisions"]}

    def test_the_constants_match_the_layout_this_test_pins(self):
        self.assertEqual(tuple(self.LEGACY_FIELDS), G.FIELDS)
        self.assertEqual(tuple(self.STRUCTURED_FIELDS), G.STRUCTURED_FIELDS)

    def test_the_top_level_is_schema_2_with_the_root_decisions_array(self):
        self.assertEqual(["_comment", "schema", "decisions"], list(self.payload))
        self.assertEqual(["generated"], self.payload["_comment"])
        self.assertIs(type(self.payload["schema"]), int)
        self.assertEqual(2, self.payload["schema"])
        self.assertEqual(Loader.SCHEMA, G.REGISTRY_SCHEMA)
        self.assertIs(self.payload["decisions"], Loader._validated(self.payload),
                      "the runtime loader must accept what the generator writes")
        self.assertEqual(["D-01", "D-02", "D-03", "D-04"],
                         [entry["id"] for entry in self.payload["decisions"]])

    def test_a_legacy_entry_is_its_front_matter_unchanged(self):
        for meta in self.metas:
            if meta["id"] == "D-02":
                continue
            with self.subTest(decision=meta["id"]):
                entry = self.by_id[meta["id"]]
                self.assertEqual(self.LEGACY_FIELDS, list(entry))
                self.assertEqual({field: meta[field] for field in self.LEGACY_FIELDS},
                                 entry)

    def test_a_structured_entry_projects_requirements(self):
        entry = self.by_id["D-02"]
        block = STRUCTURED_META["articles"][KEY]
        self.assertEqual(self.STRUCTURED_FIELDS, list(entry))
        self.assertNotIn("articles", entry)
        for field in ("title", "kind", "summary"):
            self.assertEqual(STRUCTURED_META[field], entry[field])
        self.assertEqual(["necb2020", "necb2025"], entry["editions"])
        self.assertEqual([{"id": KEY, "label": block["label"],
                           "decided": block["decided"],
                           "sources": block["sources"]}], entry["requirements"])
        self.assertEqual(["id", "label", "decided", "sources"],
                         list(entry["requirements"][0]))
        for source in entry["requirements"][0]["sources"]:
            self.assertEqual(["code", "edition", "role", "references"],
                             list(source))

    def test_every_generated_source_equals_its_canonical_TOML(self):
        """Read with tomllib directly, not through the generator's parser."""
        text = (self.directory / "D-02.md").read_text(encoding="utf-8")
        front = text[:text.index("\n" + G.FENCE + "\n", 1) + len(G.FENCE) + 1]
        authored = tomllib.loads(inner(front))
        projected = {requirement["id"]: requirement["sources"]
                     for requirement in self.by_id["D-02"]["requirements"]}
        self.assertEqual({key: block["sources"]
                          for key, block in authored["articles"].items()},
                         projected)

    def test_requirements_are_projected_in_key_order(self):
        def unsorted(meta):
            block = requirement(meta)
            meta["articles"] = {"zeta_req": copy.deepcopy(block), KEY: block,
                                "alpha_req": copy.deepcopy(block)}

        entry = G.registry_entry(structured(unsorted))
        self.assertEqual(["alpha_req", KEY, "zeta_req"],
                         [item["id"] for item in entry["requirements"]])

    def test_the_projection_does_not_alias_the_source(self):
        meta = structured()
        entry = G.registry_entry(meta)
        entry["requirements"][0]["sources"][0]["references"].append("x")
        self.assertEqual(STRUCTURED_META, meta)


class TestSharedRequirementKeys(unittest.TestCase):
    """One requirement key names one requirement wherever it appears, so its
    form, label and governing citations must agree across decisions. Each
    decision's own ``decided`` and cross-references may differ."""

    @staticmethod
    def entries(*metas):
        return {meta["id"]: (meta, GOOD_BODY) for meta in metas}

    def refuses(self, message, *metas):
        with self.assertRaises(ValueError) as caught:
            G.check_shared_requirements(self.entries(*metas))
        self.assertIn(message, str(caught.exception))

    def test_a_shared_key_that_agrees_is_accepted(self):
        def own_result(meta):
            requirement(meta)["decided"] = "D-02 decides its own result."
            requirement(meta)["sources"] = requirement(meta)["sources"][:2]
            record(meta, 0)["references"].reverse()

        G.check_shared_requirements(
            self.entries(structured(), structured(own_result, id="D-02")))

    def test_a_shared_key_with_another_LABEL_is_refused(self):
        self.refuses("is labelled", structured(), structured(
            lambda m: requirement(m).update(label="Another label"), id="D-02"))

    def test_a_shared_key_citing_other_GOVERNING_provisions_is_refused(self):
        edits = {
            "a dropped reference": lambda m: record(m, 0)["references"].pop(),
            "a dropped edition": lambda m: requirement(m)["sources"].pop(1),
            "a demoted edition": lambda m: record(m, 1).update(role="related"),
        }
        for name, edit in edits.items():
            with self.subTest(name):
                self.refuses("cites different governing provisions",
                             structured(), structured(edit, id="D-02"))

    def test_a_shared_key_is_converted_in_every_decision_together(self):
        legacy = dict(GOOD_META, editions=["necb2020", "necb2025"], articles={
            KEY: {"label": requirement(STRUCTURED_META)["label"],
                  "necb2020": ["8.4.4.13.(1)"], "necb2025": ["8.4.5.13.(1)"]}})
        self.refuses("convert every user of a shared key together",
                     legacy, structured(id="D-02"))

    def test_legacy_shared_keys_are_held_to_the_same_rule(self):
        self.refuses("is labelled", GOOD_META, dict(GOOD_META, id="D-02", articles={
            "hydronic_pumps": {"label": "Pumps", "necb2020": ["8.4.4.14."]}}))
        self.refuses("cites different governing provisions", GOOD_META,
                     dict(GOOD_META, id="D-02", articles={"hydronic_pumps": {
                         "label": "Hydronic pump power",
                         "necb2020": ["8.4.4.14.(1)"]}}))
        G.check_shared_requirements(self.entries(
            GOOD_META, dict(GOOD_META, id="D-02", articles={"hydronic_pumps": {
                "label": "Hydronic pump power",
                "necb2020": ["Article 8.4.4.14."]}})))

    def test_the_holding_keys_are_not_requirements(self):
        G.check_shared_requirements(self.entries(
            dict(GOOD_META, editions=["unverified"],
                 articles={"unverified": ["8.4.4.14."]}),
            dict(GOOD_META, id="D-02", editions=["unverified"],
                 articles={"unverified": ["8.4.4.9.(5)"]})))

    def test_reading_the_sources_applies_the_rule(self):
        directory = Path(tempfile.mkdtemp())
        write(directory, meta=structured())
        write(directory, meta=structured(
            lambda m: requirement(m).update(label="Another label"), id="D-02"),
            body=GOOD_BODY.replace("D-01", "D-02"))
        (directory / G.PREAMBLE_FILE).write_text("# Log\n", encoding="utf-8")
        (directory / G.META_FILE).write_text('{"registry_comment": []}\n',
                                             encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            G.generate(directory)
        self.assertIn("is labelled", str(caught.exception))


class TestUnvalidatedSourcesAreNamed(unittest.TestCase):
    """A source no provision index validates is accepted, so it is SAID: both
    the writing run and ``--check`` print one note per such record."""

    NOTE = ("decisions: note — D-01 articles['heat_pump_reference_by_source'] "
            "cites ashrae-62.1 2016 (incorporated-reference), which no "
            "registered provision index validates; it is carried as authored "
            "and establishes no edition")

    def run_both(self, meta):
        root = Path(tempfile.mkdtemp())
        sources, outputs = root / "sources", root / "outputs"
        sources.mkdir()
        outputs.mkdir()
        write(sources, meta=meta)
        (sources / G.PREAMBLE_FILE).write_text("# Log\n", encoding="utf-8")
        (sources / G.META_FILE).write_text('{"registry_comment": []}\n',
                                           encoding="utf-8")
        argv = ["--source-dir", str(sources), "--doc", str(outputs / "doc.md"),
                "--registry", str(outputs / "registry.json")]
        for args in (argv, ["--check", *argv]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(0, G.main(args))
            yield args[0] == "--check", [line for line in out.getvalue().splitlines()
                                         if "D-01 articles" in line]

    def test_both_branches_name_the_external_record(self):
        for checking, notes in self.run_both(structured()):
            with self.subTest(check=checking):
                self.assertEqual([self.NOTE], notes)

    def test_a_validated_record_is_not_named(self):
        meta = structured(lambda m: requirement(m)["sources"].pop())
        for checking, notes in self.run_both(meta):
            with self.subTest(check=checking):
                self.assertEqual([], notes)


class TestTheProvisionIndexIsThisCheckouts(unittest.TestCase):
    """Structured sources are validated against THIS checkout's provision
    index. A `btap` imported from another tree would answer from that tree's
    data, so the generator refuses to load at all."""

    SCRIPT = PYTHON_ROOT / "scripts" / "generate_decisions.py"

    def load(self, name):
        spec = importlib.util.spec_from_file_location(name, self.SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_btap_is_imported_from_this_checkout(self):
        for module in (G.btap_codes, G.provisions, Loader):
            with self.subTest(module=module.__name__):
                self.assertTrue(Path(module.__file__).resolve().is_relative_to(
                    G.PYTHON_DIR / "btap"))
        self.load("generate_decisions_same_tree")       # the control

    def test_a_btap_from_another_tree_is_refused(self):
        elsewhere = PYTHON_ROOT.parent.parent / "another-checkout" / "python"
        btap = types.ModuleType("btap")
        btap.__file__ = str(elsewhere / "btap" / "__init__.py")
        btap.__path__ = [str(elsewhere / "btap")]
        codes = types.ModuleType("btap.codes")
        codes.__file__ = str(elsewhere / "btap" / "codes" / "__init__.py")
        codes.__path__ = [str(elsewhere / "btap" / "codes")]
        provisions = types.ModuleType("btap.codes.provisions")
        decisions = types.ModuleType("btap.codes.decisions")
        decisions.SCHEMA = Loader.SCHEMA
        btap.codes, codes.provisions, codes.decisions = codes, provisions, decisions
        with mock.patch.dict(sys.modules, {
                "btap": btap, "btap.codes": codes,
                "btap.codes.provisions": provisions,
                "btap.codes.decisions": decisions}):
            with self.assertRaises(ImportError) as caught:
                self.load("generate_decisions_other_tree")
        self.assertIn("must validate against", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
