"""Post-handoff seal accounting retains and validates the final attestation."""

import importlib.util
import json
import sys
import unittest
from copy import deepcopy

from tests.support import REPO_ROOT

SCENARIOS = REPO_ROOT / "verification" / "scenarios"
sys.path.insert(0, str(SCENARIOS))

DEFS_SPEC = importlib.util.spec_from_file_location(
    "scenario_defs_transition_test", SCENARIOS / "scenario_defs.py")
scenario_defs = importlib.util.module_from_spec(DEFS_SPEC)
DEFS_SPEC.loader.exec_module(scenario_defs)

FREEZE_SPEC = importlib.util.spec_from_file_location(
    "freeze_transition_test", SCENARIOS / "freeze.py")
freeze = importlib.util.module_from_spec(FREEZE_SPEC)
FREEZE_SPEC.loader.exec_module(freeze)


def scenarios():
    slugs = json.loads(
        (REPO_ROOT / "python" / "scripts" / "sample_manifest.json")
        .read_text(encoding="utf-8"))["samples"]
    return scenario_defs.all_scenarios(slugs)


class TestFreezeSealTransition(unittest.TestCase):
    def test_all_scenarios_are_accounted_without_active_ruby(self):
        active, retired, attestation = freeze.seal_accounting(scenarios())
        self.assertEqual({"python-only:post-handoff": 31, "python-only": 4}, active)
        self.assertEqual({"ruby": 29, "ruby-api": 2}, retired)
        self.assertEqual({
            "commit": "85ab14352677093e24038d933cf1071e5b03431a",
            "run_id": 33544573991,
            "run_url": "https://github.com/canmet-energy/btap/actions/runs/33544573991",
        }, attestation)

    def test_missing_transition_metadata_is_rejected(self):
        sample = deepcopy(scenarios())
        transitioned = next(item for item in sample
                            if item["seal"] == "python-only:post-handoff")
        del transitioned["last_cross_language_run_id"]
        with self.assertRaisesRegex(ValueError, "transition metadata missing"):
            freeze.seal_accounting(sample)

    def test_inconsistent_attestation_is_rejected(self):
        sample = deepcopy(scenarios())
        transitioned = [item for item in sample
                        if item["seal"] == "python-only:post-handoff"]
        transitioned[-1]["last_cross_language_run_id"] += 1
        with self.assertRaisesRegex(ValueError, "disagree on final attestation"):
            freeze.seal_accounting(sample)

    def test_active_or_retired_unknown_seals_are_rejected(self):
        sample = deepcopy(scenarios())
        sample[0]["seal"] = "ruby"
        with self.assertRaisesRegex(ValueError, "active product-Ruby seal"):
            freeze.seal_accounting(sample)

        sample = deepcopy(scenarios())
        transitioned = next(item for item in sample
                            if item["seal"] == "python-only:post-handoff")
        transitioned["retired_seal"] = "unknown"
        with self.assertRaisesRegex(ValueError, "invalid retired_seal"):
            freeze.seal_accounting(sample)


if __name__ == "__main__":
    unittest.main()