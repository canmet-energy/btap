"""Every CI job that runs the frozen-scenario modules checks out a FULL clone.

`test_manifest_integrity` proves the frozen manifest's provenance commit is an
ancestor of HEAD. A shallow clone cannot answer that and does not say so: git
returns 1 — the same code as a genuine "no" — for a commit present but beyond
the graft boundary. The test's recovery is to deepen the clone, and two
modules deepening one `.git` concurrently is issue #99.

`fetch-depth: 0` removes the whole class by never entering that path. The
reason this is a TEST and not just a setting is that I set it on the `python`
job only, and the `verify` job then failed with the identical message —
"these baselines came from another line of history" — on run 38150608891. The
fix was right and its coverage was not, and nothing checked the coverage.

So the property is: for each workflow job, if it runs a test command that can
reach these modules, its checkout step sets `fetch-depth: 0`. Jobs that do not
run them are unconstrained, which is why `lint` is not listed here — adding a
full clone where nothing needs one is cost for no property.
"""
import pathlib
import re
import unittest

WORKFLOWS = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows"
MAIN = WORKFLOWS / "test.yml"

#: The modules carrying the manifest-ancestry check.
SCENARIO_MODULES = ("test_frozen_scenarios", "test_freeze_producer")

#: A command reaches those modules when it NAMES one, or when its pytest
#: target is the whole `tests` tree. `tests/` as a bare substring is too loose
#: and matched `lint`, whose only hit is `pytest -q
#: tests/test_coverage_code_refs.py` — one unrelated file. Requiring the path
#: to END at `tests` is what distinguishes "the tree" from "a file in it";
#: narrowing the rule is right, and excluding `lint` by name would have been a
#: confession that the rule was wrong.
#: The freeze script's own path is NOT a token here. It would be a cross-tree
#: reference from `python/tests/`, which `test_self_containment.py` forbids,
#: and it changes the detected set for no job — so the dependency is removed
#: rather than allowlisted, which is the first of the two fixes that gate's
#: own failure message offers.
REACHES_RE = re.compile(
    r"|".join([*(re.escape(m) for m in SCENARIO_MODULES),
               r"(?<![\w/-])tests/?(?=\s|$)"]))


def _yaml():
    try:
        import yaml
    except ImportError:                                   # pragma: no cover
        raise unittest.SkipTest(
            "pyyaml is not installed in this environment") from None
    return yaml.safe_load(MAIN.read_text(encoding="utf-8"))


class TestScenarioJobsHaveFullClones(unittest.TestCase):
    def setUp(self):
        if not MAIN.is_file():
            self.skipTest(f"{MAIN} is not present in this layout")
        self.jobs = _yaml()["jobs"]

    def _runs_scenarios(self, job):
        text = "\n".join(
            str(step.get("run") or "") for step in job.get("steps", [])
            if isinstance(step, dict))
        return bool(REACHES_RE.search(text))

    def _fetch_depth(self, job):
        for step in job.get("steps", []):
            if isinstance(step, dict) and "checkout" in str(step.get("uses", "")):
                return (step.get("with") or {}).get("fetch-depth", "UNSET")
        return "NO CHECKOUT"

    def test_every_job_that_can_reach_the_modules_has_fetch_depth_zero(self):
        checked = []
        for name, job in sorted(self.jobs.items()):
            if not self._runs_scenarios(job):
                continue
            checked.append(name)
            with self.subTest(job=name):
                self.assertEqual(
                    0, self._fetch_depth(job),
                    f"job `{name}` runs the frozen-scenario modules, so its "
                    "checkout must set `fetch-depth: 0` — a shallow clone "
                    "cannot answer the manifest-ancestry check and recovers "
                    "by deepening, which races under xdist (issue #99)")
        # The jobs are NAMED, not counted. A count tolerates the detection
        # drifting onto a different set of the same size, and `parity` is the
        # case that matters: it bundles the oracle and runs Leg C, reaches no
        # scenario module, and therefore carries no full clone — adding one
        # where nothing needs it is cost for no property.
        self.assertEqual(
            ["parity-scenarios", "python", "verify"], sorted(checked),
            "exactly these jobs run the frozen-scenario modules. If this "
            f"found {sorted(checked)} instead, either a job's commands "
            "changed or the detection stopped matching — and a detection "
            "that matches nothing makes the subtests above vacuous")

    def test_the_detection_itself_finds_a_job_that_runs_them(self):
        """The control: a synthetic job that runs the modules on a shallow
        clone must be detected and must fail the property, so a silent
        change in how jobs declare their commands cannot make the test above
        vacuous."""
        shallow = {"steps": [{"uses": "actions/checkout@v5"},
                             {"run": "pytest tests/necb/test_frozen_scenarios.py"}]}
        self.assertTrue(self._runs_scenarios(shallow))
        self.assertEqual("UNSET", self._fetch_depth(shallow))

        unrelated = {"steps": [{"uses": "actions/checkout@v5"},
                               {"run": "ruff check ."}]}
        self.assertFalse(
            self._runs_scenarios(unrelated),
            "a job that does not run them must not be constrained")


if __name__ == "__main__":
    unittest.main()
