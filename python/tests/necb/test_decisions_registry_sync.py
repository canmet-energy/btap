"""The decision sources are canonical; three outputs are generated from them.

One decision is one file, ``docs/decisions/D-NN.md``. This module gates the
repository's actual state: that every source parses, that the three generated
artifacts (the registry, the decision log and the Codes Committee provision
view) are in step with the sources, and that none of them has been
hand-edited. The generator's own behaviour -- its parser, its TOML writer, its
validation and its rendering of the provision view -- is exercised in
``test_decisions_generator.py``.

The registry is schema 2. Every entry keeps the ``id``, ``title``, ``kind``
and ``summary`` the runtime reads; a legacy entry is its front matter, and a
structured one projects ``requirements`` with an ``editions`` derived from
its governing sources. The expected projections here are computed from the
sources directly, not by the generator, and a structured decision is run end
to end beside the committed tree.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

PYTHON_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = PYTHON_ROOT.parent

sys.path.insert(0, str(PYTHON_ROOT / "scripts"))
import generate_decisions as G  # noqa: E402

# G put this checkout's python/ first on sys.path.
import btap.codes as codes  # noqa: E402
from btap.codes import decisions as Loader  # noqa: E402

PYTHON_REGISTRY = PYTHON_ROOT / "btap" / "codes" / "data" / "decisions.json"
DECISIONS_DOC = REPO_ROOT / "docs" / "necb_decisions.md"
PROVISION_VIEW = REPO_ROOT / "docs" / "CODE_DECISIONS_BY_PROVISION.md"
SOURCE_DIR = REPO_ROOT / "docs" / "decisions"
SCRIPT = PYTHON_ROOT / "scripts" / "generate_decisions.py"

#: Unbounded digits, matching the generator: D-01..D-99 were all taken.
ID_PATTERN = re.compile(r"^D-\d+$")
HEADING_PATTERN = re.compile(r"^## (D-\d+)\b", re.MULTILINE)

#: The schema-2 entry layouts, written out here rather than read from the
#: generator, so a changed field list in the generator fails this module.
LEGACY_FIELDS = ("id", "title", "kind", "articles", "editions", "summary")
STRUCTURED_FIELDS = ("id", "title", "kind", "editions", "summary", "requirements")
#: What `btap.codes.decisions` and the report's rulings appendix read.
RUNTIME_FIELDS = ("id", "title", "kind", "summary")


def runtime_editions():
    """``(family, edition) -> code id``, from the runtime registry."""
    return {(codes.resolve(code_id).family, codes.resolve(code_id).edition): code_id
            for code_id in codes.code_ids()}


def expected_entry(meta):
    """The registry entry one front matter must project to.

    The form is read off the source: a structured requirement carries
    ``sources``. Only governing records contribute to ``editions``.
    """
    articles = meta["articles"]
    if not any(isinstance(block, dict) and "sources" in block
               for block in articles.values()):
        return {field: meta[field] for field in LEGACY_FIELDS}
    runtime = runtime_editions()
    editions = sorted({runtime[(source["code"], source["edition"])]
                       for block in articles.values()
                       for source in block["sources"]
                       if source["role"] == "governing"})
    requirements = [
        {"id": key, "label": block["label"], "decided": block["decided"],
         "sources": [{field: source[field]
                      for field in ("code", "edition", "role", "references")}
                     for source in block["sources"]]}
        for key, block in sorted(articles.items())]
    return {"id": meta["id"], "title": meta["title"], "kind": meta["kind"],
            "editions": editions, "summary": meta["summary"],
            "requirements": requirements}


def ordered(value):
    """JSON text, so a comparison also holds every level's key ORDER."""
    return json.dumps(value, indent=1, ensure_ascii=False)


#: A table cell separator: a pipe the generator did not escape.
CELL_SPLIT = re.compile(r"(?<!\\)\|")
#: A link to a decision's section in the decision log. The file name and the
#: fragment are joined here, at runtime, so this module does not itself read as
#: an inbound link for the tree-wide short-link scan.
DECISION_LINK = re.compile(r"\]\(" + re.escape(DECISIONS_DOC.name) + r"#(d-\d+)\)")
SUMMARY_ANCHOR = re.compile(r'^<a id="transitional-summary-(d-\d+)"></a>$',
                            re.MULTILINE)
EDITION_HEADING = re.compile(r"^(.+) \(code id `([^`]+)`\)$")
#: The `##` sections that are not a code. Every other one is a code family.
VIEW_SECTIONS = ("Scope", "Definitions", "Transitional decision summaries",
                 "Edition not yet attributed")
NOT_ATTRIBUTED = "Edition not yet attributed"


