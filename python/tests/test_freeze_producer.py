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

    def _integrity_with(self, producer, guard=None):
        """Run the REAL `test_manifest_integrity` against a manifest whose
        producer block is `producer`, optionally with `guard` wrapping
        `load_manifest`.

        THE INJECTION HAPPENS BEFORE `load_manifest`, which is Sol's
        correction. My first version called `setUpClass()` — which calls the
        real `runner.load_manifest()` on the UNMODIFIED manifest — and only
        then swapped the class attribute. So a host-equality check inside
        `load_manifest` never saw the impossible value: he installed exactly
        such a check in memory and the test STILL PASSED, with instrumentation
        showing the guard saw only the real `25.2.0-cf7368216c`. The claim
        that this test detects a comparison "wherever someone puts it" was
        false — and it missed the same path as the two greps before it.

        The runner's `MANIFEST` is a module global read by `load_manifest`, so
        pointing it at a temporary, otherwise-identical file puts the
        impossible producer on the real load path. The tracked file is never
        written, which is asserted at the end.
        """
        import importlib.util
        import shutil
        import tempfile

        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["provenance"]["producer"] = dict(producer)

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        injected = directory / "manifest.json"
        injected.write_text(json.dumps(manifest, indent=1) + "\n",
                            encoding="utf-8")
        before = MANIFEST.read_bytes()
        before_mtime = MANIFEST.stat().st_mtime_ns

        spec_path = (REPO_ROOT / "python" / "tests" / "necb"
                     / "test_frozen_scenarios.py")
        spec = importlib.util.spec_from_file_location(
            "frozen_scenarios_under_test", spec_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
            original_load = module._load

            def patched_load(name, path):
                loaded = original_load(name, path)
                if name == "scenario_runner":
                    loaded.MANIFEST = injected
                    if guard is not None:
                        inner = loaded.load_manifest
                        loaded.load_manifest = lambda: guard(inner())
                return loaded

            module._load = patched_load
            case = module.TestFrozenScenarios
            try:
                case.setUpClass()
            except unittest.SkipTest as skip:
                self.skipTest(f"frozen-scenario prerequisites absent: {skip}")
            try:
                case("test_manifest_integrity").test_manifest_integrity()
            finally:
                case.tearDownClass()
        finally:
            sys.modules.pop(spec.name, None)

        self.assertEqual(before, MANIFEST.read_bytes(),
                         "the tracked manifest must never be written")
        # MTIME AS WELL AS BYTES. A write-and-restore with IDENTICAL bytes
        # evades a byte-only check, and Sol verified exactly that. It is not a
        # hypothetical refactor hazard: I had this assertion, then deleted it
        # by replacing this block by line range, and did not notice until he
        # filed it. A parallel worker reading the file mid-write sees a
        # truncated document whether or not the bytes end up the same.
        self.assertEqual(before_mtime, MANIFEST.stat().st_mtime_ns,
                         "the tracked manifest must not even be REWRITTEN "
                         "with identical bytes")

    def test_integrity_still_passes_with_an_IMPOSSIBLE_producer(self):
        """The property: a baseline frozen on one host verifies on another."""
        self._integrity_with(self.IMPOSSIBLE)

    def test_the_negative_test_DETECTS_a_host_gate_in_load_manifest(self):
        """PROOF that the test above can fail — Sol's requirement.

        A negative test nobody has seen fail is a claim, not a check. This
        installs the future mistake it exists to prevent — a host comparison
        inside `load_manifest` — and requires the path to go RED. Without it,
        the test above passes on the freezer's own host whatever the loader
        does, which is precisely how the previous two attempts were hollow.
        """
        import platform

        def host_gate(manifest):
            producer = manifest["provenance"]["producer"]
            if producer.get("python_driver") != platform.python_version():
                raise AssertionError(
                    "this manifest was frozen on a different host")
            return manifest

        with self.assertRaises(AssertionError) as caught:
            self._integrity_with(self.IMPOSSIBLE, guard=host_gate)
        self.assertIn("different host", str(caught.exception),
                      "the injected gate must be what failed, not something "
                      "incidental")

    def test_the_guard_harness_does_not_fail_on_its_own(self):
        """The control for the control: a PASS-THROUGH guard must not break
        the path, or the test above could be red for an unrelated reason."""
        self._integrity_with(self.IMPOSSIBLE, guard=lambda manifest: manifest)

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
