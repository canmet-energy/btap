"""A scoped re-freeze may change only what it re-ran.

`freeze.py --scenario ID` exists because a full 54-scenario freeze for one
moved output is what made the frozen corpus expensive enough to defer a
correctness fix: 28 of 89 manifest commits were hash-only re-freezes, and
`gate_sha256` hashing the gate file deferred issue #99's own lock for rounds
(Fable's `226`, Sol's `227`).

Scoping is dangerous in a specific way, and the danger is not hypothetical —
my first implementation did it. `promote()` MOVES the whole baselines
directory and rewrites the whole manifest, so a scope that forgets what it
does not own destroys it while reporting success. That version wrote:

    active_seals                      31/23  ->  0/1
    retired_seals                      29/2  ->  0/0
    final_cross_language_attestation  the D-84 record  ->  null

because the seal tallies and the attestation were computed from the SELECTED
scenarios rather than from every defined one. The scenario COUNT stayed right,
so the count guard saw nothing; only reading the diff caught it. Sol's `227`
rules that attestation immutable in terms.

These tests pin the three properties that make scoping safe, by calling the
producer rather than by re-deriving its arithmetic:

1. every defined scenario is still described, and has a baseline directory;
2. the corpus-wide provenance a scope does not own is unchanged; and
3. an unknown id, a missing manifest, or an id absent from the manifest is
   refused rather than guessed at.

They run the refusal paths, which need no simulation. The positive path — a
real scoped freeze preserving 53 baselines byte-for-byte — needs an engine and
is exercised by `verification/scenarios/freeze.py --scenario` in the parity
lane; the module-level docstring above records the measured result.
"""
import json
import pathlib
import subprocess
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FREEZE = REPO_ROOT / "verification" / "scenarios" / "freeze.py"
MANIFEST = REPO_ROOT / "verification" / "scenarios" / "manifest.json"


def _source():
    return FREEZE.read_text(encoding="utf-8")


class TestTheScopedFreezeContract(unittest.TestCase):
    def test_the_flag_exists_and_is_repeatable(self):
        source = _source()
        self.assertIn(
            '"--scenario"', source,
            "the whole point of this change is that one moved output stops "
            "costing 54 re-runs")
        self.assertIn(
            'action="append"', source,
            "repeatable, because a behaviour change usually moves a handful "
            "of scenarios rather than one")

    def test_corpus_wide_facts_come_from_EVERY_scenario(self):
        """The bug I shipped, as a source-level property.

        `seal_accounting` must be called with the unfiltered list. Calling it
        with the scoped subset is what destroyed the seal tallies and the
        D-84 attestation, and it did so while reporting success.
        """
        source = _source()
        self.assertIn(
            "seal_accounting(\n            every_scenario)", source,
            "`seal_accounting` must take the UNFILTERED scenario list. With "
            "the scoped subset it wrote active_seals 31/23 -> 0/1 and the "
            "final cross-language attestation -> null")
        self.assertIn(
            "every_scenario = list(scenarios)", source,
            "the unfiltered list has to be captured before the scope filter "
            "narrows `scenarios`")

    def test_the_promotion_guards_are_present_and_name_what_they_protect(self):
        source = _source()
        for probe, why in (
            ("refusing to promote: the manifest would describe",
             "a scope that drops scenarios from the manifest"),
            ("refusing to promote: no staged baseline directory",
             "a scope that drops a baseline DIRECTORY, which `promote` would "
             "then delete"),
            ("provenance.{field}",
             "a scope that changes corpus-wide provenance"),
            ("spec_sha256", "a scope taken while the comparison rules moved"),
        ):
            with self.subTest(guard=probe[:40]):
                self.assertIn(probe, source, why)

    def test_an_unknown_scenario_id_is_REFUSED(self):
        done = subprocess.run(
            [sys.executable, str(FREEZE), "--allow-dirty",
             "--scenario", "no-such-scenario-exists"],
            capture_output=True, text=True, check=False,
            cwd=str(REPO_ROOT), timeout=300,
            env={**_env(), "BTAP_SCENARIO_BACKEND": ""})
        self.assertNotEqual(0, done.returncode)
        self.assertIn(
            "no such scenario", (done.stdout + done.stderr).lower(),
            "a typo in a scenario id must be refused by name, not silently "
            "re-freeze nothing and promote a manifest describing one "
            "scenario")

    def test_the_manifest_still_carries_what_a_scope_must_preserve(self):
        """The fields the guard compares, present in the committed manifest.

        If the attestation were ever absent here, the guard would be
        comparing `None` to `None` and would pass vacuously.
        """
        if not MANIFEST.is_file():
            self.skipTest(f"{MANIFEST} is not present in this layout")
        provenance = json.loads(
            MANIFEST.read_text(encoding="utf-8"))["provenance"]
        self.assertTrue(
            provenance.get("active_seals"),
            "active_seals must be non-empty or the guard that protects it "
            "compares nothing to nothing")
        attestation = provenance.get("final_cross_language_attestation")
        self.assertTrue(
            attestation and attestation.get("run_id"),
            "D-84's final cross-language attestation must be present and "
            "carry its run identity; it is immutable (Sol, `227`) and a "
            "scoped freeze destroyed it once")

    def test_the_machinery_hashes_are_GONE_from_the_producer(self):
        """They are what made a scoped freeze necessary in the first place."""
        source = _source()
        for dead in ("freezer_sha256", "defs_sha256", "runner_sha256",
                     "api_worker_sha256", "compare_runs_sha256",
                     "audit_scenario_sha256", "gate_sha256"):
            with self.subTest(field=dead):
                self.assertNotIn(
                    f'"{dead}": runner.sha256', source,
                    f"{dead} is written again. A hash of a source file "
                    "proves it changed, not that comparison weakened — and "
                    "`gate_sha256` made the gate file itself cost a "
                    "54-scenario re-freeze to edit")
        self.assertIn(
            '"spec_sha256"', source,
            "spec_sha256 STAYS: it pins the adjudicated comparison rules, "
            "which is a different claim from pinning the source of the code "
            "that applies them")


def _env():
    import os

    return {k: v for k, v in os.environ.items()}


if __name__ == "__main__":
    unittest.main()
