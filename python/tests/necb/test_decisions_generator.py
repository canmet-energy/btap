"""The decision generator's own behaviour: parser, TOML writer, validation.

``test_decisions_registry_sync.py`` gates the repository's committed state.
This module attacks the machinery instead, on synthetic sources, so that each
rule is shown to REJECT something rather than merely to pass over real files
that happen to comply.
"""

from __future__ import annotations

import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PYTHON_ROOT / "scripts"))
import generate_decisions as G  # noqa: E402

EM = G.EM_DASH

GOOD_META = {
    "id": "D-01",
    "title": "A compact registry title",
    "kind": "process",
    "articles": ["8.4.4.14."],
    "summary": "A paraphrase of what was decided.",
}
GOOD_BODY = "## D-01 {} An authored heading, not the title\n\nBody text.\n".format(EM)


def write(directory, meta=None, body=None, name=None):
    meta = dict(GOOD_META if meta is None else meta)
    body = GOOD_BODY if body is None else body
    path = Path(directory) / (name or (meta["id"] + ".md"))
    path.write_text(G.source_text(meta, body), encoding="utf-8")
    return path


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

    def test_front_matter_emits_the_five_fields_in_registry_order(self):
        lines = G.front_matter(GOOD_META).split("\n")
        self.assertEqual(G.FENCE, lines[0])
        self.assertEqual(G.FENCE, lines[-1])
        self.assertEqual(list(G.FIELDS), [line.split(" = ")[0] for line in lines[1:-1]])


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
                G.source_text(GOOD_META, GOOD_BODY).replace(
                    G.FENCE + "\n\n##", 'extra = "x"\n' + G.FENCE + "\n\n##"),
                encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                G.parse_source(path)
            self.assertIn("unexpected", str(caught.exception))

    def test_a_malformed_id_is_refused(self):
        self.rejects("malformed id", meta=dict(GOOD_META, id="D-1"), name="D-1.md")
        self.rejects("malformed id", meta=dict(GOOD_META, id="D-100"), name="D-100.md")

    def test_a_filename_that_disagrees_with_the_id_is_refused(self):
        self.rejects("filename does not match", name="D-02.md")

    def test_an_unknown_kind_is_refused(self):
        self.rejects("unknown kind", meta=dict(GOOD_META, kind="runtimeish"))

    def test_empty_or_non_string_text_fields_are_refused(self):
        self.rejects("title must be", meta=dict(GOOD_META, title="  "))
        self.rejects("summary must be", meta=dict(GOOD_META, summary=""))

    def test_articles_must_be_a_list_of_strings(self):
        self.rejects("articles must be", meta=dict(GOOD_META, articles="8.4.4.14."))

    def test_a_body_without_its_own_titled_heading_is_refused(self):
        self.rejects("must open with", body="Body text.\n")
        self.rejects("must open with", body="## D-01\n\nBody text.\n")
        self.rejects("must open with", body="# D-01 {} Wrong level\n".format(EM))

    def test_a_heading_naming_another_decision_is_refused(self):
        self.rejects("heading declares",
                     body="## D-02 {} Another decision\n\nBody.\n".format(EM))

    def test_a_body_may_not_declare_its_own_short_id_in_ANY_spelling(self):
        """Every construct that owns ``d-NN``, not just the generated one.

        Two review rounds of this rule each shipped a scanner narrower than
        what GitHub renders, and each time the uniqueness test shared the same
        narrow scanner and stayed green (Sol, PR #64). The first round missed
        the ``name`` attribute, non-anchor elements and Setext; the second
        still modelled headings at column zero only, so three-space indented
        ATX, indented Setext and list-nested Setext all rendered as headings
        and passed. Sharing an incomplete scanner makes the validator and the
        assertion agree; it does not make the scanner right.
        """
        claims = {
            '<a name="d-01"></a>': "the name attribute, which also owns the target",
            '<span id="d-01"></span>': "a non-anchor element",
            "<h3 id='d-01'>Other</h3>": "single quotes on a heading element",
            '<a id="d-01"></a>': "the generated spelling, authored by hand",
            "<A ID = \"D-01\" ></A>": "uppercase, spaced",
            "<a id=d-01></a>": "unquoted",
            'text <a id="d-01"></a> inline': "inline rather than standalone",
            "### D-01": "a bare ATX heading",
            "### D-01 ###": "a closed ATX heading",
            "   ### D-01": "ATX indented three spaces, which still renders",
            "D-01\n----": "a bare Setext heading",
            "   D-01\n   ----": "Setext indented three spaces",
            "- D-01\n  ----": "Setext inside a list item",
            "> D-01": "a short id alone inside a blockquote",
            "1. D-01": "a short id alone inside an ordered list",
            # A child list sits FOUR spaces under its parent, past the
            # three-space cap a top-level block is measured by. The complete
            # parent/child source, because an isolated marker did not
            # reproduce it (Sol, PR #64).
            "- parent\n    - D-01\n      ----": "Setext in a nested child list",
            "- parent\n    - D-01": "a short id alone in a nested child list",
            # Inline markup leaves the heading's VISIBLE text as the id, so
            # each of these renders a heading slugged d-01 exactly as a plain
            # one does, while a rule reading raw syntax sees something else.
            "### **D-01**": "bold inside an ATX heading",
            "**D-01**\n---": "bold inside a Setext heading",
            "### [D-01](https://example.com)": "a link whose text is the id",
            "### `D-01`": "code span inside a heading",
            "### <em>D-01</em>": "an inline HTML element inside a heading",
            # These three defeated the regex reducer by leaving syntax BEHIND,
            # making the candidate longer than the render rather than shorter
            # -- which is why "approximation can only refuse" was false
            # (Sol, PR #64).
            "### D&#45;01": "a character reference spelling the hyphen",
            "### [D-01](https://example.com/a_(b))":
                "balanced parentheses inside a link destination",
            '### <span title="1 > 0">D-01</span>':
                "a greater-than inside a quoted attribute",
            # Unresolvable syntax fails closed rather than being read as prose.
            "### [D-01](unterminated": "an unterminated link destination",
            "### [D-01": "an unterminated link label",
        }
        for claim, why in claims.items():
            with self.subTest(claim=why):
                self.rejects("element-id surface", body=GOOD_BODY + "\n" + claim + "\n")

    def test_an_owner_on_the_headings_own_line_is_not_exempt(self):
        """No line is exempt, including line 1.

        Excluding line 1 wholesale -- on the premise that the required titled
        heading cannot own the short id -- accepted an HTML owner appended to
        that very heading (Sol, PR #64). The titled heading carries text after
        the id, so it matches neither heading arm and needs no exemption.
        """
        self.rejects("element-id surface",
                     body='## D-01 {} Main <a name="d-01"></a>\n'.format(EM))

    def test_the_rule_does_not_fire_on_look_alikes(self):
        """The conservative ban must not become a ban on ordinary prose.

        A TOML ``id = "D-01"`` assignment is the case that forced the tag
        context: without it the front matter of every source is a false claim.
        ``data-id`` and a longer unquoted id are Sol's false-rejection cases.
        """
        for benign in ('a paragraph mentioning D-01 and id = "D-01" in prose',
                       "## D-01 " + EM + " a titled heading later in the body",
                       '<a href="#d-01">a link, not a declaration</a>',
                       '<a data-id="d-01">a different attribute</a>',
                       "<a id=d-01-note>a longer unquoted id</a>",
                       '<a id="d-01-note">a longer quoted id</a>',
                       "- D-01 is discussed in this list item",
                       "D-01 opens a sentence that continues.",
                       "**D-01** is cited inline in a sentence.",
                       "see [D-01](#d-01) for the detail",
                       "| D-01 | a table cell |"):
            with self.subTest(benign=benign[:44]):
                _meta, body = self.parse(body=GOOD_BODY + "\n" + benign + "\n")
                self.assertIn(benign, body)

    def test_the_owner_scan_finds_each_spelling(self):
        """The shared scanner itself, so both callers rest on tested behaviour."""
        found = G.short_id_owners(
            '<a id="d-01"></a>\n<a name="d-02"></a>\n<span id="d-03"></span>\n'
            "### D-04\n   D-05\n")
        self.assertEqual(
            [(1, "html id attribute", "d-01"),
             (2, "html name attribute", "d-02"),
             (3, "html id attribute", "d-03"),
             (4, "bare ATX heading", "d-04"),
             (5, "standalone short id", "d-05")], found)

    def test_block_prefixes_are_normalised_before_the_line_is_judged(self):
        for line, expected in (("   D-01", "D-01"), ("- D-01", "D-01"),
                               ("> D-01", "D-01"), ("  1. D-01", "D-01"),
                               ("- > D-01", "D-01"), ("D-01 and more", "D-01 and more"),
                               ("    D-01", "D-01"),
                               # past the three-space cap: a nested child list
                               ("    - D-01", "D-01"),
                               ("      - D-01", "D-01"),
                               ("  - - D-01", "D-01")):
            with self.subTest(line=line):
                self.assertEqual(expected, G.unprefixed(line))

    def test_visible_text_resolves_the_supported_grammar_exactly(self):
        """The three constructs the restricted grammar resolves, and only those."""
        for raw, expected in (("**D-01**", "D-01"), ("`D-01`", "D-01"),
                              ("[D-01](https://example.com)", "D-01"),
                              ("[D-01][ref]", "D-01"), ("<em>D-01</em>", "D-01"),
                              ("_D-01_", "D-01"), ("~~D-01~~", "D-01"),
                              ("D&#45;01", "D-01"), ("D&#x2D;01", "D-01"),
                              ("[D-01](https://example.com/a_(b))", "D-01"),
                              ('<span title="1 > 0">D-01</span>', "D-01"),
                              ("D-01 and more words", "D-01 and more words"),
                              ("see [D-01](#d-01) here", "see D-01 here")):
            with self.subTest(raw=raw):
                text, proven = G.visible_text(raw)
                self.assertEqual(expected, text)
                self.assertTrue(proven, "this construct is in the supported grammar")

    def test_unresolvable_syntax_is_reported_as_unproven(self):
        """The fail-closed half: unresolved is NOT the same as resolved-to-prose.

        Treating the remainder as prose is exactly what admitted the three
        counterexamples above, because leftover syntax made the candidate
        longer than the rendered heading (Sol, PR #64).
        """
        for raw in ("[D-01](unterminated", "[D-01", "[D-01](a(b)"):
            with self.subTest(raw=raw):
                self.assertFalse(G.visible_text(raw)[1],
                                 "an unresolvable construct must not be called proven")

    def test_links_balance_their_destination_parentheses(self):
        text, proven = G.consume_links("[D-01](https://example.com/a_(b)) tail")
        self.assertEqual("D-01 tail", text)
        self.assertTrue(proven)
        self.assertFalse(G.consume_links("[D-01](a(b)")[1])

    def test_html_is_tokenised_not_pattern_matched(self):
        text, parsed = G.strip_html('<span title="1 > 0">D-01</span>')
        self.assertEqual("D-01", text)
        self.assertTrue(parsed)
        self.assertEqual("D-01", G.strip_html("D&#45;01")[0])

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


class TestSplitIsNotAWriter(unittest.TestCase):
    def test_split_refuses_a_directory_that_already_holds_sources(self):
        directory = Path(tempfile.mkdtemp())
        write(directory)

        class Args:
            source_dir = directory
            doc = Path("unused")
            registry = Path("unused")

        self.assertEqual(1, G.run_split(Args()))


if __name__ == "__main__":
    unittest.main()
