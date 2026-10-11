"""Every CI job that runs the frozen-scenario modules checks out a FULL clone.

`test_manifest_integrity` proves the frozen manifest's provenance commit is an
ancestor of HEAD. A shallow clone cannot answer that and does not say so: git
returns 1 — the same code as a genuine "no" — for a commit present but beyond
the graft boundary. Its recovery is to deepen the clone, and two modules
deepening one `.git` concurrently is issue #99.

This is a TEST and not just a setting because I set `fetch-depth: 0` on the
`python` job only, and `verify` then failed with the identical message —
"these baselines came from another line of history" — on run 38150608891. The
fix was right and its coverage was not, and nothing checked the coverage.

## Why this is a DECLARATION and not an inference

I tried to infer it from each job's shell commands and the attempt was wrong
three different ways: `pip install -q pytest` is not a test run; `python3 -m
unittest tests.necb.test_x` names dotted modules a `.py` matcher cannot see;
and `-m` means a marker expression to pytest but a module to python. Deciding
"can this shell command reach that test module" is not statically decidable,
and a rule that fails closed on everything it does not understand demands full
clones for jobs that do not need them — which is cost for no property, and an
assertion that will be weakened the first time it is inconvenient.

So the mapping is DECLARED below, one line per job with its reason, and the
test's job is to make sure nobody adds or changes a job without deciding:

- every job in the workflow must appear in the table, and
- every job declared as running the modules must have `fetch-depth: 0`, and
- no job declared as not running them may carry one.

A new job fails this test until someone writes down which it is. That is the
property worth having; "my regex understood the shell" is not.

Stdlib only, no `yaml`: the previous version imported PyYAML, which is in no
CI install line and required-by nothing we install, so it skipped in BOTH jobs
and reported `OK (skipped=2)` — a vacuous green guarding nothing (Fable,
`214`). The sibling `test_decisions_gate_is_path_unfiltered.py` scans text for
exactly this reason.
"""
import pathlib
import re
import unittest

WORKFLOWS = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows"
MAIN = WORKFLOWS / "test.yml"

#: Per job: does it run `test_frozen_scenarios` / `test_freeze_producer`, and
#: why. Verified by reading each job's steps, not inferred from them.
RUNS_SCENARIO_MODULES = {
    "python": (True, "runs the whole `tests/` tree under `-n auto`, which is "
                     "both modules"),
    "verify": (True, "runs the SDK/EnergyPlus suite plus the sizing-lane "
                     "frozen scenarios in one parallel pytest run"),
    "parity-scenarios": (True, "runs `test_frozen_scenarios` by name for the "
                               "annual parity lane"),
    "parity": (False, "bundles the oracle, runs the SmallOffice gate, Live "
                      "Leg C and the golden export; its only pytest target "
                      "is `test_legacy_archetype_e2e.py`"),
    "lint": (False, "stdlib checks, the decisions registry by dotted module "
                    "name, and `tests/test_coverage_code_refs.py`"),
    "main-red": (False, "an incident lifecycle: `gh` calls only, and it does "
                        "not check the repository out at all"),
}

#: Jobs that legitimately have no checkout step.
NO_CHECKOUT_EXPECTED = ("main-red",)

COMMENT_RE = re.compile(r"(?m)^\s*#.*$|(?<=\s)#.*$")


def parse_checkouts(text):
    """`{job: fetch-depth}` by indentation, where the value is the checkout
    step's setting, `"UNSET"`, or `"NO CHECKOUT"`.

    Only the checkout step is parsed, because a `with:` block under a `uses:`
    is unambiguous — unlike shell.
    """
    lines = COMMENT_RE.sub("", text).split("\n")
    jobs, job, step, in_jobs = {}, None, None, False

    def close():
        if job and step and step.get("checkout"):
            jobs[job] = step.get("fetch_depth", "UNSET")

    for line in lines:
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        header = re.match(r"^  ([A-Za-z][\w-]*):\s*$", line)
        if header:
            close()
            job, step = header.group(1), None
            jobs.setdefault(job, "NO CHECKOUT")
            continue
        if job is None:
            continue
        if re.match(r"^      - ", line):
            close()
            step = {}
        if step is None:
            continue
        if "uses:" in line and "checkout" in line:
            step["checkout"] = True
        depth = re.search(r"fetch-depth:\s*(\S+)", line)
        if depth:
            step["fetch_depth"] = depth.group(1)
    close()
    return jobs


