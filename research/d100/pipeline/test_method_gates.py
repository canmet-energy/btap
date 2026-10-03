#!/usr/bin/env python3
"""Negative probes for the D-100 method gates. Offline, stdlib unittest.

    cd research/d100/pipeline && python3 -m unittest test_method_gates -v

A gate that has only ever been run against a clean archive is not a gate. Sol
falsified the first version of `integrity.py` by mutating the one
`returned_mismatch` payload — a table ROW changed, hash untouched — and both
`integrity.py` and the offline `rebuild.py` called the archive sound (`074`).
Every mutation he reported is pinned here, so the hole cannot reopen quietly, and
so a future reader can see which specific corruptions the gate is known to catch.

The clean-archive assertion is deliberately FIRST and deliberately not the point:
each mutation copies the committed archive into a temporary directory, corrupts
one thing, and requires a finding.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import compare
import integrity
import rebuild
from common import ARTIFACT_ROOT

MISMATCH = "get_table__necb__8.4.4.1__2020"
PRESENT_TABLE = "get_table__necb__3.2.2.2__2020"


def _sha(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class ArchiveProbe(unittest.TestCase):
    """Each test gets its own copy of the committed archive."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        shutil.copytree(ARTIFACT_ROOT / "hbix", self.dir / "hbix")
        for name in ("citations.json", "hbix_index.json"):
            shutil.copy2(ARTIFACT_ROOT / name, self.dir)

    # -- helpers ---------------------------------------------------------
    def payload_path(self, key):
        return self.dir / "hbix" / f"{key}.json"

    def edit_payload(self, key, mutate, rehash=False):
        path = self.payload_path(key)
        stored = json.loads(path.read_text(encoding="utf-8"))
        mutate(stored)
        if rehash and stored.get("payload") is not None:
            stored["meta"]["sha256"] = _sha(stored["payload"])
        path.write_text(json.dumps(stored, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        return stored

    def edit_index(self, mutate):
        path = self.dir / "hbix_index.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        mutate(doc)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False,
                                   sort_keys=True) + "\n", encoding="utf-8")

    def findings(self):
        found, _ = integrity.check(self.dir)
        return found

    def assertCaught(self, needle=None):
        found = self.findings()
        self.assertTrue(found, "the gate reported the archive sound")
        if needle:
            self.assertTrue(any(needle in f for f in found),
                            f"no finding mentioned {needle!r}: {found}")

    # -- the clean case, first and least interesting ----------------------
    def test_the_committed_archive_is_sound(self):
        self.assertEqual([], self.findings())

    # -- Sol's `074` mutations -------------------------------------------
    def test_a_row_changed_inside_the_returned_mismatch_payload(self):
        """His headline falsification: the mismatch payload was never hashed."""
        def mutate(stored):
            row = stored["payload"]["rows"][0]
            row[sorted(row)[0]] = "CORRUPTED"
        self.edit_payload(MISMATCH, mutate)          # hash deliberately untouched
        self.assertCaught("sha256 does not recompute")

    def test_a_row_changed_inside_a_present_payload(self):
        def mutate(stored):
            row = stored["payload"]["rows"][0]
            row[sorted(row)[0]] = "CORRUPTED"
        self.edit_payload(PRESENT_TABLE, mutate)
        self.assertCaught("sha256 does not recompute")

    def test_a_stored_state_disagreeing_with_the_index(self):
        """Only `request` was compared, so `state` could diverge silently."""
        self.edit_payload(MISMATCH, lambda s: s["meta"].update(state="error"))
        self.assertCaught("meta.state disagrees")

    def test_the_index_request_count_is_read(self):
        self.edit_index(lambda d: d.update(request_count=0))
        self.assertCaught("request_count")

    def test_a_present_payload_with_its_edition_erased(self):
        """`if edition and ...` treated absent identity as valid."""
        self.edit_payload(PRESENT_TABLE,
                          lambda s: s["payload"].pop("edition", None), rehash=True)
        self.edit_index(lambda d: d["index"][PRESENT_TABLE].update(
            sha256=_sha(json.loads(
                self.payload_path(PRESENT_TABLE).read_text())["payload"])))
        self.assertCaught("declares no edition")

    def test_a_returned_mismatch_that_does_not_actually_mismatch(self):
        """The state must earn its name, or it is just an unchecked payload."""
        def mutate(stored):
            stored["payload"]["table_number"] = \
                stored["meta"]["request"]["table_number"]
        self.edit_payload(MISMATCH, mutate, rehash=True)
        self.edit_index(lambda d: d["index"][MISMATCH].update(
            sha256=_sha(json.loads(
                self.payload_path(MISMATCH).read_text())["payload"])))
        self.assertCaught("identifies itself as exactly what was requested")

    def test_a_deleted_payload_file(self):
        self.payload_path(PRESENT_TABLE).unlink()
        self.assertCaught("no payload file")

    def test_an_undeclared_state(self):
        self.edit_payload(PRESENT_TABLE, lambda s: s["meta"].update(state="fine"))
        self.edit_index(lambda d: d["index"][PRESENT_TABLE].update(state="fine"))
        self.assertCaught("undeclared state")


