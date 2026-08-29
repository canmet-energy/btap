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
import os
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT

SCENARIOS_DIR = REPO_ROOT / "verification" / "scenarios"
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
        cls.manifest = cls.runner.load_manifest()
        cls.cr = cls.runner.load_compare_runs()
        cls.spec = cls.cr.load_spec(REPO_ROOT / "verification" / "spec.json")
        cls.scratch = tempfile.TemporaryDirectory(prefix="frozen-scenarios-")

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def test_manifest_integrity(self):
        """Runs in EVERY lane: schema sanity, spec hash pin, per-scenario
        baseline existence + sha256, provenance ancestry."""
        m = self.manifest
        self.assertEqual(m["spec_sha256"],
                         self.runner.sha256(REPO_ROOT / "verification" / "spec.json"),
                         "verification/spec.json changed after the freeze — "
                         "an adjudicated re-freeze is required, never a "
                         "silent rules change under frozen baselines")
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
        import subprocess
        ancestor = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "merge-base", "--is-ancestor",
             m["provenance"]["commit"], "HEAD"], check=False)
        self.assertEqual(0, ancestor.returncode,
                         f"manifest provenance commit "
                         f"{m['provenance']['commit'][:12]} is not an "
                         "ancestor of HEAD")

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
