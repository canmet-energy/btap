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

## The classification is DECLARED, and PINNED to the commands it classifies

Inferring "can this shell command reach that test module" from each job's
`run:` text is not statically decidable, and my attempt was wrong three ways:
`pip install -q pytest` is not a test run; `python3 -m unittest
tests.necb.test_x` names dotted modules a `.py` matcher cannot see; and `-m`
is a marker expression to pytest but a module to python. It flagged `lint` and
`parity`, both of which are fine.

So each job's classification is authored below. But a declaration is only
worth anything if a command change forces it to be reconsidered, and the
first version did not look at the commands at all: Sol (`217`) changed
`parity`'s pytest target from one file to `tests/` — which reaches both
ancestry modules on a shallow checkout — and the guard still reported
`5 passed`. The statement that `parity` reaches nothing was assumed by the
test, not tested by it.

Each entry therefore carries a DIGEST of that job's normalised `run:` blocks.
Editing any command changes the digest and fails this file, which is the
re-adjudication: look at what changed, decide whether the classification still
holds, and update both. No shell is interpreted and nothing is guessed — the
test's claim is only ever "these commands were classified by a human", which
is a claim it can actually keep.

Stdlib only: the version before imported PyYAML, which is in no CI install
line and required-by nothing we install, so it skipped in BOTH jobs and
reported `OK (skipped=2)` — a vacuous green guarding nothing (Fable, `214`).
"""
import hashlib
import pathlib
import re
import unittest

WORKFLOWS = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows"
MAIN = WORKFLOWS / "test.yml"

#: The modules carrying the manifest-ancestry check.
SCENARIO_MODULES = ("test_frozen_scenarios", "test_freeze_producer")

#: Per job: does it run those modules, the sha256 prefix of its WHOLE body,
#: that body's line count, and why.
#:
#: The digest is what couples the judgement to the job. It covered only the
#: job's `run:` blocks at first, and that left two ways to change what a job
#: RUNS without moving it: `PYTEST_ADDOPTS: tests/` in a step or job `env:`,
#: and a different `container.image` (Fable, `219`). The whole body is the
#: job's definition, so the whole body is hashed — comments excepted, so
#: documentation can be corrected without re-adjudicating a classification.
#:
#: It is deliberately noisy: bumping an action version or adding a step also
#: fails this file. That is the intended cost, because the claim being kept
#: is "a human classified THIS job definition", and a job definition that has
#: changed has not been classified.
JOBS = {
    "python": {
        "runs_them": True,
        "digest": "b27bd30840e95e8b",
        "body_lines": 33,
        "why": "runs the whole `tests/` tree under `-n auto`, which is both "
               "modules",
    },
    "verify": {
        "runs_them": True,
        "digest": "799b7e6ddc27ed4c",
        "body_lines": 63,
        "why": "runs the SDK/EnergyPlus suite plus the sizing-lane frozen "
               "scenarios in one parallel pytest run",
    },
    "parity-scenarios": {
        "runs_them": True,
        "digest": "8ccd71ffd2396bd9",
        "body_lines": 24,
        "why": "runs `test_frozen_scenarios` by name for the annual parity "
               "lane",
    },
    "parity": {
        "runs_them": False,
        "digest": "57dd9e9a01790c6f",
        "body_lines": 51,
        "why": "bundles the oracle, runs the SmallOffice gate, Live Leg C and "
               "the golden export; its only pytest target is the single file "
               "`test_legacy_archetype_e2e.py`",
    },
    "lint": {
        "runs_them": False,
        "digest": "10d6d178b192175c",
        "body_lines": 31,
        "why": "stdlib checks, the decision and AHJ gates by dotted module "
               "name, and the single file `tests/test_coverage_code_refs.py`",
    },
    "main-red": {
        "runs_them": False,
        "digest": "afa9771f6944be9c",
        "body_lines": 62,
        "why": "an incident lifecycle: `gh` calls only, and it does not check "
               "the repository out at all",
    },
}

#: Jobs that legitimately have no checkout step.
NO_CHECKOUT_EXPECTED = ("main-red",)

COMMENT_RE = re.compile(r"(?m)^\s*#.*$|(?<=\s)#.*$")

#: GitHub job ids may start with a letter or `_`. Accepting only `[A-Za-z]`
#: let a valid `_scenario` job with a shallow checkout escape the inventory
#: entirely (Sol, `217`).
JOB_HEADER_RE = re.compile(r"^  ([A-Za-z_][\w-]*):\s*$")


def parse(text):
    """`{job: {"fetch_depth": value, "body": str}}`.

    Two surfaces, both unambiguous: a `with:` block under a `uses:` checkout,
    and the job's own text. No shell is interpreted and no command is
    classified here — the body is hashed whole and the judgement about it is
    authored above.
    """
    lines = COMMENT_RE.sub("", text).split("\n")
    jobs, job, step, in_jobs = {}, None, None, False
    bounds = {}

    def close():
        if job and step and step.get("checkout"):
            jobs[job]["fetch_depth"] = step.get("fetch_depth", "UNSET")

    for index, line in enumerate(lines):
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        header = JOB_HEADER_RE.match(line)
        if header:
            close()
            job, step = header.group(1), None
            jobs.setdefault(job, {"fetch_depth": "NO CHECKOUT", "body": ""})
            bounds[job] = index
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

    # Each job's body: its header through the line before the next header.
    order = sorted(bounds.items(), key=lambda kv: kv[1])
    for position, (name, first) in enumerate(order):
        last = (order[position + 1][1] if position + 1 < len(order)
                else len(lines))
        jobs[name]["body"] = "\n".join(
            line.rstrip() for line in lines[first:last] if line.strip())
    return jobs


def digest_of(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


class TestScenarioJobsHaveFullClones(unittest.TestCase):
    def setUp(self):
        if not MAIN.is_file():
            self.skipTest(f"{MAIN} is not present in this layout")
        self.jobs = parse(MAIN.read_text(encoding="utf-8"))

    def test_the_parser_is_not_vacuous(self):
        self.assertGreaterEqual(
            len(self.jobs), 6,
            f"parsed only {sorted(self.jobs)}; the workflow's shape changed "
            "and every assertion here is passing over nothing")
        for job, info in sorted(self.jobs.items()):
            with self.subTest(job=job):
                self.assertGreater(
                    len(info["body"].splitlines()), 10,
                    f"job `{job}` parsed with a {len(info['body'])}-character "
                    "body; no job in this workflow is that small, so the "
                    "parser lost its lines")
                if job not in NO_CHECKOUT_EXPECTED:
                    self.assertNotEqual(
                        "NO CHECKOUT", info["fetch_depth"],
                        f"job `{job}` parsed with no checkout step; it has "
                        "one, so the parser lost its steps")

    def test_the_declaration_covers_exactly_the_jobs_present(self):
        self.assertEqual(
            sorted(JOBS), sorted(self.jobs),
            "the declaration and the workflow disagree about which jobs "
            "exist. Add the new job with runs_them=True and its reason if it "
            "can run the frozen-scenario modules, False if it cannot — an "
            "undeclared job is an undecided one")

    def test_each_jobs_DEFINITION_is_the_one_that_was_classified(self):
        """The coupling. Without it the classification is an assumption.

        Sol (`217`) changed `parity`'s pytest target from one file to
        `tests/`, which reaches both ancestry modules on its shallow
        checkout, and the first version of this file still passed because it
        compared booleans against nothing. Hashing only the `run:` blocks
        then still left `PYTEST_ADDOPTS` in an `env:` and a changed
        `container.image` able to redirect a job silently (Fable, `219`).
        """
        for job, declared in sorted(JOBS.items()):
            with self.subTest(job=job):
                body = self.jobs[job]["body"]
                self.assertEqual(
                    declared["body_lines"], len(body.splitlines()),
                    f"job `{job}` is now {len(body.splitlines())} lines, not "
                    f"{declared['body_lines']}")
                self.assertEqual(
                    declared["digest"], digest_of(body),
                    f"job `{job}`'s DEFINITION has changed since someone "
                    f"classified it as runs_them={declared['runs_them']} "
                    f"({declared['why']}). Re-read them, decide whether that "
                    "still holds, and update `digest` — the point of the "
                    "digest is that a command edit cannot quietly invalidate "
                    "the judgement")

    def test_every_job_that_runs_them_has_fetch_depth_zero(self):
        for job, declared in sorted(JOBS.items()):
            if not declared["runs_them"]:
                continue
            with self.subTest(job=job):
                self.assertEqual(
                    "0", str(self.jobs[job]["fetch_depth"]),
                    f"job `{job}` runs the frozen-scenario modules "
                    f"({declared['why']}), so its checkout must set "
                    "`fetch-depth: 0` — a shallow clone cannot answer the "
                    "manifest-ancestry check and recovers by deepening it, "
                    "which races under xdist (issue #99)")

    def test_no_job_that_does_NOT_run_them_carries_a_full_clone(self):
        """The other direction, so the setting stays tied to a reason."""
        for job, declared in sorted(JOBS.items()):
            if declared["runs_them"] or job in NO_CHECKOUT_EXPECTED:
                continue
            with self.subTest(job=job):
                self.assertNotEqual(
                    "0", str(self.jobs[job]["fetch_depth"]),
                    f"job `{job}` does not run them ({declared['why']}), so "
                    "a full clone there buys nothing. If that changed, flip "
                    "its entry instead of leaving the two out of step")

    def test_a_job_id_starting_with_an_underscore_is_SEEN(self):
        """GitHub allows it, and accepting only `[A-Za-z]` let a valid
        `_scenario` job with a shallow checkout escape the inventory
        entirely (Sol, `217`)."""
        synthetic = (
            "jobs:\n"
            "  _scenario:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v5\n"
            "      - run: pytest tests/\n"
        )
        self.assertIn(
            "_scenario", parse(synthetic),
            "a job id may begin with an underscore; one that is not parsed "
            "is one the declaration cannot be checked against")

    def test_the_parser_reads_the_right_step_and_joins_block_scalars(self):
        synthetic = (
            "jobs:\n"
            "  shallow:\n"
            "    steps:\n"
            "      - uses: actions/checkout@v5\n"
            "      - name: run\n"
            "        run: |\n"
            "          pytest tests/ \\\n"
            "            --durations=15\n"
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
            "      - run: true\n"
        )
        parsed = parse(synthetic)
        self.assertEqual("UNSET", parsed["shallow"]["fetch_depth"])
        self.assertEqual("0", parsed["deep"]["fetch_depth"])
        self.assertEqual(
            "NO CHECKOUT", parsed["decoy"]["fetch_depth"],
            "a `fetch-depth` under a step that is NOT a checkout must not be "
            "read as one")
        # The body carries every line, so a continuation line or an `env:`
        # is inside the digest without the parser having to understand it.
        self.assertIn("--durations=15", parsed["shallow"]["body"],
                      "a block scalar's continuation lines are part of the "
                      "job body, so an edit on one moves the digest")
        self.assertIn("name: run", parsed["shallow"]["body"],
                      "and so is everything else the job declares")
        self.assertNotIn(
            "deep:", parsed["shallow"]["body"],
            "but a job's body must stop at the next job, or one job's edit "
            "would move another's digest")

    def test_an_env_that_REDIRECTS_a_run_moves_the_digest(self):
        """`PYTEST_ADDOPTS` changes what a command runs without touching it.

        Hashing only the `run:` blocks left this invisible, along with a
        changed `container.image` (Fable, `219`). Both live in the job body.
        """
        base = (
            "jobs:\n"
            "  j:\n"
            "    container:\n"
            "      image: ghcr.io/x/y:1\n"
            "    steps:\n"
            "      - uses: actions/checkout@v5\n"
            "      - run: pytest tests/test_one.py\n"
        )
        redirected = base.replace(
            "      - run: pytest tests/test_one.py\n",
            "      - env:\n"
            "          PYTEST_ADDOPTS: tests/\n"
            "        run: pytest tests/test_one.py\n")
        retagged = base.replace("ghcr.io/x/y:1", "ghcr.io/x/y:2")
        first = digest_of(parse(base)["j"]["body"])
        self.assertNotEqual(
            first, digest_of(parse(redirected)["j"]["body"]),
            "an `env:` that redirects pytest must move the digest")
        self.assertNotEqual(
            first, digest_of(parse(retagged)["j"]["body"]),
            "and so must a different container image")

    def test_a_COMMENT_does_not_move_the_digest(self):
        """So documentation can be corrected without re-adjudicating."""
        base = ("jobs:\n  j:\n    steps:\n"
                "      - uses: actions/checkout@v5\n"
                "      - run: pytest tests/\n")
        commented = ("jobs:\n  j:\n    steps:\n"
                     "      # why this job exists\n"
                     "      - uses: actions/checkout@v5\n"
                     "      - run: pytest tests/\n")
        self.assertEqual(
            digest_of(parse(base)["j"]["body"]),
            digest_of(parse(commented)["j"]["body"]),
            "a comment is not part of the definition being classified")


if __name__ == "__main__":
    unittest.main()
