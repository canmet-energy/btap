"""`runner.compare()`'s contract, class by class, each negatively pinned.

`test_comparator_contract.py` covers `verification/compare_runs.py`, the JSON
differ. The deleted `runner_sha256` also covered
`verification/scenarios/runner.py`, whose `compare()` owns the SCENARIO-level
contracts — exit status, streams, stream fragments, the run-dir file
inventory, text artifacts, byte assertions, worker failure, and the authored
`asserts` block. None of those was pinned, and Sol (`228`) showed what that
costs:

    -  if scenario.get("expect_exit") is not None and run.exit_code != ...
    +  if False and scenario.get("expect_exit") is not None and ...

With that installed, the comparator-contract module, `test_manifest_integrity`
and `test_scoped_freeze` all stayed green — and so did the WHOLE Python frozen
lane, all 23 scenarios, in 154 seconds. Matching live outputs cannot show that
a comparator still rejects a mismatch, which is the same reason a baseline run
is not a mutation test.

So this file calls the real `compare()` on synthetic baselines and synthetic
`ScenarioRun` values. Each case states, by hand, a scenario contract and a run
that VIOLATES it, and asserts `compare()` reports a problem — plus a matching
run that satisfies it, so no case passes merely because `compare()` complains
about everything.

`MUTATIONS` then disables one comparator clause at a time and asserts exactly
which cases stop noticing. A clause no case defends is a clause the hashes
were the only thing protecting.
"""
import importlib.util
import pathlib
import shutil
import sys
import tempfile
import unittest
from dataclasses import dataclass, field

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCENARIOS_DIR = REPO_ROOT / "verification" / "scenarios"
SPEC_PATH = REPO_ROOT / "verification" / "spec.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _runner():
    return _load("scenario_runner_contract", SCENARIOS_DIR / "runner.py")


@dataclass
class Case:
    """One scenario contract, a run that breaks it, and one that does not."""

    name: str
    scenario: dict
    bad_run: dict
    good_run: dict
    #: Files to write into the synthetic BASELINE directory.
    baseline: dict = field(default_factory=dict)
    #: Files to write into the synthetic RUN directory.
    bad_files: dict = field(default_factory=dict)
    good_files: dict = field(default_factory=dict)
    why: str = ""


def _scenario(**overrides):
    base = {"id": "synthetic", "lane": "python", "seal": "python-only"}
    base.update(overrides)
    return base


