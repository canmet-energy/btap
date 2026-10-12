"""The R4 frozen-scenario suite — Leg B's successor (D-80 R4).

Runs the manifest-declared scenarios for the selected lane(s) against the
frozen baselines under ``verification/scenarios/`` and asserts the
executed count equals the manifest's per-lane count (the live_leg_c
zero-vacuity pattern: green must mean "all of them ran and matched", never
"whatever was discovered passed").

Lanes: ``BTAP_SCENARIO_LANES`` (comma-separated; default ``python`` — the
engine-free lane that runs on every PR). ``BTAP_SCENARIOS_REQUIRED=1``
turns every missing prerequisite (manifest, baselines, engine) into a
FAILURE naming the remedy.
"""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT

SCENARIOS_DIR = REPO_ROOT / "verification" / "scenarios"

#: Keys `freeze.py` ADDS to an authored scenario definition. Everything else
#: in a manifest entry must equal what `scenario_defs.py` declares today.
GENERATED_SCENARIO_KEYS = frozenset({"baseline_sha256", "produced_by"})
LANES = tuple(os.environ.get("BTAP_SCENARIO_LANES", "python").split(","))
REQUIRED = os.environ.get("BTAP_SCENARIOS_REQUIRED") == "1"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFrozenScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest_path = SCENARIOS_DIR / "manifest.json"
        if not manifest_path.is_file():
            msg = ("verification/scenarios/manifest.json is missing — the "
                   "frozen suite has not been frozen yet (run "
                   "verification/scenarios/freeze.py)")
            if REQUIRED:
                raise AssertionError(msg)
            raise unittest.SkipTest(msg + " (BTAP_SCENARIOS_REQUIRED=1 "
                                    "makes this a failure)")
        cls.runner = _load("scenario_runner", SCENARIOS_DIR / "runner.py")
        cls.defs = _load("scenario_defs_gate",
                         SCENARIOS_DIR / "scenario_defs.py")
        cls.manifest = cls.runner.load_manifest()
        cls.cr = cls.runner.load_compare_runs()
        cls.spec = cls.cr.load_spec(REPO_ROOT / "verification" / "spec.json")
        cls.scratch = tempfile.TemporaryDirectory(prefix="frozen-scenarios-")

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def test_the_generated_key_set_matches_the_PRODUCER(self):
        """The gate and `freeze.py` must agree on what the freeze adds.

        Both carry `GENERATED_SCENARIO_KEYS`, and the exact
        definitions-to-manifest comparison is only sound while they do: a key
        the producer adds and the gate does not exclude fails every scenario,
        and a key the gate excludes without the producer adding it silently
        stops being compared. Two copies of one fact, so the fact is
        asserted.
        """
        source = (SCENARIOS_DIR / "freeze.py").read_text(encoding="utf-8")
        for key in sorted(GENERATED_SCENARIO_KEYS):
            with self.subTest(key=key):
                self.assertIn(
                    f'"{key}"', source,
                    f"the gate excludes {key!r} from the contract "
                    "comparison, but freeze.py never writes it — so a real "
                    "authored field by that name would stop being checked")
        self.assertIn(
            "GENERATED_SCENARIO_KEYS = frozenset({\"baseline_sha256\", "
            "\"produced_by\"})", source,
            "freeze.py must declare the same generated-key set this gate "
            "uses; if it diverges, the exact comparison is unsound in one "
            "direction or the other")

    def test_manifest_integrity(self):
        """Runs in EVERY lane: schema sanity, spec hash pin, per-scenario
        baseline existence + sha256, provenance ancestry."""
        m = self.manifest
        self.assertEqual(m["spec_sha256"],
                         self.runner.sha256(REPO_ROOT / "verification" / "spec.json"),
                         "verification/spec.json changed after the freeze — "
                         "an adjudicated re-freeze is required, never a "
                         "silent rules change under frozen baselines")
        # The seven machinery hashes that used to be asserted here —
        # `freezer_sha256`, `defs_sha256`, `runner_sha256`,
        # `api_worker_sha256`, `compare_runs_sha256`, `audit_scenario_sha256`
        # and `gate_sha256` — are gone (Sol, `227`). A hash of `runner.py`
        # proved that `runner.py` changed, not that the change weakened
        # comparison; 28 of 89 manifest commits were hash-only re-freezes, a
        # comment-level edit re-froze 54 scenarios, and the coupling deferred
        # issue #99's lock for rounds. The property they reached for is now
        # tested directly in `python/tests/test_comparator_contract.py`, case
        # by case, with each case shown to go red on its own mutation.
        #
        # `spec_sha256` STAYS: it pins the adjudicated comparison RULES, not
        # the source of the code that applies them, and a silent tolerance
        # change under frozen baselines is exactly what it catches.
        # The AUTHORED definitions must still be the ones the manifest
        # describes. This is the semantic replacement for `defs_sha256`, and
        # it is a stronger claim than that hash made: a hash said
        # `scenario_defs.py` was unchanged, this says every scenario CI
        # executes is the scenario the file currently declares.
        #
        # Without it, editing an authored contract is silently ignored —
        # Sol (`228`) changed `usage-unknown-flag`'s `expect_exit` from 2 to
        # 99 and every manifest test stayed green while CI kept running the
        # stored 2. The same escape covered a changed command, lane, file
        # contract, assertion, timeout or seal.
        #
        # The freeze adds exactly two keys — `baseline_sha256` and
        # `produced_by` — so the comparison is exact rather than a field
        # allowlist that drifts. A new generated key must be added HERE
        # deliberately; forgetting makes this test fail rather than start
        # ignoring a contract.
        slugs = json.loads(
            (self.runner.PYTHON_ROOT / "scripts" / "sample_manifest.json")
            .read_text(encoding="utf-8"))["samples"]
        authored = {s["id"]: s for s in self.defs.all_scenarios(slugs)}
        stored = {s["id"]: s for s in m["scenarios"]}
        self.assertEqual(
            sorted(authored), sorted(stored),
            "the authored scenario set and the frozen manifest disagree "
            "about which scenarios exist — a definition was added or "
            "removed without a re-freeze")
        contract_drift = []
        for scenario_id, entry in sorted(stored.items()):
            trimmed = {key: value for key, value in entry.items()
                       if key not in GENERATED_SCENARIO_KEYS}
            if trimmed != authored[scenario_id]:
                moved = sorted(
                    key for key in set(trimmed) | set(authored[scenario_id])
                    if trimmed.get(key) != authored[scenario_id].get(key))
                contract_drift.append(f"{scenario_id}: {moved}")
        self.assertEqual(
            [], contract_drift,
            "these scenarios' AUTHORED contracts no longer match what the "
            "manifest froze, so CI is executing the old contract:\n  "
            + "\n  ".join(contract_drift)
            + "\nRe-freeze them (freeze.py --scenario <id> ...), or revert "
              "the definition.")

        ids = [s["id"] for s in m["scenarios"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate scenario ids")
        by_lane = {}
        for s in m["scenarios"]:
            by_lane[s["lane"]] = by_lane.get(s["lane"], 0) + 1
        self.assertEqual(m["counts"], by_lane,
                         "manifest counts disagree with the scenario list")
        problems = []
        for s in m["scenarios"]:
            problems.extend(self.runner.verify_baselines(s, m))
        self.assertEqual([], problems, "\n".join(problems))
        # The provenance ancestry assertion that used to close this method
        # is DELETED (Sol, `227`). `provenance.commit` being reachable from
        # the present HEAD proved only that a freeze commit remained in one
        # Git lineage. It did not prove the Code interpretation was right,
        # that the current runner executed the scenario, that the baseline
        # represents the current product, or that a report tells an authority
        # the truth. Per-file hashes establish which bytes were approved and
        # running the current product against them establishes whether
        # behaviour still agrees; "made on this line of history" is
        # repository bookkeeping, not a compliance property.
        #
        # It fired twice, on `9f48d45` and `235145a`, and both were
        # self-created outages: the gate rejected unchanged behaviour because
        # a squash merge had rewritten the history it read. Deleting it
        # retires D-95's merge-method exception, the unshallow lock, the
        # `fetch-depth: 0` requirement and the job-digest seal, all of which
        # existed only to keep this one line executable.
        #
        # `provenance.commit` itself stays in the manifest as informational
        # history. Nothing requires it to be reachable.

    def test_post_handoff_seals_retain_the_final_attestation(self):
        scenarios = self.manifest["scenarios"]
        transitioned = [scenario for scenario in scenarios
                        if scenario["seal"] == "python-only:post-handoff"]
        self.assertEqual(31, len(transitioned))
        self.assertEqual(29, sum(scenario["retired_seal"] == "ruby"
                                 for scenario in transitioned))
        self.assertEqual(2, sum(scenario["retired_seal"].startswith("ruby-api:")
                                for scenario in transitioned))
        self.assertFalse(any(scenario["seal"] == "ruby"
                             or scenario["seal"].startswith("ruby-api:")
                             for scenario in scenarios))
        for scenario in transitioned:
            self.assertEqual("85ab14352677093e24038d933cf1071e5b03431a",
                             scenario["last_cross_language_commit"])
            self.assertEqual(33544573991, scenario["last_cross_language_run_id"])
            self.assertEqual(
                "https://github.com/canmet-energy/btap/actions/runs/33544573991",
                scenario["last_cross_language_run_url"])
            self.assertIn("D-84", scenario["seal_transition_reason"])

    def test_first_freeze_seals_claim_no_attestation(self):
        """A scenario authored AFTER the Ruby product retired has no
        cross-language history to point at. `all_scenarios()` converts only
        `ruby`/`ruby-api:` seals, so a `python-only:` seal must arrive with
        none of the transition metadata — carrying 85ab143 on a run Ruby
        never made would be a fabricated attestation, which is the exact
        failure this suite exists to make impossible."""
        attestation_fields = ("retired_seal", "last_cross_language_commit",
                              "last_cross_language_run_id",
                              "last_cross_language_run_url",
                              "seal_transition_reason")
        offenders = []
        for scenario in self.manifest["scenarios"]:
            if scenario["seal"] == "python-only:post-handoff":
                continue  # the converted seals; asserted above
            if not scenario["seal"].startswith("python-only:"):
                continue
            carried = [f for f in attestation_fields if f in scenario]
            if carried:
                offenders.append(f"{scenario['id']}: {carried}")
        self.assertEqual([], offenders,
                         "python-only seals carrying cross-language "
                         "attestation fields:\n" + "\n".join(offenders))

    def test_ci_wires_every_lane(self):
        """Every lane the manifest declares must have a CI executor — the
        exact silent failure this guards against happened: a step-removal
        edit swallowed the parity-lane step and CI stayed green while two
        frozen scenarios went inactive. The python lane rides the default
        (no env var); every other lane must appear as an explicit
        BTAP_SCENARIO_LANES=<lane> in the workflow."""
        workflow = (REPO_ROOT / ".github" / "workflows" / "test.yml"
                    ).read_text(encoding="utf-8")
        missing = [lane for lane in self.manifest["counts"]
                   if lane != "python"
                   and f"BTAP_SCENARIO_LANES={lane}" not in workflow]
        self.assertEqual([], missing,
                         f"manifest lane(s) {missing} have NO executor step "
                         "in .github/workflows/test.yml — their frozen "
                         "scenarios are silently inactive in CI")

    def test_lane_scenarios(self):
        """Every scenario in the selected lane(s), and EXACTLY that many."""
        selected = [s for s in self.manifest["scenarios"]
                    if s["lane"] in LANES]
        expected = sum(self.manifest["counts"].get(lane, 0) for lane in LANES)
        self.assertEqual(expected, len(selected),
                         f"lane selection {LANES} found {len(selected)} "
                         f"scenarios but the manifest declares {expected}")
        self.assertGreater(expected, 0, f"no scenarios in lanes {LANES}")

        corpus = None
        if any("<CORPUS>" in str(s.get("argv", [])) for s in selected):
            corpus = self.runner.ensure_corpus(self.scratch.name)
        lone = self.runner.lone_epw(self.scratch.name)

        executed = 0
        for scenario in selected:
            with self.subTest(scenario=scenario["id"]):
                run_dir = Path(self.scratch.name) / "runs" / scenario["id"]
                run_dir.mkdir(parents=True, exist_ok=True)
                ctx = self.runner.make_ctx(run_dir, corpus, lone)
                run = self.runner.execute(scenario, run_dir, ctx)
                problems = self.runner.compare(scenario, run, self.spec,
                                               self.cr)
                self.assertEqual([], problems, "\n".join(problems))
            executed += 1
        self.assertEqual(expected, executed,
                         "executed-scenario count drifted from the manifest")


if __name__ == "__main__":
    unittest.main()
