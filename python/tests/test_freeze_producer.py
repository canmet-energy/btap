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
#: `python_driver` and `python_worker` are SEPARATE because they can differ:
#: the driver runs `freeze.py`, the worker runs the scenarios and honours
#: `BTAP_PYTHON`. One field claiming to be "the" interpreter named one that
#: produced none of the outputs (Sol, PR #80).
EXPECTED_KEYS = {"openstudio", "energyplus", "python_driver", "python_worker",
                 "platform", "container_digest"}


def _freeze():
    if str(SCENARIOS) not in sys.path:
        sys.path.insert(0, str(SCENARIOS))
    return importlib.import_module("freeze")


class TestProducerIdentity(unittest.TestCase):
    def setUp(self):
        self.freeze = _freeze()

    def test_it_reports_every_expected_field(self):
        identity = self.freeze.producer_identity()
        # `python_worker_executable` is added only when the probe succeeds, so
        # the expected set is a floor rather than an equality.
        self.assertTrue(EXPECTED_KEYS.issubset(set(identity)),
                        f"missing: {EXPECTED_KEYS - set(identity)}")

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

    def test_a_FAILED_version_probe_records_absence_not_garbage(self):
        """Sol's finding: the exit status was never checked.

        `identity["energyplus"] = text.split()[-1]` took the last word of ANY
        output, so a probe printing "EnergyPlus version probe FAILED" with
        returncode 7 recorded `"energyplus": "FAILED"` — indistinguishable in
        provenance from a real build string.
        """
        from unittest import mock

        class Failed:
            returncode, stdout, stderr = 7, "EnergyPlus version probe FAILED\n", ""

        with mock.patch.object(self.freeze.subprocess, "run",
                               return_value=Failed()):
            identity = self.freeze.producer_identity()
        self.assertIsNone(identity["energyplus"],
                          "a failed probe must record absence, not the last "
                          "word of its error message")

    def test_a_WRONG_SHAPED_version_is_not_recorded(self):
        """Even on success, only a version-with-build shape is accepted."""
        from unittest import mock

        class Odd:
            returncode, stdout, stderr = 0, "EnergyPlus, Version banana\n", ""

        with mock.patch.object(self.freeze.subprocess, "run",
                               return_value=Odd()):
            identity = self.freeze.producer_identity()
        self.assertIsNone(identity["energyplus"])

    def test_the_worker_interpreter_is_recorded_separately(self):
        """Sol's finding: `BTAP_PYTHON` makes the two interpreters differ."""
        identity = self.freeze.producer_identity()
        self.assertIn("python_driver", identity)
        self.assertIn("python_worker", identity)

    def test_an_unreadable_identity_is_absent_rather_than_fatal(self):
        """A freeze must not break because a probe failed.

        The probes now run in a SUBPROCESS (the worker interpreter), so the
        soft-failure property is exercised by making that subprocess raise
        rather than by patching an in-process call — which an earlier version
        of this test did, and which the new design made vacuous.
        """
        from unittest import mock

        with mock.patch.object(self.freeze.subprocess, "run",
                               side_effect=OSError("no interpreter")):
            identity = self.freeze.producer_identity()
        self.assertIsNone(identity["energyplus"])
        self.assertIsNone(identity["python_worker"])
        self.assertIsNotNone(identity["python_driver"],
                             "one failed probe must not blank the others")
        self.assertIsNotNone(identity["platform"])

    def test_a_FAILED_worker_probe_records_absence(self):
        """A nonzero probe records nothing, not the last word of its error."""
        from unittest import mock

        class Failed:
            returncode = 7
            stdout = "energyplus FAILED\n"
            stderr = ""

        with mock.patch.object(self.freeze.subprocess, "run",
                               return_value=Failed()):
            identity = self.freeze.producer_identity()
        self.assertIsNone(identity["energyplus"])
        self.assertIsNone(identity["python_worker"])


