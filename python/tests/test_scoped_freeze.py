"""A scoped re-freeze may change only what it re-ran.

`freeze.py --scenario ID` exists because a full 54-scenario freeze for one
moved output is what made the frozen corpus expensive enough to defer a
correctness fix: 28 of 89 manifest commits touched no baseline file at all
(Sol's measurement; "hash-only" was my looser phrasing for it), and
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

This module has two halves, and the difference between them matters.

**Executed.** `TestTheScopedFreezePOSITIVEPath` drives the real
`freeze.assemble_scope()` with no engine: three synthetic scenarios, two
carried from host P0 and one re-run on P1. It asserts what survives
promotion — both producer identities, byte-identical carried baselines,
whole carried entries, and the completeness guard — and it asserts the
refusals as refusals: a corrupted carried baseline, an undeclared extra
file, a missing directory for a scenario that declares baselines, a re-run
entry whose own hash is wrong, and an incomplete scope. `228` asked for this
and `231` recorded that it had not landed; the logic was inside the function
that runs EnergyPlus, so `assemble_scope()` is extracted for it.

The mutation matrix is the reason to believe it: disabling the staged
verification kills three of those tests, and removing the completeness guard
kills nine.

**Source-inspected.** The five checks below read `freeze.py` as text. They
prove the guards are WRITTEN, not that they fire, and they exist for the
parts still inside `main()` — argument handling, the manifest-absent
refusal, and the corpus-wide fields a scope must not recompute. Treat them
as the weaker evidence they are.

**Not covered by either.** No CI job passes `--scenario`. The end-to-end
scope with a real engine has only ever been run by hand, most recently in a
scratch worktree at this head:

```text
--scenario verdict-compliant, 53 carried   frozen 54 scenarios, seals intact
a STALE definition for a carried scenario  added to the selected set, re-run
the empty `internal-dead-remote` directory absent on a fresh clone; handled
```

"""
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FREEZE = REPO_ROOT / "verification" / "scenarios" / "freeze.py"
MANIFEST = REPO_ROOT / "verification" / "scenarios" / "manifest.json"