CASES = [
    Case(
        "exact exit status",
        _scenario(expect_exit=2),
        bad_run={"exit_code": 0}, good_run={"exit_code": 2},
        why="Sol's installed defect. A CLI that stops refusing bad usage "
            "exits 0 where the scenario froze 2, and nothing else in the "
            "suite notices"),
    Case(
        "a run dir expected to be EMPTY",
        _scenario(no_run_dir=True),
        bad_run={}, good_run={},
        bad_files={"report.json": "{}"}, good_files={},
        why="a scenario that must emit nothing, emitting something"),
    Case(
        "the run-dir file inventory, extras",
        _scenario(files=["report.json"]),
        bad_run={}, good_run={},
        baseline={"report.json": '{"a": 1}'},
        bad_files={"report.json": '{"a": 1}', "surprise.json": "{}"},
        good_files={"report.json": '{"a": 1}'},
        why="freeze what you emit: an undeclared artifact is a changed "
            "output"),
    Case(
        "the run-dir file inventory, absences",
        _scenario(files=["report.json"], expected_run_files=["report.json",
                                                             "audit.json"]),
        bad_run={}, good_run={},
        baseline={"report.json": "{}", "audit.json": "[]"},
        bad_files={"report.json": "{}"},
        good_files={"report.json": "{}", "audit.json": "[]"},
        why="a declared artifact that stopped being produced"),
    Case(
        "a JSON file's contents",
        _scenario(files=["report.json"]),
        bad_run={}, good_run={},
        baseline={"report.json": '{"compliant": true}'},
        bad_files={"report.json": '{"compliant": false}'},
        good_files={"report.json": '{"compliant": true}'},
        why="the verdict moving — this one routes into compare_runs, and it "
            "is here because `compare()` is what wires it up"),
    Case(
        "an EXACT text artifact",
        _scenario(text_files={"audit.txt": "exact"}),
        bad_run={}, good_run={},
        baseline={"audit.txt": "line one\nline two\n"},
        bad_files={"audit.txt": "line one\nline TWO\n"},
        good_files={"audit.txt": "line one\nline two\n"},
        why="audit text is case-sensitive and the words are the claim"),
    Case(
        "a text artifact missing on the live side",
        _scenario(text_files={"audit.txt": "exact"}),
        bad_run={}, good_run={},
        baseline={"audit.txt": "x\n"},
        bad_files={}, good_files={"audit.txt": "x\n"},
        why="an artifact that stopped being written at all"),
    Case(
        "an EXACT stream",
        _scenario(streams={"stdout": "exact"}),
        bad_run={"stdout": "VERDICT: not compliant\n"},
        good_run={"stdout": "VERDICT: compliant\n"},
        baseline={"stdout.txt": "VERDICT: compliant\n"},
        why="the CLI's own verdict line"),
    Case(
        "a REQUIRED stream fragment",
        _scenario(fragments={"stdout": {"required": ["conditional"]}}),
        bad_run={"stdout": "VERDICT: compliant\n"},
        good_run={"stdout": "VERDICT: conditional\n"},
        why="a conditional determination that stopped being announced"),
    Case(
        "a FORBIDDEN stream fragment",
        _scenario(fragments={"stderr": {"forbidden": ["Traceback"]}}),
        bad_run={"stderr": "Traceback (most recent call last):\n"},
        good_run={"stderr": ""},
        why="a crash surfacing in a run that is supposed to be clean"),
    Case(
        "a required fragment in a FILE",
        _scenario(fragments={"audit.txt": {"required": ["AHJ-21"]}}),
        bad_run={}, good_run={},
        bad_files={"audit.txt": "no citation here\n"},
        good_files={"audit.txt": "... | AHJ AHJ-21\n"},
        why="a citation axis that stopped reaching the audit"),
    Case(
        "a byte assertion",
        _scenario(byte_asserts=[{"file": "verdict.txt", "equals": "PASS"}]),
        bad_run={}, good_run={},
        bad_files={"verdict.txt": "FAIL"},
        good_files={"verdict.txt": "PASS"},
        why="an exact-bytes contract on a small artifact"),
    Case(
        "an API worker that failed",
        _scenario(),
        bad_run={"observations": {"error": "worker timed out after 5400s"}},
        good_run={"observations": {"compliant": True}},
        why="with `expect_exit` None, this is what keeps a DEAD run from "
            "reading as a pass"),
    Case(
        "an authored structured assertion",
        # NO `files` entry, deliberately. With one, the JSON differ also
        # catches this and the case stops being about the `asserts` block —
        # the mutation that disables assertions then blinds nothing, which
        # is exactly what the meta-test reported.
        _scenario(asserts=[{"op": "json_gt", "file": "report.json",
                            "path": "proposed.total_site_kwh", "value": 0}]),
        bad_run={}, good_run={},
        bad_files={"report.json": '{"proposed": {"total_site_kwh": 0.0}}'},
        good_files={"report.json": '{"proposed": {"total_site_kwh": 1.0}}'},
        why="the `asserts` block, which freeze.py also runs — so an "
            "assertion cannot be a freeze-time-only guarantee"),
]


@dataclass
class Mutation:
    name: str
    old: str
    new: str
    must_stop_noticing: frozenset