def raw_front_matter():
    """``{id: front matter}`` read straight from the files, in numeric id
    order and with no generator code, so what the view must contain is worked
    out independently of it."""
    paths = sorted(SOURCE_DIR.glob("D-*.md"),
                   key=lambda path: int(path.stem.split("-")[1]))
    return {path.stem: tomllib.loads(
                path.read_text(encoding="utf-8").split("+++\n")[1])
            for path in paths}


def recorded_citations(articles):
    """Every citation a decision records, in any of its three forms."""
    found = []
    for block in articles.values():
        if isinstance(block, list):                       # unverified / not_applicable
            found += block
        elif "sources" in block:                          # structured
            found += [reference for record in block["sources"]
                      for reference in record["references"]]
        else:                                             # legacy, per code id
            found += [citation for code_id, citations in block.items()
                      if code_id != "label" for citation in citations]
    return found


def classify(front):
    """``(structured, established, held, omitted)`` decision ids, decided from
    what each decision RECORDS and not from the generator's classification."""
    structured, established, held, omitted = [], [], [], []
    for decision_id, meta in front.items():
        articles = meta["articles"]
        if not recorded_citations(articles):
            omitted.append(decision_id)
        elif any(isinstance(block, dict) and "sources" in block
                 for block in articles.values()):
            structured.append(decision_id)
        elif set(articles) == {"unverified"}:
            held.append(decision_id)
        else:
            established.append(decision_id)
    return structured, established, held, omitted


def view_rows(view):
    """``(section, heading, cells)`` for every table body row of a provision
    view, where ``section`` is the `##` heading and ``heading`` the `###`."""
    section = heading = ""
    rows = []
    for line in view.splitlines():
        if line.startswith("### "):
            heading = line[4:]
        elif line.startswith("## "):
            section, heading = line[3:], ""
        elif line.startswith("|---"):
            rows.pop()          # the header row this rule underlines
        elif line.startswith("|"):
            rows.append((section, heading,
                         [cell.strip() for cell in CELL_SPLIT.split(line)[1:-1]]))
    return rows


def code_spans(cell):
    return [span.replace("\\|", "|") for span in re.findall(r"`([^`]+)`", cell)]


def unescape(text):
    """The text a Markdown reader sees once backslash escapes are applied."""
    return re.sub(r"\\(.)", r"\1", text)


def leading_number(span):
    """A citation's provision number as integers, Division A first."""
    number = re.search(r"\d+(?:\.\d+)*", span).group()
    return (0 if span.startswith("Division A") else 1,
            tuple(int(part) for part in number.split(".")))


class TestDecisionSources(unittest.TestCase):
    """Every source file parses and carries a well-formed entry."""

    @classmethod
    def setUpClass(cls):
        cls.preamble, cls.entries, cls.meta = G.read_sources(SOURCE_DIR)

    def test_every_source_parses_and_has_a_unique_well_formed_id(self):
        # parse_source validates as it reads, so reaching here is the schema
        # check; what remains is that the ids are unique and well formed.
        self.assertGreater(len(self.entries), 0)
        for decision_id in self.entries:
            self.assertRegex(decision_id, ID_PATTERN,
                             f"malformed decision id: {decision_id!r}")
        # Through the PRODUCTION helper. The first version of this assertion
        # recomputed the stray set from a byte-for-byte copy of the generator's
        # expression, so deleting the generator's guard left the whole suite
        # green -- the fourth instance in this repository of a test agreeing
        # with its own reimplementation rather than with the code (Fable, PR
        # #64). One implementation, two callers. The rejection case lives in
        # test_decisions_generator.py.
        stray = G.stray_files(SOURCE_DIR)
        self.assertEqual(
            [], stray,
            "entr(ies) in the canonical directory that reach none of the "
            f"generated outputs: {stray}")

    def test_a_source_file_rewrites_to_itself(self):
        """The writer is the inverse of the parser, for every real source.

        A source that does not survive a parse/write round trip means editing
        any one decision through the tooling would silently reformat it.
        """
        for path in sorted(SOURCE_DIR.glob("D-*.md")):
            with self.subTest(source=path.name):
                meta, body = G.parse_source(path)
                self.assertEqual(path.read_text(encoding="utf-8"),
                                 G.source_text(meta, body))

    def test_runtime_entries_declare_articles_or_say_why_not(self):
        """A ``kind`` is one of the four the registry defines."""
        for decision_id, (meta, _body) in self.entries.items():
            with self.subTest(decision=decision_id):
                self.assertIn(meta["kind"], G.KINDS)