class TestItIsARecordAndNotAGate(unittest.TestCase):
    """The negative property, pinned BEHAVIOURALLY. See the module docstring.

    An earlier version of this class pinned it with two greps — one scanning
    test files for `"producer"` on the same line as `assertEqual`/`assertIn`,
    the other checking that `test_frozen_scenarios.py` never spells
    `producer`. Neither holds the door shut: an equality check added inside
    `runner.load_manifest()` would make `test_manifest_integrity`
    host-dependent while both greps stayed green (Sol, PR #80).

    So the contract is exercised instead: take the committed manifest, replace
    its producer identities with values that CANNOT match this host, and
    require the real integrity path to still pass as long as the source and
    baseline hashes agree. That is the property — a baseline frozen on one
    machine remains verifiable on another — and it fails if anyone ever makes
    the producer load-bearing, wherever they put the comparison.
    """

    #: Identities no machine can have, so a comparison against the host must
    #: fail if one is ever introduced.
    IMPOSSIBLE = {
        "openstudio": "0.0.0+notarealbuild",
        "energyplus": "0.0.0-notarealbuild",
        "python_driver": "0.0.0",
        "python_worker": "0.0.0",
        "platform": "NotARealPlatform-0",
        "container_digest": "sha256:" + "0" * 64,
    }

    def test_the_manifest_carries_the_block(self):
        provenance = json.loads(MANIFEST.read_text(encoding="utf-8"))["provenance"]
        self.assertIn("producer", provenance,
                      "re-freeze: the manifest predates the producer block")
        for key in ("openstudio", "energyplus", "python_driver",
                    "python_worker", "platform", "container_digest"):
            self.assertIn(key, provenance["producer"])

    def test_integrity_still_passes_with_an_IMPOSSIBLE_producer(self):
        """The load-bearing test. Wherever a comparison is added, this fails.

        IT TOUCHES NO SHARED FILE. The first version overwrote the tracked
        `verification/scenarios/manifest.json` while a subprocess ran and
        copied it back afterwards. CI runs the suite under `pytest -n auto`,
        so another worker could read the impossible block — or a half-written
        JSON file — and an interrupted process would leave the tracked
        manifest altered. Sol demonstrated it: he ran the field-shape test
        inside that window and it failed on `container_digest`. Writing to the
        shared checkout to test a property of the shared checkout was the
        wrong shape (Sol, PR #80).

        Instead the REAL `test_manifest_integrity` runs in-process against an
        INJECTED manifest: `TestFrozenScenarios` loads it once in
        `setUpClass`, so replacing that attribute exercises the genuine
        assertions — hashes, ancestry, counts — with a producer block no
        machine can match.
        """
        import importlib.util

        spec_path = (REPO_ROOT / "python" / "tests" / "necb"
                     / "test_frozen_scenarios.py")
        spec = importlib.util.spec_from_file_location(
            "frozen_scenarios_under_test", spec_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            case = module.TestFrozenScenarios
            try:
                case.setUpClass()
            except unittest.SkipTest as skip:
                self.skipTest(f"frozen-scenario prerequisites absent: {skip}")
            try:
                # the injection: only the producer block, nothing else
                case.manifest = json.loads(json.dumps(case.manifest))
                case.manifest["provenance"]["producer"] = dict(self.IMPOSSIBLE)
                instance = case("test_manifest_integrity")
                instance.test_manifest_integrity()
            finally:
                case.tearDownClass()
        finally:
            sys.modules.pop(spec.name, None)

        # If that raised, the producer has become load-bearing somewhere.
        self.assertEqual(
            dict(self.IMPOSSIBLE), case.manifest["provenance"]["producer"],
            "sanity: the impossible block must have been the one in play")

    def test_the_live_manifest_is_never_modified_by_these_tests(self):
        """Pins the fix above, not just the behaviour it replaced.

        A future edit reaching for the simpler write-and-restore approach
        would reintroduce a test that can corrupt a parallel run.
        """
        before = MANIFEST.read_bytes()
        mtime = MANIFEST.stat().st_mtime_ns
        self.test_integrity_still_passes_with_an_IMPOSSIBLE_producer()
        self.assertEqual(before, MANIFEST.read_bytes(),
                         "the tracked manifest must be byte-identical after "
                         "the negative test runs")
        self.assertEqual(mtime, MANIFEST.stat().st_mtime_ns,
                         "the tracked manifest must not even be REWRITTEN "
                         "with identical bytes — a parallel worker reading it "
                         "mid-write sees a truncated file")

        # NO SOURCE GREP HERE, and the reason is worth recording. The first
        # version of this test asserted `"MANIFEST.write_text" not in` its own
        # source — and FAILED, because that string appears in the docstring
        # above describing what not to do. A check that greps for a
        # prohibition is a check modelling itself: it can fail for the wrong
        # reason, as that did, and pass while the prohibited thing happens by
        # another spelling. The byte-and-mtime comparison above is the
        # property; it needs no help.

    def test_the_field_shapes_are_checked_separately(self):
        """The POSITIVE check, kept apart from the negative one above.

        Shape is worth asserting; equality with the host is not.
        """
        provenance = json.loads(MANIFEST.read_text(encoding="utf-8"))["provenance"]
        producer = provenance["producer"]
        if producer.get("energyplus") is not None:
            self.assertRegex(producer["energyplus"],
                             r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z]+)?$")
        if producer.get("python_driver") is not None:
            self.assertRegex(producer["python_driver"], r"^\d+\.\d+\.\d+$")
        self.assertIsNone(producer["container_digest"],
                          "only CI can supply a real image digest")


if __name__ == "__main__":
    unittest.main(verbosity=2)