MUTATIONS = [
    Mutation(
        "exit status not compared (Sol's installed defect)",
        'if scenario.get("expect_exit") is not None and run.exit_code != scenario["expect_exit"]:',
        'if False and scenario.get("expect_exit") is not None and run.exit_code != scenario["expect_exit"]:',
        frozenset({"exact exit status"})),
    Mutation(
        "an empty run dir not checked",
        'if run_dir and run_dir.exists() and any(run_dir.iterdir()):',
        'if False and run_dir and run_dir.exists() and any(run_dir.iterdir()):',
        frozenset({"a run dir expected to be EMPTY"})),
    Mutation(
        "the file inventory not compared",
        "            if actual != expected:",
        "            if False:",
        frozenset({"the run-dir file inventory, extras",
                   "the run-dir file inventory, absences"})),
    Mutation(
        "text artifacts not compared",
        "        if baseline_n != live_n:",
        "        if False:",
        frozenset({"an EXACT text artifact"})),
    # NOT in this table: disabling the None guard
    # (`if baseline is None or live is None:`) makes `compare()` RAISE rather
    # than go quiet, and a raise is a loud failure. The guard converts a
    # crash into a named problem; it is not what stands between a missing
    # artifact and a green run. Claiming it blinds a case would be claiming
    # a mutation I cannot demonstrate.
    Mutation(
        "exact streams not compared",
        'if frozen.read_text(encoding="utf-8") != normalize(live, run.run_dir or "<none>", run.scratch):',
        'if False and frozen.read_text(encoding="utf-8") != normalize(live, run.run_dir or "<none>", run.scratch):',
        frozenset({"an EXACT stream"})),
    Mutation(
        "required stream fragments not checked",
        "            if needle not in live:",
        "            if False:",
        frozenset({"a REQUIRED stream fragment"})),
    Mutation(
        "forbidden stream fragments not checked",
        "            if needle in live:",
        "            if False:",
        frozenset({"a FORBIDDEN stream fragment"})),
    Mutation(
        "required file fragments not checked",
        "            if needle not in content:",
        "            if False:",
        frozenset({"a required fragment in a FILE"})),
    Mutation(
        "byte assertions not checked",
        'if actual != assertion["equals"]:',
        'if False and actual != assertion["equals"]:',
        frozenset({"a byte assertion"})),
    Mutation(
        "a failed API worker not reported",
        'if isinstance(run.observations, dict) and "error" in run.observations:',
        'if False and isinstance(run.observations, dict) and "error" in run.observations:',
        frozenset({"an API worker that failed"})),
    Mutation(
        "authored assertions not run",
        "    problems.extend(check_assertions(scenario, run))",
        "    problems.extend([])",
        frozenset({"an authored structured assertion"})),
    Mutation(
        "the JSON differ not wired up",
        "        cr.compare_file(str(base), str(run.run_dir), name, spec, diffs)",
        "        diffs = diffs",
        frozenset({"a JSON file's contents"})),
]


class _Harness:
    """A synthetic baseline tree and run dir for one case."""

    def __init__(self, runner, case, which):
        self.runner = runner
        self.case = case
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="cmp-scn-"))
        self.baselines = self.root / "baselines"
        (self.baselines / case.scenario["id"]).mkdir(parents=True)
        for name, text in case.baseline.items():
            (self.baselines / case.scenario["id"] / name).write_text(
                text, encoding="utf-8")
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        files = case.bad_files if which == "bad" else case.good_files
        for name, text in files.items():
            (self.run_dir / name).write_text(text, encoding="utf-8")
        overrides = case.bad_run if which == "bad" else case.good_run
        self.run = runner.ScenarioRun(
            exit_code=overrides.get("exit_code", 0),
            stdout=overrides.get("stdout", ""),
            stderr=overrides.get("stderr", ""),
            run_dir=str(self.run_dir),
            scratch=str(self.root),
            observations=overrides.get("observations"))

    def problems(self):
        previous = self.runner.BASELINES
        self.runner.BASELINES = self.baselines
        try:
            cr = self.runner.load_compare_runs()
            spec = cr.load_spec(SPEC_PATH)
            return self.runner.compare(self.case.scenario, self.run, spec, cr)
        finally:
            self.runner.BASELINES = previous

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def _notices(runner, case):
    """Does `compare()` report the violation, and stay quiet on the good run?

    A RAISE counts as noticing. `compare()` throwing means the scenario
    fails, loudly, with a traceback naming the file — which is detection, not
    blindness. It matters for one clause in particular: disabling the
    `baseline is None or live is None` guard does not make a missing artifact
    pass, it makes `live.replace` raise `AttributeError`. The guard turns a
    crash into a named problem; it is not what stands between a missing file
    and a green run.
    """
    bad = _Harness(runner, case, "bad")
    good = _Harness(runner, case, "good")
    try:
        try:
            noticed = bool(bad.problems())
        except Exception:                                 # noqa: BLE001
            noticed = True
        try:
            complained = bool(good.problems())
        except Exception:                                 # noqa: BLE001
            complained = True
        return noticed, complained
    finally:
        bad.cleanup()
        good.cleanup()


