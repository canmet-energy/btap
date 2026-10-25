"""Every AUTHORED sample must size with zero Severe and zero Fatal errors.

CLAUDE.md's rule for our own artifacts: a sample WE author should be clean,
because shipping one with a known Severe teaches the wrong thing. The opposite
policy governs a SUBMITTED proposed model, where a Severe does not stop the
run — see "A proposed FATAL stops the run; a proposed SEVERE does not".

This reads the committed verdict. `simulate_all_samples.py --check` re-derives
it with real EnergyPlus runs and is the gate that would catch drift; this test
is the cheap assertion that the committed verdict says what it must, and runs
with no engine at all.

Issue #68 is why it exists: `04-fancoil-chiller` and `13-district-heating`
shipped for three weeks with a `Coil:Cooling:Water` design-UA Severe, because
the catalogue sweep proves a SYSTEM on the shared bare fixture and nothing
sized the generated sample (D-107, Sol's `313`).
"""

import json
import unittest
from pathlib import Path

STATUS = Path(__file__).resolve().parents[1] / "fixtures" / "sample_simulation_status.json"
MANIFEST = (Path(__file__).resolve().parents[2] / "scripts"
            / "sample_manifest.json")


class TestSampleSimulationStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(STATUS.read_text(encoding="utf-8"))
        cls.rows = cls.payload["samples"]

    def test_the_schema_is_pinned(self):
        self.assertEqual(1, self.payload["schema"])

    def test_every_manifest_sample_has_a_verdict_and_nothing_else_does(self):
        expected = sorted(
            json.loads(MANIFEST.read_text(encoding="utf-8"))["samples"])
        self.assertEqual(
            expected, sorted(r["name"] for r in self.rows),
            "the verdict must cover the manifest EXACTLY — a sample with no "
            "verdict is an ungated artifact, and a verdict with no sample is "
            "a stale row that would hide one")

    def test_no_authored_sample_ships_with_a_severe_or_fatal(self):
        dirty = [r for r in self.rows
                 if r["severe"] or r["fatal"] or r["status"] != "ok"]
        self.assertEqual(
            [], dirty,
            "a sample WE author must size cleanly; these do not: "
            + ", ".join(f"{r['name']}(severe={r['severe']},"
                        f"fatal={r['fatal']},{r['status']})" for r in dirty))

    def test_every_row_completed(self):
        """A Severe count of zero on a run that never finished proves nothing."""
        incomplete = [r["name"] for r in self.rows if not r["completed"]]
        self.assertEqual(
            [], incomplete,
            "EnergyPlus must report 'Completed Successfully'; a zero Severe "
            f"count on an unfinished run is not evidence: {incomplete}")

    def test_the_two_issue_68_samples_are_covered(self):
        """The gate is worthless if it does not reach the known offenders."""
        names = {r["name"] for r in self.rows}
        for slug in ("04-fancoil-chiller", "13-district-heating"):
            self.assertIn(
                slug, names,
                f"{slug} carried the issue-68 Severe and must be gated")


if __name__ == "__main__":
    unittest.main()