class ClauseProbe(unittest.TestCase):
    """A cited subclause is not the same address as its parent sentence.

    `wanted_sentences("(1)(a)")` returned `[1]`, so `8.4.3.6.(1)(a)` was reported
    at `granularity: "cited sentence"` even though the archived 2020 section has
    a single `1)` line and no `a)` clause at all — the same false-precision class
    as the D-62 range bug (Sol, `074`).
    """

    def test_a_lettered_clause_is_requested_as_a_clause(self):
        self.assertEqual(([1], "a"), compare.wanted_fragment("(1)(a)"))
        self.assertEqual(([1], "c"), compare.wanted_fragment("(1)(c)"))

    def test_a_plain_sentence_has_no_clause(self):
        self.assertEqual(([2], None), compare.wanted_fragment("(2)"))
        self.assertEqual(([4, 5], None), compare.wanted_fragment("(4)-(5)"))

    def test_an_absent_clause_cannot_be_isolated(self):
        """2020's 8.4.3.6 shape: one numbered sentence, no lettered clauses."""
        body = "1) The reference building shall comply with this Subsection.\n"
        text, complete = compare.clause_of(body, [1], "a")
        self.assertIsNone(text)
        self.assertFalse(complete)

    def test_a_present_clause_is_isolated(self):
        body = ("1) The following apply:\n"
                "a) the first condition, and\n"
                "b) the second condition.\n")
        text, complete = compare.clause_of(body, [1], "a")
        self.assertTrue(complete)
        self.assertIn("first condition", text)
        self.assertNotIn("second condition", text)


class NoteProbe(unittest.TestCase):
    """The Table-Note comparison path, which the CORPUS cannot exercise.

    None of the three Table Note citations is `present` at the same address in
    both editions, so the note path is never reached by real data (Sol, `074`).
    A synthetic two-present-side probe is the only way to know it works.
    """

    PARENT = ("Notes to Table 8.4.5.7.-B\n"
              "(1) The values apply to the reference building only.\n"
              "(2) Interpolation is permitted.\n")

    def test_the_requested_note_is_isolated(self):
        text = compare.note_text({"full_text": self.PARENT}, "Note (1)")
        self.assertIn("reference building", text)
        self.assertNotIn("Interpolation", text)

    def test_a_later_note_is_isolated(self):
        text = compare.note_text({"full_text": self.PARENT}, "Note (2)")
        self.assertIn("Interpolation", text)
        self.assertNotIn("reference building", text)

    def test_an_absent_note_is_not_invented(self):
        self.assertIsNone(compare.note_text({"full_text": self.PARENT}, "Note (9)"))

    def test_two_present_sides_compare_as_a_note(self):
        """The path the corpus cannot reach: both editions present."""
        entry = {"kind": "table", "fragment": "Note (1)",
                 "cited_by": ["D-55"], "requests": {}}
        changed = self.PARENT.replace("reference building only",
                                      "reference building and the proposed building")
        sides = {
            "2020": {"get_table": {"meta": {"state": "present"}, "payload": {"rows": []}},
                     "get_section": {"meta": {"state": "present"},
                                     "payload": {"full_text": self.PARENT}}},
            "2025": {"get_table": {"meta": {"state": "present"}, "payload": {"rows": []}},
                     "get_section": {"meta": {"state": "present"},
                                     "payload": {"full_text": changed}}},
        }
        record = compare.compare_one(entry, sides)
        self.assertEqual("table note, from the parent article", record["granularity"])
        self.assertEqual("differs", record["verdict"])
        self.assertTrue(record["diff_spans"], "a changed note must show a span")

    def test_two_present_sides_with_an_identical_note(self):
        entry = {"kind": "table", "fragment": "Note (1)",
                 "cited_by": ["D-55"], "requests": {}}
        side = {"get_table": {"meta": {"state": "present"}, "payload": {"rows": []}},
                "get_section": {"meta": {"state": "present"},
                                "payload": {"full_text": self.PARENT}}}
        record = compare.compare_one(entry, {"2020": side, "2025": side})
        self.assertEqual("substantively identical", record["verdict"])


class RefetchProbe(unittest.TestCase):
    """`--refetch` must finish comparing, and must distinguish a persisting
    server erratum from a changed answer (Sol, `074`)."""

    def side(self, state, rows):
        return {"meta": {"state": state}, "payload": {"rows": rows}}

    def test_an_unchanged_known_mismatch_is_a_note_not_a_finding(self):
        before = {"k": self.side("returned_mismatch", [{"a": "1"}])}
        after = {"k": self.side("returned_mismatch", [{"a": "1"}])}
        findings, notes = rebuild.compare_evidence(before, after, {"k"})
        self.assertEqual([], findings)
        self.assertTrue(any("erratum persists" in n or "expected" in n for n in notes))

    def test_a_changed_row_inside_a_known_mismatch_IS_a_finding(self):
        before = {"k": self.side("returned_mismatch", [{"a": "1"}])}
        after = {"k": self.side("returned_mismatch", [{"a": "CHANGED"}])}
        findings, _ = rebuild.compare_evidence(before, after, {"k"})
        self.assertTrue(findings, "a changed payload must be reported even in a "
                                  "state we expect to persist")

    def test_a_changed_present_payload_is_a_finding(self):
        before = {"k": self.side("present", [{"a": "1"}])}
        after = {"k": self.side("present", [{"a": "2"}])}
        findings, _ = rebuild.compare_evidence(before, after, set())
        self.assertTrue(findings)

    def test_a_mismatch_that_became_present_is_a_finding(self):
        """Resolved upstream is good news, but it still moves the evidence."""
        before = {"k": self.side("returned_mismatch", [{"a": "1"}])}
        after = {"k": self.side("present", [{"a": "1"}])}
        findings, _ = rebuild.compare_evidence(before, after, {"k"})
        self.assertTrue(findings)

    def test_a_changed_request_set_is_a_finding(self):
        findings, _ = rebuild.compare_evidence(
            {"a": self.side("present", [])}, {"b": self.side("present", [])}, set())
        self.assertTrue(any("request set changed" in f for f in findings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
