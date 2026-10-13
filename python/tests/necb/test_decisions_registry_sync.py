"""The decision sources are canonical; both outputs are generated from them.

One decision is one file, ``docs/decisions/D-NN.md``. This module gates the
repository's actual state: that every source parses, that the two generated
artifacts are in step with the sources, and that neither artifact has been
hand-edited. The generator's own behaviour -- its parser, its TOML writer and
its validation -- is exercised in ``test_decisions_generator.py``.

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
            "entr(ies) in the canonical directory that reach neither generated "
            f"output: {stray}")

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
    """Neither artifact may drift from, or be edited beside, its sources."""

    @classmethod
    def setUpClass(cls):
        cls.doc, cls.registry = G.generate(SOURCE_DIR)
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

    def test_both_outputs_carry_exactly_the_source_id_set(self):
        headings = HEADING_PATTERN.findall(self.doc)
        self.assertEqual(len(headings), len(set(headings)),
                         "duplicate ## D-XX headings in the generated document")
        self.assertEqual(set(headings), set(self.entries))
        registry_ids = [entry["id"] for entry in json.loads(self.registry)["decisions"]]
        self.assertEqual(len(registry_ids), len(set(registry_ids)),
                         "duplicate ids in the generated registry")
        self.assertEqual(set(registry_ids), set(self.entries))

    def test_both_outputs_are_in_numeric_id_order(self):
        """Numeric id order is the ordering invariant, and the only one.

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
        cls.registry_path.parent.mkdir()
        arguments = ["--source-dir", str(cls.source_dir), "--doc", str(cls.doc_path),
                     "--registry", str(cls.registry_path)]
        cls.outcomes = {}
        for mode, argv in (("write", arguments), ("check", ["--check", *arguments])):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                cls.outcomes[mode] = (G.main(argv), out.getvalue())
        cls.doc = cls.doc_path.read_text(encoding="utf-8")
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