class TestTheScenarioComparatorContract(unittest.TestCase):
    def setUp(self):
        self.runner = _runner()

    def test_the_case_table_covers_each_contract_once(self):
        names = [c.name for c in CASES]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(
            len(CASES), 14,
            "`compare()` owns nine classes of scenario contract; a table "
            "smaller than this is not covering them")

    def test_compare_REPORTS_each_violation_and_passes_each_good_run(self):
        for case in CASES:
            with self.subTest(case=case.name):
                noticed, complained = _notices(self.runner, case)
                self.assertTrue(
                    noticed,
                    f"{case.name}: `compare()` did not report the violation "
                    f"— {case.why}")
                self.assertFalse(
                    complained,
                    f"{case.name}: `compare()` reported a problem on the "
                    "SATISFYING run too, so the case above proves nothing")

    def test_each_mutation_stops_EXACTLY_its_named_cases_noticing(self):
        """The reason to believe this file.

        Each clause of `compare()` is disabled in turn and the table must
        stop noticing exactly the cases that clause defends. A clause no case
        defends is one the deleted machinery hashes were the only thing
        protecting.
        """
        source = (SCENARIOS_DIR / "runner.py").read_text(encoding="utf-8")
        for mutation in MUTATIONS:
            with self.subTest(mutation=mutation.name):
                self.assertEqual(
                    1, source.count(mutation.old),
                    f"the clause this mutation disables is not uniquely "
                    f"present in runner.py: {mutation.old[:60]!r}")
                patched = source.replace(mutation.old, mutation.new)
                work = pathlib.Path(tempfile.mkdtemp(prefix="cmp-mut-"))
                try:
                    # Mirror the tree SHAPE, not just the file: `runner.py`
                    # computes `REPO_ROOT` from its own location and loads
                    # `verification/compare_runs.py` and `spec.json`
                    # relative to it.
                    scenarios = work / "verification" / "scenarios"
                    scenarios.mkdir(parents=True)
                    for sibling in SCENARIOS_DIR.glob("*.py"):
                        shutil.copy2(sibling, scenarios / sibling.name)
                    shutil.copy2(REPO_ROOT / "verification"
                                 / "compare_runs.py",
                                 work / "verification" / "compare_runs.py")
                    shutil.copy2(SPEC_PATH, work / "verification"
                                 / "spec.json")
                    (scenarios / "runner.py").write_text(patched,
                                                         encoding="utf-8")
                    runner = _load("scenario_runner_mutated",
                                   scenarios / "runner.py")
                    blind = set()
                    for case in CASES:
                        noticed, _ = _notices(runner, case)
                        if not noticed:
                            blind.add(case.name)
                    self.assertEqual(
                        set(mutation.must_stop_noticing), blind,
                        f"disabling {mutation.name!r} was expected to blind "
                        f"{sorted(mutation.must_stop_noticing)} and blinded "
                        f"{sorted(blind)}")
                finally:
                    shutil.rmtree(work, ignore_errors=True)

    def test_every_case_is_defended_by_SOME_clause(self):
        """Every case must be blindable, except where a clause fails LOUDLY.

        The exemption is named, not subtracted quietly. Disabling the
        `baseline is None or live is None` guard makes `compare()` raise
        `AttributeError` on `live.replace` rather than return no problems —
        so that clause cannot be shown to BLIND anything, because a raise is
        a failure the harness sees. The guard converts a crash into a named
        problem; it is not what stands between a missing artifact and a
        green run.
        """
        exempt = {
            "a text artifact missing on the live side":
                "its clause raises when disabled, which is detection, not "
                "blindness — see the note above MUTATIONS",
        }
        covered = set().union(*(m.must_stop_noticing for m in MUTATIONS))
        uncovered = sorted({c.name for c in CASES} - covered - set(exempt))
        self.assertEqual(
            [], uncovered,
            f"no mutation can blind these cases: {uncovered}. Either the "
            "clause they exercise is unreachable, or the case is not "
            "testing what its name says — and if the clause fails loudly "
            "instead, add it to `exempt` WITH the reason rather than "
            "dropping the case")
        for case_name in exempt:
            with self.subTest(exempt=case_name):
                self.assertIn(
                    case_name, {c.name for c in CASES},
                    "an exemption for a case that no longer exists is a "
                    "stale excuse; remove it")


if __name__ == "__main__":
    unittest.main()
