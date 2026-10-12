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
from unittest import mock

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


class TestTheScopedProvenanceGuardEXECUTES(unittest.TestCase):
    """The corpus-wide half of a scoped freeze, driven rather than grepped.

    `assemble_scope()` covers the scenario TREE. It ends before manifest
    provenance is assembled, so the seals, the D-84 attestation and
    `spec_sha256` were watched only by a source-substring assertion — and
    `233` measured what that is worth: removing
    `final_cross_language_attestation` from the guarded tuple left all
    sixteen scoped-freeze tests green.

    `assemble_manifest()` is extracted for this, and `CORPUS_WIDE_PROVENANCE`
    is data so each field can be dropped from the guard one at a time.
    """

    #: A previous manifest carrying the records a scope must not touch. The
    #: attestation is D-84's, which `227` ruled immutable in terms.
    ATTESTATION = {
        "commit": "85ab14352677093e24038d933cf1071e5b03431a",
        "run_id": "33544573991",
        "ruby_parity_runs": 45, "ruby_parity_assertions": 629,
    }

    def setUp(self):
        self.freeze = _load_freeze()
        self.runner = self.freeze.runner
        self.previous = {
            "spec_sha256": self.runner.sha256(
                REPO_ROOT / "verification" / "spec.json"),
            "provenance": {
                "active_seals": {"python-only": 23,
                                 "python-only:post-handoff": 31},
                "retired_seals": {"ruby": 29, "ruby-api": 2},
                "final_cross_language_attestation": dict(self.ATTESTATION),
                "attestation_note": "the final cross-language CI run "
                                    "validates its own ancestor commit; its "
                                    "immutable run identity is retained "
                                    "after product-Ruby retirement",
            },
            "scenarios": [],
        }
        self.frozen = [{"id": "a", "lane": "python", "files": [],
                        "baseline_sha256": {}}]

    def _assemble(self, *, carried=True, **overrides):
        def fail(message):
            raise AssertionError(message)

        kwargs = {
            "frozen": self.frozen,
            "previous": self.previous,
            "carried": [{"id": "b"}] if carried else [],
            "this_producer": {"openstudio_cli": "3.11.0",
                              "producer": "P1"},
            # `.get` because one case deliberately has an EMPTY prior
            # provenance — a first freeze of a fresh corpus — and the
            # defaults must not assume there was something before.
            "active_seals": dict(
                self.previous["provenance"].get("active_seals") or {}),
            "retired_seals": dict(
                self.previous["provenance"].get("retired_seals") or {}),
            "final_attestation": dict(self.ATTESTATION),
            "dirty": "", "commit": "deadbeef",
            "runner": self.runner, "fail": fail,
        }
        kwargs.update(overrides)
        return self.freeze.assemble_manifest(**kwargs)

    def test_a_scope_that_keeps_everything_is_accepted(self):
        """The control. Without it, "refuse always" passes every test below."""
        manifest = self._assemble()
        provenance = manifest["provenance"]
        self.assertEqual(self.ATTESTATION,
                         provenance["final_cross_language_attestation"])
        self.assertEqual({"python-only": 23,
                          "python-only:post-handoff": 31},
                         provenance["active_seals"])
        self.assertEqual({"ruby": 29, "ruby-api": 2},
                         provenance["retired_seals"])
        self.assertEqual(self.previous["spec_sha256"],
                         manifest["spec_sha256"])
        self.assertEqual("P1", provenance["producer"])
        self.assertIn("this invocation only", provenance["producer_scope"],
                      "the global block must say it speaks for this "
                      "invocation and point at the per-scenario field")

    def test_each_CORPUS_WIDE_field_is_refused_when_a_scope_moves_it(self):
        """One case per guarded field, so none can be dropped unnoticed."""
        moved = {
            "active_seals": {"active_seals": {"python-only": 1}},
            "retired_seals": {"retired_seals": {}},
            "final_cross_language_attestation": {
                "final_attestation": {"commit": "0" * 40, "run_id": "1"}},
        }
        for field, override in moved.items():
            with self.subTest(field=field):
                self.assertIn(field, self.freeze.CORPUS_WIDE_PROVENANCE,
                              f"{field} must be in the guarded set")
                with self.assertRaises(AssertionError) as caught:
                    self._assemble(**override)
                self.assertIn(field, str(caught.exception))
                self.assertIn("refusing to promote", str(caught.exception))

    def test_a_moved_attestation_NOTE_is_refused_too(self):
        """The fourth guarded field, which had no case until it was measured.

        `attestation_note` is a literal in `assemble_manifest`, so a scope
        cannot move it by passing a different value — which is why it needed
        a different shape of case. What CAN move is the previous manifest's
        copy: if the note's wording is edited in the source, a scoped freeze
        would rewrite the committed record silently.

        Dropping it from `CORPUS_WIDE_PROVENANCE` left all 21 tests green,
        which is the same hole Sol found for the attestation itself one
        field over.
        """
        self.previous["provenance"]["attestation_note"] = (
            "an older wording of the same record")
        with self.assertRaises(AssertionError) as caught:
            self._assemble()
        self.assertIn("attestation_note", str(caught.exception))
        self.assertIn("refusing to promote", str(caught.exception))

    def test_the_D_84_attestation_is_refused_by_NAME(self):
        """D-84's record is the one `227` ruled immutable in terms.

        This is the field whose guard `233` removed with no test noticing.
        """
        with self.assertRaises(AssertionError) as caught:
            self._assemble(final_attestation={"commit": "0" * 40})
        message = str(caught.exception)
        self.assertIn("final_cross_language_attestation", message)
        self.assertIn("IMMUTABLE", message,
                      "the refusal must say WHY, or a maintainer reads it as "
                      "a stale-cache problem and re-runs the freeze")

    def test_a_moved_spec_sha256_refuses_a_scope(self):
        """The comparison rules moved, so no scope can establish the rest."""
        self.previous["spec_sha256"] = "0" * 64
        with self.assertRaises(AssertionError) as caught:
            self._assemble()
        self.assertIn("spec_sha256", str(caught.exception))
        self.assertIn("run a full freeze", str(caught.exception))

    def test_a_FULL_freeze_may_RE_SEAL_but_not_mint_an_attestation(self):
        """The guard is for a SCOPE — except the immutable half, which is not.

        My first version of this control asserted that a full freeze may
        replace `final_cross_language_attestation` with
        `{"commit": "1"*40, "run_id": "2"}`. That CONTRADICTS the decision it
        was written to respect: D-84's attestation names a specific commit
        and CI run, D-103 keeps it, and it may be neither reduced nor
        recreated. A full freeze owns the corpus; it does not get to mint a
        cross-language attestation that no cross-language run produced.

        Sol's `237` found the same gap in the wiring, not only in the
        description: mutating what `main()` passes as `final_attestation`
        passed 30 tests across every scoped-freeze test, the seal-transition
        suite and manifest integrity.
        """
        # Seals MAY move on a full freeze: the corpus changed, so the tally
        # changing is a real result.
        manifest = self._assemble(carried=False,
                                  active_seals={"python-only": 99})
        self.assertEqual({"python-only": 99},
                         manifest["provenance"]["active_seals"],
                         "a full freeze owns the whole corpus, so a changed "
                         "seal tally is a legitimate outcome")

        # The ATTESTATION may not, on any path.
        with self.assertRaises(AssertionError) as caught:
            self._assemble(carried=False,
                           final_attestation={"commit": "1" * 40,
                                              "run_id": "2"})
        message = str(caught.exception)
        self.assertIn("final_cross_language_attestation", message)
        self.assertIn("IMMUTABLE", message)
        self.assertIn("D-84", message,
                      "the refusal must name the decision, or a maintainer "
                      "reads it as a stale-cache problem and re-runs")

    def test_the_immutable_guard_applies_to_a_SCOPE_as_well(self):
        """Both paths, so neither can be the only one wired."""
        with self.assertRaises(AssertionError) as caught:
            self._assemble(carried=True,
                           final_attestation={"commit": "2" * 40})
        self.assertIn("IMMUTABLE", str(caught.exception))

    def test_an_absent_prior_manifest_is_not_an_attestation_violation(self):
        """A first freeze has nothing to preserve, and must not be refused.

        Without this, guarding unconditionally would make the very first
        freeze of a fresh corpus impossible — the mirror of the defect
        above.
        """
        spec = self.previous["spec_sha256"]
        seals = dict(self.previous["provenance"]["active_seals"])
        retired = dict(self.previous["provenance"]["retired_seals"])
        self.previous = {"spec_sha256": spec, "provenance": {},
                         "scenarios": []}
        manifest = self._assemble(carried=False,
                                  active_seals=seals,
                                  retired_seals=retired,
                                  final_attestation={"commit": "3" * 40})
        self.assertEqual(
            {"commit": "3" * 40},
            manifest["provenance"]["final_cross_language_attestation"],
            "there was no prior attestation to contradict")