class TestGeneratedOutputsAreInStep(unittest.TestCase):
    """No generated artifact may drift from, or be edited beside, its sources."""

    @classmethod
    def setUpClass(cls):
        cls.doc, cls.registry, cls.provision_view = G.generate(SOURCE_DIR)
        cls.entries = G.read_sources(SOURCE_DIR)[1]

    def test_check_passes_on_the_committed_tree(self):
        """The drift gate itself -- the same command CI runs."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_committed_document_is_exactly_what_the_sources_render(self):
        self.assertEqual(DECISIONS_DOC.read_text(encoding="utf-8"), self.doc,
                         "docs/necb_decisions.md is generated; edit "
                         "docs/decisions/D-NN.md and regenerate")

    def test_committed_registry_is_exactly_what_the_sources_render(self):
        self.assertEqual(PYTHON_REGISTRY.read_text(encoding="utf-8"), self.registry,
                         "decisions.json is generated; edit "
                         "docs/decisions/D-NN.md and regenerate")

    def test_committed_provision_view_is_exactly_what_the_sources_render(self):
        self.assertEqual(PROVISION_VIEW.read_text(encoding="utf-8"),
                         self.provision_view,
                         "docs/CODE_DECISIONS_BY_PROVISION.md is generated; "
                         "edit docs/decisions/D-NN.md and regenerate")

    def test_the_generator_writes_the_view_where_the_documents_live(self):
        """The default output path IS the committed file, so a plain
        `generate_decisions.py` and `--check` read and write it."""
        self.assertEqual(PROVISION_VIEW, G.PROVISION_VIEW)
        self.assertEqual(DECISIONS_DOC.parent, G.PROVISION_VIEW.parent)

    def test_the_log_and_the_registry_carry_exactly_the_source_id_set(self):
        headings = HEADING_PATTERN.findall(self.doc)
        self.assertEqual(len(headings), len(set(headings)),
                         "duplicate ## D-XX headings in the generated document")
        self.assertEqual(set(headings), set(self.entries))
        registry_ids = [entry["id"] for entry in json.loads(self.registry)["decisions"]]
        self.assertEqual(len(registry_ids), len(set(registry_ids)),
                         "duplicate ids in the generated registry")
        self.assertEqual(set(registry_ids), set(self.entries))

    def test_the_log_and_the_registry_are_in_numeric_id_order(self):
        """Numeric id order is the ordering invariant of these two, and the
        only one. The provision view is ordered by code, edition and provision
        instead.

        The pre-migration files carried three different sequences -- document,
        registry and numeric -- and claimed a chronology that did not hold
        (D-58..D-60, dated 2026-08-02, preceded D-53..D-57, dated 2026-07-29).
        """
        expected = G.numeric_order(self.entries)
        self.assertEqual(HEADING_PATTERN.findall(self.doc), expected)
        self.assertEqual(
            [entry["id"] for entry in json.loads(self.registry)["decisions"]], expected)

    def test_the_index_does_not_claim_a_chronology(self):
        self.assertIn(G.INDEX_HEADING, self.doc)
        self.assertNotIn("chronological", self.doc.split(G.END_MARK)[0])

    def test_every_decision_has_exactly_one_generated_anchor(self):
        """The structural gate: generation emits one anchor per decision.

        This checks the LITERAL form the generator writes, which is exact and
        needs no model of Markdown. It does NOT establish that an authored
        body cannot introduce a second owner of the same short id in some
        other spelling -- that rule was cut from this PR after five review
        rounds kept finding further spellings, and the residual risk is an
        ambiguous `#d-NN` fragment rather than a dead link. The dead-link
        class is closed structurally, because every anchor is emitted outside
        every authored body.
        """
        anchors = re.findall(r'^<a id="(d-\d+)"></a>$', self.doc, re.MULTILINE)
        self.assertEqual(len(anchors), len(set(anchors)), "duplicate generated anchor")
        self.assertEqual({i.lower() for i in self.entries}, set(anchors),
                         "every decision must carry its generated anchor")
        for decision_id in self.entries:
            with self.subTest(decision=decision_id):
                self.assertIn(
                    '<a id="{}"></a>\n\n## {} '.format(decision_id.lower(), decision_id),
                    self.doc, "the anchor must sit immediately above its heading")

    def test_the_registry_is_the_front_matter_projection(self):
        """Each entry is its source's schema-2 projection, field order
        included: the front matter for a legacy decision, ``requirements``
        and the derived ``editions`` for a structured one."""
        for entry in json.loads(self.registry)["decisions"]:
            with self.subTest(decision=entry["id"]):
                self.assertEqual(
                    ordered(expected_entry(self.entries[entry["id"]][0])),
                    ordered(entry))
                self.assertIn(tuple(entry), (LEGACY_FIELDS, STRUCTURED_FIELDS))

    def test_the_registry_is_schema_2_around_its_root_array(self):
        payload = json.loads(self.registry)
        self.assertEqual(["_comment", "schema", "decisions"], list(payload))
        self.assertIs(int, type(payload["schema"]))
        self.assertEqual(2, payload["schema"])
        self.assertEqual(Loader.SCHEMA, payload["schema"])
        meta = json.loads((SOURCE_DIR / G.META_FILE).read_text(encoding="utf-8"))
        self.assertEqual(meta["registry_comment"], payload["_comment"])

    def test_every_entry_keeps_the_fields_the_runtime_reads(self):
        """``id``, ``title``, ``kind`` and ``summary`` are what resolves a
        ruling and fills the report's rulings appendix, in either form."""
        for entry in json.loads(self.registry)["decisions"]:
            meta = self.entries[entry["id"]][0]
            with self.subTest(decision=entry["id"]):
                self.assertEqual({field: meta[field] for field in RUNTIME_FIELDS},
                                 {field: entry[field] for field in RUNTIME_FIELDS})

    def test_the_runtime_loader_serves_the_generated_array(self):
        self.assertTrue(Path(Loader.__file__).resolve().is_relative_to(
            PYTHON_ROOT / "btap"), Loader.__file__)
        with mock.patch.object(Loader, "_all", None), \
                mock.patch.object(Loader, "_by_id", None):
            self.assertEqual(json.loads(self.registry)["decisions"],
                             Loader.all_decisions())


