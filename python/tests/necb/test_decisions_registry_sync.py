"""The decision sources are canonical; both outputs are generated from them.

One decision is one file, ``docs/decisions/D-NN.md``. This module gates the
repository's actual state: that every source parses, that the two generated
artifacts are in step with the sources, and that neither artifact has been
hand-edited. The generator's own behaviour -- its parser, its TOML writer and
its validation -- is exercised in ``test_decisions_generator.py``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = PYTHON_ROOT.parent

sys.path.insert(0, str(PYTHON_ROOT / "scripts"))
import generate_decisions as G  # noqa: E402

PYTHON_REGISTRY = PYTHON_ROOT / "btap" / "codes" / "data" / "decisions.json"
DECISIONS_DOC = REPO_ROOT / "docs" / "necb_decisions.md"
SOURCE_DIR = REPO_ROOT / "docs" / "decisions"
SCRIPT = PYTHON_ROOT / "scripts" / "generate_decisions.py"

ID_PATTERN = re.compile(r"^D-\d{2}$")
HEADING_PATTERN = re.compile(r"^## (D-\d{2})\b", re.MULTILINE)


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
        anchors = re.findall(r'^<a id="(d-\d{2})"></a>$', self.doc, re.MULTILINE)
        self.assertEqual(len(anchors), len(set(anchors)), "duplicate generated anchor")
        self.assertEqual({i.lower() for i in self.entries}, set(anchors),
                         "every decision must carry its generated anchor")
        for decision_id in self.entries:
            with self.subTest(decision=decision_id):
                self.assertIn(
                    '<a id="{}"></a>\n\n## {} '.format(decision_id.lower(), decision_id),
                    self.doc, "the anchor must sit immediately above its heading")

    def test_the_registry_is_the_front_matter_projection(self):
        """The JSON carries the five registry fields and nothing else."""
        for entry in json.loads(self.registry)["decisions"]:
            with self.subTest(decision=entry["id"]):
                self.assertEqual(tuple(entry), G.FIELDS)
                self.assertEqual(entry, {f: self.entries[entry["id"]][0][f]
                                         for f in G.FIELDS})


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
