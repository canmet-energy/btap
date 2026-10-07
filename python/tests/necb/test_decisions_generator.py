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
    # `articles` is a MAP from code id to that edition's own citations: the
    # same number can name different requirements in different editions, so a
    # flat list cannot say which numbering it uses. The fixture uses a real
    # code id and a real article so the validated path is exercised rather
    # than skipped.
    "articles": {"necb2020": ["8.4.4.14."]},
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
        header = inner.index("[articles]")
        scalars = [ln.split(" = ")[0] for ln in inner[:header]]
        self.assertEqual([f for f in G.FIELDS if f != "articles"], scalars)
        for line in inner[header + 1:]:
            self.assertIn(line.split(" = ")[0], G.registered_codes()
                          | {G.ARTICLES_UNVERIFIED})


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
                # inserted BEFORE the [articles] table: a TOML table
                # header captures every key that follows it, so appending
                # before the closing fence would make this an articles key
                # rather than an unexpected top-level field
                G.source_text(GOOD_META, GOOD_BODY).replace(
                    "\n[articles]", '\nextra = "x"\n\n[articles]'),
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
        self.rejects("must be a list of strings",
                     meta=dict(GOOD_META, articles={"necb2020": "8.4.4.14."}))

    def test_articles_may_not_cite_an_edition_the_decision_does_not_claim(self):
        self.rejects("editions does not claim",
                     meta=dict(GOOD_META,
                               articles={"necb2025": ["8.4.5.14."]}))

    def test_a_Section_8_4_article_absent_from_that_edition_is_refused(self):
        """`8.4.4.9` is the Heating System article in NECB 2020 and does not
        exist in 2025 at all."""
        self.rejects("does not exist in that edition",
                     meta=dict(GOOD_META, editions=["necb2025"],
                               articles={"necb2025": ["8.4.4.9.(5)"]}))

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
                               articles={"necb2025": ["8.4.5.14."]}))
            G.parse_source(Path(d) / "D-01.md")     # must not raise

    def test_unverified_alone_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, meta=dict(GOOD_META, editions=["unverified"],
                               articles={"unverified": ["8.4.4.14."]}))
            G.parse_source(Path(d) / "D-01.md")

    def test_an_UNREGISTERED_code_id_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, meta=dict(GOOD_META, editions=["necb2030"],
                               articles={"necb2030": []}))
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


if __name__ == "__main__":
    unittest.main()