#: A structured decision as an author writes it, in the writer's own layout.
#: Its NECB references are ones each edition's committed provision index
#: records as present; the related NECB record and the incorporated external
#: standard sit beside the two governing records and establish nothing.
STRUCTURED_SOURCE = """\
+++
id = "{id}"
title = "Fixture: a structured decision beside the committed tree"
kind = "runtime"
summary = "A fixture decision that exists only inside this test."

[articles.heat_pump_reference_by_source]
label = "Reference system for a proposed heat pump, by heat source"
decided = "Water-loop and other heat pumps follow different reference-system selection branches."

[[articles.heat_pump_reference_by_source.sources]]
code = "necb"
edition = "2020"
role = "governing"
references = [
  "8.4.4.13.(1)",
  "8.4.4.13.(2)",
  "Note A-8.4.4.13",
]

[[articles.heat_pump_reference_by_source.sources]]
code = "necb"
edition = "2025"
role = "governing"
references = [
  "8.4.5.13.(1)",
  "8.4.5.13.(2)",
  "Note A-8.4.5.13",
]

[[articles.heat_pump_reference_by_source.sources]]
code = "necb"
edition = "2020"
role = "related"
references = [
  "Table 8.4.4.7.-B",
]

[[articles.heat_pump_reference_by_source.sources]]
code = "ashrae-62.1"
edition = "2016"
role = "incorporated-reference"
references = [
  "6.2.2.1",
]
+++

## {id} — A structured fixture decision

Body text.
"""