class TestScenarioJobsHaveFullClones(unittest.TestCase):
    def setUp(self):
        if not MAIN.is_file():
            self.skipTest(f"{MAIN} is not present in this layout")
        self.checkouts = parse_checkouts(MAIN.read_text(encoding="utf-8"))

    def test_the_table_covers_exactly_the_jobs_in_the_workflow(self):
        """A job added or renamed fails here until someone decides."""
        self.assertEqual(
            sorted(RUNS_SCENARIO_MODULES), sorted(self.checkouts),
            "the declaration above and the workflow disagree about which "
            "jobs exist. Add the new job with (True, reason) if it can run "
            "the frozen-scenario modules and (False, reason) if it cannot — "
            "an undeclared job is an undecided one")

    def test_the_parser_is_not_vacuous(self):
        self.assertGreaterEqual(
            len(self.checkouts), 5,
            f"parsed only {sorted(self.checkouts)}; the workflow's shape "
            "changed and every assertion here is passing over nothing")
        for job, depth in sorted(self.checkouts.items()):
            if job in NO_CHECKOUT_EXPECTED:
                continue
            with self.subTest(job=job):
                self.assertNotEqual(
                    "NO CHECKOUT", depth,
                    f"job `{job}` parsed with no checkout step; it has one, "
                    "so the parser lost its steps")

    def test_every_job_that_runs_them_has_fetch_depth_zero(self):
        for job, (runs, why) in sorted(RUNS_SCENARIO_MODULES.items()):
            if not runs:
                continue
            with self.subTest(job=job):
                self.assertEqual(
                    "0", str(self.checkouts.get(job)),
                    f"job `{job}` runs the frozen-scenario modules ({why}), "
                    "so its checkout must set `fetch-depth: 0` — a shallow "
                    "clone cannot answer the manifest-ancestry check and "
                    "recovers by deepening it, which races under xdist "
                    "(issue #99)")

    def test_no_job_that_does_NOT_run_them_carries_a_full_clone(self):
        """The other direction, so the setting stays tied to a reason.

        `parity` is the case: a full clone where nothing needs one is cost for
        no property, and I had added it there before checking.
        """
        for job, (runs, why) in sorted(RUNS_SCENARIO_MODULES.items()):
            if runs or job in NO_CHECKOUT_EXPECTED:
                continue
            with self.subTest(job=job):
                self.assertNotEqual(
                    "0", str(self.checkouts.get(job)),
                    f"job `{job}` does not run the frozen-scenario modules "
                    f"({why}), so a full clone there buys nothing. If that "
                    "changed, flip its entry in the declaration instead of "
                    "leaving the two out of step")

    def test_the_parser_reads_the_right_step(self):
        synthetic = (
            "jobs:\n"
            "  shallow:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v5\n"
            "      - name: run\n"
            "        run: pytest tests/\n"
            "  deep:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v5\n"
            "        with:\n"
            "          fetch-depth: 0\n"
            "      - run: pytest tests/\n"
            "  decoy:\n"
            "    steps:\n"
            "      - uses: actions/setup-python@v6\n"
            "        with:\n"
            "          fetch-depth: 0\n"
        )
        parsed = parse_checkouts(synthetic)
        self.assertEqual("UNSET", parsed["shallow"])
        self.assertEqual("0", parsed["deep"])
        self.assertEqual(
            "NO CHECKOUT", parsed["decoy"],
            "a `fetch-depth` under a step that is NOT a checkout must not be "
            "read as one")


if __name__ == "__main__":
    unittest.main()
