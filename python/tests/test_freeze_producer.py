"""The frozen manifest records WHO produced it — as a record, not a gate.

The manifest pinned the SOURCE of a baseline and never its PRODUCER. Because
the scenarios' weather is committed (`python/tests/fixtures/weather/*.epw` and
`*.ddy` are tracked), the provenance commit already pins the weather bytes,
and the harness hashes pin the rest of the source. What was missing is the
engine stack that ran: `openstudio_cli` is a version STRING a machine reports,
so two hosts can both report `3.11.0+241b8abb4d` while running different
EnergyPlus builds — and CI never freezes, so the producer has always been
whichever developer machine ran `freeze.py`.

THE CENTRAL PROPERTY THESE TESTS PIN IS A NEGATIVE ONE: nothing compares the
recorded identities against the running machine. A baseline frozen on one host
must stay verifiable on another, which is the point of the frozen corpus. If a
future change turns these fields into an equality check, every developer's
checkout fails `test_manifest_integrity` for a reason that has nothing to do
with the baselines — so the absence of that comparison is asserted here
deliberately, not left to be noticed.

Offline: no freeze is run and no scenario is executed.
"""

from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = REPO_ROOT / "verification" / "scenarios"
MANIFEST = SCENARIOS / "manifest.json"

#: Every key the block must carry. `container_digest` is included and expected
#: to be null today: the CI image's tag is
#: `<openstudio version>-<sha256(Dockerfile)[:12]>`, which pins the RECIPE
#: rather than the built bytes, and a true `sha256:` digest is obtainable only
#: where the image runs. The slot exists so the follow-on fills it rather than
#: reshaping provenance again.
EXPECTED_KEYS = {"openstudio", "energyplus", "python", "platform",
                 "container_digest"}


def _freeze():
    if str(SCENARIOS) not in sys.path:
        sys.path.insert(0, str(SCENARIOS))
    return importlib.import_module("freeze")


class TestProducerIdentity(unittest.TestCase):
    def setUp(self):
        self.freeze = _freeze()

    def test_it_reports_every_expected_field(self):
        identity = self.freeze.producer_identity()
        self.assertEqual(EXPECTED_KEYS, set(identity))

    def test_the_energyplus_build_hash_is_kept_not_just_the_version(self):
        """A bare `25.2.0` is exactly what hides two different engines."""
        identity = self.freeze.producer_identity()
        energyplus = identity.get("energyplus")
        if energyplus is None:
            self.skipTest("no EnergyPlus provisioned in this environment")
        self.assertRegex(
            energyplus, r"^\d+\.\d+\.\d+-[0-9a-f]+$",
            "the build hash is the point — a bare version string is what two "
            "hosts can share while running different engines")

    def test_container_digest_is_absent_until_ci_can_supply_it(self):
        self.assertIsNone(self.freeze.producer_identity()["container_digest"])

    def test_an_unreadable_identity_is_absent_rather_than_fatal(self):
        """A freeze must not break because a probe failed.

        Simulated by making the EnergyPlus probe raise: the field goes to
        None and the other fields still report.
        """
        from unittest import mock

        import btap.simulation.engine as engine

        with mock.patch.object(engine, "ensure_energyplus",
                               side_effect=RuntimeError("no engine")):
            identity = self.freeze.producer_identity()
        self.assertIsNone(identity["energyplus"])
        self.assertIsNotNone(identity["python"],
                             "one failed probe must not blank the others")


class TestItIsARecordAndNotAGate(unittest.TestCase):
    """The negative property. See the module docstring.

    These identities differ per machine BY DESIGN, so no check may require
    them to match the host running the tests.
    """

    def test_the_manifest_carries_the_block(self):
        provenance = json.loads(MANIFEST.read_text(encoding="utf-8"))["provenance"]
        self.assertIn("producer", provenance,
                      "re-freeze: the manifest predates the producer block")
        self.assertEqual(EXPECTED_KEYS, set(provenance["producer"]))

    def test_no_test_compares_the_recorded_producer_to_this_machine(self):
        """A grep, deliberately — the thing to prevent is a future equality
        check, and the only way to see one coming is to look for it."""
        suspicious = []
        for path in sorted((REPO_ROOT / "python" / "tests").rglob("test_*.py")):
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if '"producer"' not in text and "'producer'" not in text:
                continue
            for line in text.splitlines():
                if "producer" in line and ("assertEqual" in line
                                           or "assertIn" in line):
                    suspicious.append(f"{path.relative_to(REPO_ROOT)}: {line.strip()}")
        self.assertEqual(
            [], suspicious,
            "a baseline frozen on one host must stay verifiable on another; "
            "the producer block is attribution, not a constraint")

    def test_the_frozen_scenario_gate_does_not_read_it(self):
        gate = (REPO_ROOT / "python" / "tests" / "necb"
                / "test_frozen_scenarios.py").read_text(encoding="utf-8")
        self.assertNotIn("producer", gate,
                         "test_frozen_scenarios must not gate on the producer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