def _load_freeze():
    """Import `freeze.py` as a module, for the tests that EXECUTE it."""
    spec = importlib.util.spec_from_file_location("freeze_under_test", FREEZE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["freeze_under_test"] = module
    spec.loader.exec_module(module)
    return module


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


class TestTheScopedFreezePOSITIVEPath(unittest.TestCase):
    """A successful scope, executed — not grepped out of the source.

    `228` asked for a synthetic scoped freeze with DISTINCT producer
    identities proving both the selected and the carried side, and `231`
    recorded that it had not landed and that the refusals were still only
    strings searched for in `freeze.py`. Neither was testable while the
    logic lived inside the function that runs EnergyPlus, so
    `assemble_scope()` is extracted; this drives it with no engine at all.

    The fixture is three scenarios: `kept-a` and `kept-b` frozen on host P0,
    and `rerun-c` re-frozen here on P1. The question each test asks is what
    survives promotion.
    """

    P0 = {"producer": "P0: openstudio 3.11.0 @ host-zero",
          "openstudio_cli": "3.11.0"}
    P1 = {"producer": "P1: openstudio 3.11.0 @ host-one",
          "openstudio_cli": "3.11.0"}

    def setUp(self):
        self.freeze = _load_freeze()
        self.runner = self.freeze.runner
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="scoped-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.committed = self.work / "committed"
        self.staged = self.work / "staged"
        self.committed.mkdir()
        self.staged.mkdir()

        #: The committed side: two carried scenarios with real bytes.
        self.previous = {"scenarios": []}
        for name, payload in (("kept-a", '{"compliant": true}\n'),
                              ("kept-b", '{"compliant": false}\n')):
            directory = self.committed / name
            directory.mkdir()
            (directory / "report.json").write_text(payload, encoding="utf-8")
            self.previous["scenarios"].append({
                "id": name, "lane": "python", "files": ["report.json"],
                "baseline_sha256": {
                    "report.json": self.runner.sha256(
                        directory / "report.json")},
                "produced_by": dict(self.P0)})

        #: The staged side: the one re-run scenario, as `main()` leaves it.
        rerun = self.staged / "rerun-c"
        rerun.mkdir()
        (rerun / "report.json").write_text('{"compliant": true}\n',
                                           encoding="utf-8")
        self.frozen = [{
            "id": "rerun-c", "lane": "python", "files": ["report.json"],
            "baseline_sha256": {
                "report.json": self.runner.sha256(rerun / "report.json")},
            "produced_by": dict(self.P1)}]
        self.all_ids = ["kept-a", "kept-b", "rerun-c"]

    def _assemble(self):
        """Run the real `assemble_scope` against the fixture.

        `runner.BASELINES` is the committed tree for the duration, which is
        where a carried baseline is read from.
        """
        def fail(message):
            raise AssertionError(message)

        previous_baselines = self.runner.BASELINES
        self.runner.BASELINES = self.committed
        try:
            return self.freeze.assemble_scope(
                list(self.frozen),
                [dict(s) for s in self.previous["scenarios"]],
                self.staged, self.previous, self.all_ids, self.runner, fail)
        finally:
            self.runner.BASELINES = previous_baselines

    def test_a_successful_scope_keeps_BOTH_producer_identities(self):
        """The property `228` asked for, and the reason the field is per
        scenario at all: one invocation must not relabel work it did not do.
        """
        result = self._assemble()
        by_id = {s["id"]: s for s in result}
        self.assertEqual(self.all_ids, [s["id"] for s in result],
                         "the scope must describe every defined scenario, "
                         "in the defined order")
        self.assertEqual(
            self.P0, by_id["kept-a"]["produced_by"],
            "a CARRIED baseline keeps the identity of the host that made "
            "it; relabelling it with this invocation's producer is the "
            "defect the per-scenario field exists to stop (Sol, `228`)")
        self.assertEqual(self.P0, by_id["kept-b"]["produced_by"])
        self.assertEqual(
            self.P1, by_id["rerun-c"]["produced_by"],
            "and the RE-RUN scenario carries this invocation's identity")

    def test_a_carried_baseline_arrives_BYTE_identical(self):
        self._assemble()
        for name in ("kept-a", "kept-b"):
            committed = (self.committed / name / "report.json").read_bytes()
            promoted = (self.staged / name / "report.json").read_bytes()
            self.assertEqual(committed, promoted,
                             f"{name} was carried, not re-run, so its bytes "
                             "must be the committed bytes")

    def test_the_carried_HASHES_and_definitions_are_unchanged(self):
        result = self._assemble()
        by_id = {s["id"]: s for s in result}
        for entry in self.previous["scenarios"]:
            with self.subTest(scenario=entry["id"]):
                self.assertEqual(entry, by_id[entry["id"]],
                                 "a carried entry is carried WHOLE — hashes, "
                                 "lane, files and producer")

    def test_a_CORRUPTED_carried_baseline_refuses(self):
        """The first of Fable's `228` cases, as an executable test."""
        (self.committed / "kept-a" / "report.json").write_text(
            '{"compliant": "corrupted"}\n', encoding="utf-8")
        with self.assertRaises(AssertionError) as caught:
            self._assemble()
        self.assertIn("kept-a", str(caught.exception))
        self.assertIn("does not match its manifest sha256",
                      str(caught.exception),
                      "the refusal must name the file and say why, or a "
                      "maintainer cannot act on it")
        self.assertIn("the staged tree does not match",
                      str(caught.exception),
                      "and it must come from the STAGED check, which is the "
                      "one that covers carried and re-run entries alike — a "
                      "carry-time duplicate caught nothing this does not")

    def test_an_UNDECLARED_extra_file_in_a_carried_baseline_refuses(self):
        """The second case. A frozen directory is an exact set."""
        (self.committed / "kept-b" / "extra.json").write_text(
            "{}\n", encoding="utf-8")
        with self.assertRaises(AssertionError) as caught:
            self._assemble()
        self.assertIn("extra.json", str(caught.exception))

    def test_an_undeclared_SUBDIRECTORY_in_a_baseline_refuses(self):
        """`is_file()` made "an exact set" false for anything not a file.

        An undeclared subdirectory was published with exit 0, invisible to
        the freeze and to the gate (Fable, `231` R1). It cannot alter a
        comparison, because nothing reads it — but the claim was exactness,
        and a directory that quietly accumulates is how a baseline tree
        stops being the thing the manifest describes.
        """
        (self.committed / "kept-a" / "leftovers").mkdir()
        (self.committed / "kept-a" / "leftovers" / "x.json").write_text(
            "{}\n", encoding="utf-8")
        with self.assertRaises(AssertionError) as caught:
            self._assemble()
        self.assertIn("leftovers", str(caught.exception))

    def test_a_carried_scenario_whose_DIRECTORY_is_gone_refuses(self):
        shutil.rmtree(self.committed / "kept-a")
        with self.assertRaises(AssertionError) as caught:
            self._assemble()
        self.assertIn("declares baselines", str(caught.exception))

    def test_a_scenario_with_NO_baselines_may_have_no_directory(self):
        """The `internal-dead-remote` case: Git stores no empty directory.

        Refusing here made `--scenario` unusable on every fresh clone and in
        every new worktree, which is where DEVELOPERS.md says to freeze
        (Fable, `228`).
        """
        self.previous["scenarios"].append(
            {"id": "no-files", "lane": "python", "files": [],
             "baseline_sha256": {}, "produced_by": dict(self.P0)})
        self.all_ids.append("no-files")
        result = self._assemble()
        self.assertEqual(4, len(result))
        self.assertTrue((self.staged / "no-files").is_dir(),
                        "an empty staged directory, so the whole-tree "
                        "promotion publishes a complete set")

    def test_an_INCOMPLETE_scope_refuses_rather_than_deleting_baselines(self):
        """The guard that makes whole-directory promotion safe at all."""
        self.all_ids.append("never-staged")
        with self.assertRaises(AssertionError) as caught:
            self._assemble()
        self.assertIn("never-staged", str(caught.exception))
        self.assertIn("refusing to promote", str(caught.exception))

    def test_a_RE_RUN_scenario_whose_hash_is_wrong_refuses(self):
        """The staged side is verified too, not only the carried side."""
        self.frozen[0]["baseline_sha256"]["report.json"] = "0" * 64
        with self.assertRaises(AssertionError) as caught:
            self._assemble()
        self.assertIn("rerun-c", str(caught.exception))
        self.assertIn("the staged tree does not match", str(caught.exception))
