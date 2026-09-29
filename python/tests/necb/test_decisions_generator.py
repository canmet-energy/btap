"""The decision generator's own behaviour: parser, TOML writer, validation.

``test_decisions_registry_sync.py`` gates the repository's committed state.
This module attacks the machinery instead, on synthetic sources, so that each
rule is shown to REJECT something rather than merely to pass over real files
that happen to comply.
"""

from __future__ import annotations

import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()