class TestAStructuredDecisionBesideTheCommittedTree(unittest.TestCase):
    """End to end, on a COPY of the committed sources plus one structured
    decision at the next free id: the generator accepts it beside every
    legacy decision, no committed entry or section moves, and the runtime
    loader resolves it from the file the generator wrote."""

    KEY = "heat_pump_reference_by_source"

    @classmethod
    def setUpClass(cls):
        scratch = tempfile.TemporaryDirectory()
        cls.addClassCleanup(scratch.cleanup)
        root = Path(scratch.name)
        cls.source_dir = root / "decisions"
        shutil.copytree(SOURCE_DIR, cls.source_dir)
        taken = [int(path.stem[len("D-"):]) for path in SOURCE_DIR.glob("D-*.md")]
        cls.new_id = "D-{}".format(max(taken) + 1)
        cls.text = STRUCTURED_SOURCE.format(id=cls.new_id)
        cls.path = cls.source_dir / (cls.new_id + ".md")
        cls.path.write_text(cls.text, encoding="utf-8")
        cls.front = tomllib.loads(cls.text.split(G.FENCE + "\n")[1])
        cls.body = cls.text.split("\n" + G.FENCE + "\n\n", 1)[1]

        cls.doc_path = root / "necb_decisions.md"
        cls.registry_path = root / "data" / "decisions.json"
        cls.view_path = root / "CODE_DECISIONS_BY_PROVISION.md"
        cls.registry_path.parent.mkdir()
        arguments = ["--source-dir", str(cls.source_dir), "--doc", str(cls.doc_path),
                     "--registry", str(cls.registry_path),
                     "--provision-view", str(cls.view_path)]
        cls.outcomes = {}
        for mode, argv in (("write", arguments), ("check", ["--check", *arguments])):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                cls.outcomes[mode] = (G.main(argv), out.getvalue())
        cls.doc = cls.doc_path.read_text(encoding="utf-8")
        cls.view = cls.view_path.read_text(encoding="utf-8")
        cls.payload = json.loads(cls.registry_path.read_text(encoding="utf-8"))
        cls.committed = json.loads(PYTHON_REGISTRY.read_text(encoding="utf-8"))

    def test_the_fixture_key_is_not_a_committed_requirement(self):
        """Otherwise the shared-key rule, not the structured form, would be
        what this class exercises."""
        _, entries, _ = G.read_sources(SOURCE_DIR)
        self.assertFalse(any(self.KEY in meta["articles"]
                             for meta, _ in entries.values()))

    def test_both_branches_accept_it(self):
        for mode, (code, output) in self.outcomes.items():
            with self.subTest(mode=mode):
                self.assertEqual(0, code, output)

    def test_the_authored_file_is_already_in_the_writers_layout(self):
        meta, body = G.parse_source(self.path)
        self.assertEqual(self.text, G.source_text(meta, body))

    def test_its_entry_is_the_structured_projection(self):
        entry = self.payload["decisions"][-1]
        self.assertEqual(self.new_id, entry["id"])
        self.assertEqual(ordered(expected_entry(self.front)), ordered(entry))
        self.assertEqual(STRUCTURED_FIELDS, tuple(entry))
        self.assertNotIn("articles", entry)
        # Literal, not derived: the two governing records and nothing else.
        self.assertEqual(["necb2020", "necb2025"], entry["editions"])
        (requirement,) = entry["requirements"]
        self.assertEqual(self.KEY, requirement["id"])
        self.assertEqual(
            [("necb", "2020", "governing"), ("necb", "2025", "governing"),
             ("necb", "2020", "related"),
             ("ashrae-62.1", "2016", "incorporated-reference")],
            [(source["code"], source["edition"], source["role"])
             for source in requirement["sources"]])

    def test_no_committed_entry_moves(self):
        self.assertEqual(self.committed["_comment"], self.payload["_comment"])
        self.assertEqual(self.committed["schema"], self.payload["schema"])
        self.assertEqual(ordered(self.committed["decisions"]),
                         ordered(self.payload["decisions"][:-1]))

    def test_the_document_gains_one_index_line_and_one_section(self):
        """Byte-exact: the committed document with exactly the new decision's
        index line and its anchored section added, and nothing else."""
        committed = DECISIONS_DOC.read_text(encoding="utf-8")
        head, end, tail = committed.partition("\n\n<!-- TOC END -->")
        self.assertTrue(end, "the committed document has no index end marker")
        line = "- **{}** — {} _(runtime)_".format(self.new_id, self.front["title"])
        self.assertEqual(
            head + "\n" + line + end + tail + "\n"
            + '<a id="{}"></a>\n\n'.format(self.new_id.lower()) + self.body,
            self.doc)

    def new_rows(self):
        """``(heading, cells)`` for every provision-view row of the new id."""
        return [(heading, cells) for section, heading, cells in view_rows(self.view)
                if section not in VIEW_SECTIONS
                and DECISION_LINK.search(cells[1]).group(1) == self.new_id.lower()]

    def test_the_provision_view_gains_only_its_two_rows_and_three_counts(self):
        """Every committed line survives in its place; the only lines that
        change are the three scope counts, and two rows are added."""
        committed = PROVISION_VIEW.read_text(encoding="utf-8")
        counted = ("| Decisions with concrete rows from structured",
                   "| Decisions included in this view", "| All decisions")
        before = [line for line in committed.splitlines()
                  if not line.startswith(counted)]
        after = [line for line in self.view.splitlines()
                 if not line.startswith(counted)]
        known = set(before)
        added = [line for line in after if line not in known]
        self.assertEqual(before, [line for line in after if line in known],
                         "no committed line moves, changes or disappears")
        self.assertEqual(2, len(added), added)
        for line in added:
            self.assertIn(
                "]({}#{})".format(DECISIONS_DOC.name, self.new_id.lower()), line)

        def scope(view):
            return {cells[0]: int(cells[1]) for section, _h, cells in view_rows(view)
                    if section == "Scope"}
        old, new = scope(committed), scope(self.view)
        self.assertEqual(
            {"Decisions with concrete rows from structured source records": 1,
             "Decisions included in this view": 1, "All decisions": 1},
            {name: new[name] - old[name] for name in new if new[name] != old[name]})

    def test_its_rows_are_its_governing_records_and_nothing_else(self):
        rows = self.new_rows()
        self.assertEqual(
            ["NECB 2020 (code id `necb2020`)", "NECB 2025 (code id `necb2025`)"],
            [heading for heading, _cells in rows])
        (_, row_2020), (_, row_2025) = rows
        # Sentences, then the Appendix note, in provision order.
        self.assertEqual(["8.4.4.13.(1)", "8.4.4.13.(2)", "Note A-8.4.4.13"],
                         code_spans(row_2020[0]))
        self.assertEqual(["8.4.5.13.(1)", "8.4.5.13.(2)", "Note A-8.4.5.13"],
                         code_spans(row_2025[0]))
        for cells in (row_2020, row_2025):
            for related in ("Table 8.4.4.7.-B", "6.2.2.1"):
                self.assertNotIn(related, code_spans(cells[0]))
        self.assertEqual(
            "NECB 2025: " + ", ".join("`{}`".format(c) for c in
                                      ("8.4.5.13.(1)", "8.4.5.13.(2)",
                                       "Note A-8.4.5.13")), row_2020[4])
        self.assertEqual(
            "NECB 2020: " + ", ".join("`{}`".format(c) for c in
                                      ("8.4.4.13.(1)", "8.4.4.13.(2)",
                                       "Note A-8.4.4.13")), row_2025[4])
        # The related NECB record and the incorporated standard are other
        # sources on BOTH rows, and never a row, a heading or an edition.
        sources = ("*incorporated-reference* ashrae-62.1 2016: `6.2.2.1`<br>"
                   "*related* NECB 2020: `Table 8.4.4.7.-B`")
        self.assertEqual([sources, sources], [row_2020[5], row_2025[5]])
        self.assertEqual([], re.findall(r"^#{2,3} .*ashrae", self.view,
                                        re.MULTILINE | re.IGNORECASE))

    def test_its_rows_carry_the_requirements_own_decided_text(self):
        decided = self.front["articles"][self.KEY]["decided"]
        for _heading, cells in self.new_rows():
            self.assertEqual(decided, cells[3])
            self.assertNotIn("Transitional", cells[3])
        self.assertNotIn(self.front["summary"], self.view)
        self.assertNotIn("transitional-summary-" + self.new_id.lower(), self.view)

    def test_the_runtime_loader_resolves_it_from_the_written_file(self):
        with mock.patch.object(Loader, "DATA_DIR", self.registry_path.parent), \
                mock.patch.object(Loader, "_all", None), \
                mock.patch.object(Loader, "_by_id", None):
            entry = Loader.lookup(self.new_id)
            self.assertEqual(self.front["title"], entry["title"])
            self.assertEqual(self.front["summary"], entry["summary"])
            self.assertIn(entry, Loader.of_kind("runtime"))
            self.assertEqual([item["id"] for item in self.payload["decisions"]],
                             Loader.ids())

    def test_only_its_external_record_is_disclosed(self):
        """The committed tree carries no source an index cannot validate, the
        related NECB 2020 record is validated, and the external standard is
        named on both branches."""
        note = ("decisions: note — {} articles[{!r}] cites ashrae-62.1 2016 "
                "(incorporated-reference), which no registered provision index "
                "validates; it is carried as authored and establishes no "
                "edition").format(self.new_id, self.KEY)
        for mode, (_, output) in self.outcomes.items():
            with self.subTest(mode=mode):
                self.assertEqual(
                    [note], [line for line in output.splitlines()
                             if "provision index validates" in line])