class TestTheFullFreezePathREACHESAssembly(unittest.TestCase):
    """`main()` with no `--scenario`, driven with no engine.

    `previous` was assigned only inside the `--scenario` branch and passed
    unconditionally to both helpers, so an ordinary FULL freeze died at
    promotion assembly — `UnboundLocalError: cannot access local variable
    'previous'` — AFTER every expensive run (Sol, `237`).

    My `test_a_FULL_freeze_may_...` control called `assemble_manifest()`
    directly with a synthetic `previous`, so it never executed the branch it
    claimed to control. Sol said plainly that a helper-only call does not
    close this, and he was right: the helpers were fine and the call site
    was broken.

    This drives `main()` itself. The engine is never reached because the
    scenario set is empty; what is under test is the ORCHESTRATION between
    argument parsing and promotion.
    """

    def _main_with_no_scenarios(self, argv):
        freeze = _load_freeze()
        freeze.scenario_defs.all_scenarios = lambda *a, **k: []
        freeze.producer_identity = lambda *a, **k: {
            "openstudio_cli": "3.11.0", "producer": "test"}
        # The attestation must be the COMMITTED one. Returning `None`
        # here made the immutable guard fire — correctly, since erasing
        # D-84's record is exactly what it exists to stop — and the run
        # never reached promotion. A stub that trips a guard under test
        # measures the stub.
        committed = json.loads(
            freeze.runner.MANIFEST.read_text(encoding="utf-8"))
        attestation = committed["provenance"].get(
            "final_cross_language_attestation")
        freeze.seal_accounting = lambda *a, **k: (
            committed["provenance"]["active_seals"],
            committed["provenance"]["retired_seals"],
            attestation)
        with mock.patch.object(sys, "argv", ["freeze.py", *argv]):
            try:
                freeze.main()
            except SystemExit as exit_code:
                return "exit", str(exit_code)
            except Exception as error:                        # noqa: BLE001
                return type(error).__name__, str(error)
        return "returned", ""

    def test_the_full_path_REACHES_publication_with_previous_in_hand(self):
        """The regression, through one in-memory environment seam.

        Earlier versions accepted every failure except `UnboundLocalError`,
        then expected a particular missing directory. The latter passed
        locally and failed on the bare runner because an inline
        `subprocess.run(["openstudio", ...])` reached a different missing
        thing first. Neither outcome proved the orchestration.

        Publication is the step after both assembly helpers. Reaching this
        sentinel with their manifest proves `previous` made it through the
        real `main()` call site. Supplying the external environment in
        memory makes that witness independent of OpenStudio, Git and disk.
        """
        class ReachedPublication(Exception):
            """Raised by the in-memory publisher."""

        freeze = _load_freeze()
        freeze.scenario_defs.all_scenarios = lambda *a, **k: []
        attestation = {
            "commit": "8" * 40,
            "run_id": 33544573991,
            "run_url": "https://example.invalid/runs/33544573991",
        }
        freeze.seal_accounting = lambda *a, **k: (
            {"python-only:post-handoff": 0, "python-only": 0},
            {"ruby": 0, "ruby-api": 0},
            attestation)
        captured = {}

        def sentinel(manifest, baselines):
            captured["manifest"] = manifest
            captured["baselines"] = baselines
            raise ReachedPublication

        environment = {
            "dirty": False,
            "commit": "9" * 40,
            "slugs": [],
            "previous": {
                "scenarios": [],
                "provenance": {
                    "final_cross_language_attestation": attestation,
                },
            },
            "producer": lambda: {
                "openstudio_cli": "3.11.0",
                "producer": {"openstudio": "3.11.0"},
            },
            "spec_sha256": "a" * 64,
            "sample_manifest_sha256": "b" * 64,
            "publish": sentinel,
        }
        external = AssertionError("the in-memory witness touched the host")
        with mock.patch.object(sys, "argv", ["freeze.py"]), \
                mock.patch.object(freeze, "git", side_effect=external), \
                mock.patch.object(freeze.subprocess, "run",
                                  side_effect=external), \
                mock.patch.object(freeze.tempfile, "mkdtemp",
                                  side_effect=external), \
                mock.patch.object(freeze.runner, "sha256",
                                  side_effect=external), \
                mock.patch.object(pathlib.Path, "read_text",
                                  side_effect=external), \
                mock.patch.object(pathlib.Path, "write_text",
                                  side_effect=external), \
                mock.patch.object(pathlib.Path, "mkdir",
                                  side_effect=external):
            with self.assertRaises(ReachedPublication):
                freeze.main(environment=environment)

        self.assertIsNone(
            captured["baselines"],
            "an empty in-memory run must not allocate a staging tree")
        self.assertEqual([], captured["manifest"]["scenarios"])
        self.assertEqual(
            attestation,
            captured["manifest"]["provenance"]
            ["final_cross_language_attestation"],
            "the immutable D-84 record must survive main-to-manifest wiring")

    def test_a_SCOPED_run_still_refuses_without_a_manifest_to_carry(self):
        """The counterweight: initialising `previous` must not weaken this.

        A scope needs a prior manifest BY DEFINITION — it carries baselines
        forward from it. Giving the full path a neutral empty prior must not
        make a scope accept one.
        """
        freeze = _load_freeze()
        if not freeze.runner.MANIFEST.is_file():
            self.skipTest("this repository has a committed manifest")
        kind, message = self._main_with_no_scenarios(
            ["--allow-dirty", "--scenario", "no-such-scenario-id"])
        self.assertEqual("exit", kind,
                         "an unknown scenario id must be refused")
        self.assertIn("no such scenario", message.lower())