class TestTheCommittedProvisionView(unittest.TestCase):
    """``docs/CODE_DECISIONS_BY_PROVISION.md`` against the RAW decision files.

    ``TestGeneratedOutputsAreInStep`` already proves the file is what the
    generator renders. That proves nothing about whether the generator is
    right, so everything here is worked out from the front matter directly,
    with no generator code: which decisions the view must include and omit,
    which row each requirement owes each edition, and where it may not appear.
    """

    #: A SNAPSHOT of this tree at Phase B, taken from the plan's census: 68
    #: decisions cite a provision and 35 cite none. A change to the decision
    #: set moves it legitimately; re-read `docs/decisions/` and update it
    #: together with the sentence in `docs/DEVELOPERS.md` that quotes it.
    INCLUDED, OMITTED = 68, 35

    @classmethod
    def setUpClass(cls):
        cls.view = PROVISION_VIEW.read_text(encoding="utf-8")
        cls.doc = DECISIONS_DOC.read_text(encoding="utf-8")
        cls.front = raw_front_matter()
        (cls.structured, cls.established, cls.held,
         cls.omitted) = classify(cls.front)
        cls.included = cls.structured + cls.established + cls.held
        cls.rows = view_rows(cls.view)
        cls.edition_rows = []
        for section, heading, cells in cls.rows:
            if section not in VIEW_SECTIONS:
                match = EDITION_HEADING.match(heading)
                assert match, "a code section row sits under {!r}".format(heading)
                cls.edition_rows.append((match.group(2), cells))
        cls.held_rows = [cells for section, _heading, cells in cls.rows
                         if section == NOT_ATTRIBUTED]

    @staticmethod
    def linked(cell):
        return DECISION_LINK.search(cell).group(1).upper()

    def test_the_scope_table_counts_what_the_raw_sources_say(self):
        scope = {cells[0]: int(cells[1]) for section, _heading, cells in self.rows
                 if section == "Scope"}
        self.assertEqual({
            "Decisions with concrete rows from structured source records":
                len(self.structured),
            "Decisions with concrete rows from an established legacy mapping":
                len(self.established),
            "Decisions held under Edition not yet attributed": len(self.held),
            "Decisions included in this view": len(self.included),
            "Decisions omitted because they cite no provision":
                len(self.omitted),
            "All decisions": len(self.front)}, scope)

    def test_the_snapshot_census_of_this_tree(self):
        """68 included and 35 omitted: the numbers the plan states for the tree
        Phase B was built on. Independent of the scope table, which is only
        compared with the raw sources above."""
        self.assertEqual((self.INCLUDED, self.OMITTED),
                         (len(self.included), len(self.omitted)),
                         "the decision set changed: re-read docs/decisions/ and "
                         "update this snapshot and its documentation together")

    def test_every_citation_free_decision_is_omitted(self):
        """Not a row, not a link, not a summary anchor, not a held entry."""
        self.assertTrue(self.omitted, "no citation-free decision to test with")
        linked = {self.linked(cells[1]) for _code, cells in self.edition_rows}
        linked |= {self.linked(cells[0]) for cells in self.held_rows}
        anchored = {i.upper() for i in SUMMARY_ANCHOR.findall(self.view)}
        for decision_id in self.omitted:
            with self.subTest(decision=decision_id):
                self.assertNotIn(decision_id, linked | anchored)
                self.assertNotIn(
                    "]({}#{})".format(DECISIONS_DOC.name, decision_id.lower()),
                    self.view)

    def test_every_included_decision_is_present_and_nothing_else_is_linked(self):
        every_link = {i.upper() for i in DECISION_LINK.findall(self.view)}
        self.assertEqual(set(self.included), every_link)
        # Present in the place its class says, and in no other.
        in_editions = {self.linked(cells[1]) for _code, cells in self.edition_rows}
        in_held = {self.linked(cells[0]) for cells in self.held_rows}
        self.assertEqual(set(self.structured) | set(self.established), in_editions)
        self.assertEqual(set(self.held), in_held)
        self.assertEqual(set(), in_editions & in_held)

    def test_a_held_decision_is_never_placed_in_an_edition(self):
        held = set(self.held)
        self.assertTrue(held, "no held decision to test with")
        for code_id, cells in self.edition_rows:
            with self.subTest(code=code_id, row=cells[1][:40]):
                self.assertNotIn(self.linked(cells[1]), held)

    def test_the_held_table_is_the_raw_unverified_decisions_as_recorded(self):
        headings = re.findall(r"^## (.+)$", self.view, re.MULTILINE)
        self.assertEqual(NOT_ATTRIBUTED, headings[-1],
                         "the held decisions are the last section")
        self.assertEqual(
            [self.linked(cells[0]) for cells in self.held_rows], self.held,
            "one row per held decision, in numeric id order")
        for cells in self.held_rows:
            meta = self.front[self.linked(cells[0])]
            with self.subTest(decision=meta["id"]):
                self.assertEqual(4, len(cells))
                self.assertEqual(meta["title"], unescape(cells[1]))
                self.assertEqual([meta["kind"]], code_spans(cells[2]))
                self.assertEqual(meta["articles"]["unverified"],
                                 code_spans(cells[3]),
                                 "citations are listed as recorded, in order")

    def test_each_established_requirement_is_one_row_per_edition(self):
        """One row per (decision, requirement, code id) the raw lists name,
        carrying exactly the citations recorded for that edition."""
        expected = {}
        for decision_id in self.established:
            for key, block in self.front[decision_id]["articles"].items():
                for code_id, citations in block.items():
                    if code_id != "label":
                        expected[(code_id, decision_id, key)] = (block, citations)
        actual = {}
        for code_id, cells in self.edition_rows:
            identity = (code_id, self.linked(cells[1]), code_spans(cells[2])[-1])
            self.assertNotIn(identity, actual, "a requirement is one row per edition")
            actual[identity] = cells
        self.assertEqual(set(expected), set(actual))
        self.assertEqual(len(self.edition_rows), len(expected))
        for identity, (block, citations) in expected.items():
            cells = actual[identity]
            with self.subTest(row=identity):
                self.assertEqual(sorted(citations), sorted(code_spans(cells[0])),
                                 "every citation of the requirement, in ONE row")
                self.assertEqual(len(citations), len(code_spans(cells[0])))
                self.assertEqual(self.front[identity[1]]["title"],
                                 unescape(cells[1].split(") ", 1)[1]))
                self.assertEqual(block["label"],
                                 unescape(cells[2].split("<br>")[0]))

    def test_other_editions_are_the_same_requirements_other_citations(self):
        for code_id, cells in self.edition_rows:
            decision_id, key = self.linked(cells[1]), code_spans(cells[2])[-1]
            block = self.front[decision_id]["articles"][key]
            others = {other: citations for other, citations in block.items()
                      if other not in ("label", code_id)}
            with self.subTest(code=code_id, decision=decision_id, key=key):
                if not others:
                    self.assertEqual("—", cells[4])
                    continue
                self.assertEqual(
                    sorted(c for citations in others.values() for c in citations),
                    sorted(code_spans(cells[4])))
                for other in others:
                    self.assertIn(codes.resolve(other).label + ": ", cells[4])
                self.assertNotIn(codes.resolve(code_id).label + ": ", cells[4])
                self.assertEqual("—", cells[5], "a legacy row has no other sources")

    def test_a_legacy_row_says_its_decided_text_is_transitional(self):
        for code_id, cells in self.edition_rows:
            decision_id = self.linked(cells[1])
            with self.subTest(code=code_id, decision=decision_id):
                self.assertTrue(cells[3].startswith("**Transitional**"), cells[3])
                self.assertIn("(#transitional-summary-{})".format(
                    decision_id.lower()), cells[3])
                self.assertNotIn(self.front[decision_id]["summary"][:60], cells[3])

    def test_each_transitional_summary_is_the_registry_summary_printed_once(self):
        anchors = SUMMARY_ANCHOR.findall(self.view)
        self.assertEqual([i.lower() for i in self.established], anchors)
        section = self.view.split("## Transitional decision summaries\n", 1)[1]
        section = section.split("\n## ", 1)[0]
        chunks = re.split(r'^<a id="transitional-summary-d-\d+"></a>$', section,
                          flags=re.MULTILINE)[1:]
        self.assertEqual(len(self.established), len(chunks))
        for decision_id, chunk in zip(self.established, chunks):
            meta = self.front[decision_id]
            paragraphs = [part for part in chunk.strip().split("\n\n") if part]
            with self.subTest(decision=decision_id):
                self.assertEqual(2, len(paragraphs))
                self.assertIn(self.linked(paragraphs[0]), (decision_id,))
                self.assertEqual(" ".join(meta["summary"].split()),
                                 unescape(paragraphs[1]))
                self.assertEqual(1, self.view.count(paragraphs[1]),
                                 "the summary is printed once, not on every row")

    def test_rows_read_the_provision_number_numerically(self):
        """8.4.4.9 before 8.4.4.10 -- a string sort puts them the other way."""
        by_code = {}
        for code_id, cells in self.edition_rows:
            by_code.setdefault(code_id, []).append(code_spans(cells[0])[0])
        self.assertTrue(by_code)
        for code_id, firsts in by_code.items():
            numbers = [leading_number(span) for span in firsts]
            with self.subTest(code=code_id):
                self.assertGreater(len(firsts), 1)
                self.assertEqual(sorted(numbers), numbers, firsts)

    def test_every_row_has_exactly_the_six_columns(self):
        for code_id, cells in self.edition_rows:
            with self.subTest(code=code_id, row=cells[1][:40]):
                self.assertEqual(6, len(cells))
                self.assertTrue(all(cells))

    def test_every_decision_link_resolves_to_its_log_anchor(self):
        anchors = set(re.findall(r'^<a id="(d-\d+)"></a>$', self.doc, re.MULTILINE))
        links = set(DECISION_LINK.findall(self.view))
        self.assertTrue(links)
        self.assertEqual(set(), links - anchors)

    def test_the_view_states_what_its_source_provenance_and_status_mean(self):
        for heading in ("### Source", "### Provenance", "### Status",
                        "### Reading a row"):
            self.assertIn("\n" + heading + "\n", self.view)
        status = {cells[0] for section, heading, cells in self.rows
                  if section == "Definitions" and heading == "Status"}
        self.assertEqual({"Governing", "Incorporated reference, related",
                          "Transitional", "Not yet attributed"}, status)
        self.assertIn("reproduces no Code text", self.view)

    def test_the_view_is_a_pure_function_of_the_sources(self):
        entries = G.read_sources(SOURCE_DIR)[1]
        reversed_entries = dict(reversed(list(entries.items())))
        self.assertEqual(self.view, G.render_provision_view(entries))
        self.assertEqual(self.view, G.render_provision_view(reversed_entries))
        self.assertEqual(self.view, G.generate(SOURCE_DIR)[2])


class TestTheMigrationCannotRunAgain(unittest.TestCase):
    def test_split_refuses_once_the_sources_exist(self):
        """``--split`` bootstrapped the sources; it must never overwrite them."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--split"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(1, result.returncode,
                         "--split must fail closed against real sources")
        self.assertIn("refusing to split", result.stdout + result.stderr)

    def test_the_retired_toc_generator_is_gone(self):
        """One writer. A second one would let the two drift apart silently."""
        self.assertFalse((PYTHON_ROOT / "scripts" / "generate_decisions_toc.py").exists())


if __name__ == "__main__":
    unittest.main()
