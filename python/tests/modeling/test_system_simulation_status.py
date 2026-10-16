"""The catalogue sweep's committed evidence.

Every catalogue system, built on the bare fixture, must complete the recorded
sizing or annual mode with zero Severe or Fatal errors. This does not certify
the seeded samples: the humidified-PSZ incident is the live case where a clean
catalogue system became an unsimulable sample after generation modified it.
The defect class this guards is a required performance-curve field left UNSET
— the SDK models that as merely absent, so every in-process assertion passes
and the model looks fine until EnergyPlus reaches it.

Simulating 102 systems takes about nine minutes one at a time, so the sweep
lives in `python/scripts/simulate_all_systems.py` and this test reads the
verdict it writes. That script is PYTHON and owns the file: the Ruby twin
this docstring used to name retired at R6 under D-84, which left the verdict
with no producer at all — and 97 hand-written `"ok"` rows carrying no run
evidence (Claude, 2026-10-12).

This test is hard in BOTH directions: a newly-broken system fails here, and
so does a system that starts working, because a stale exemption would hide
the next regression behind it. It is also hard about the verdict ITSELF —
rows that reached EnergyPlus must carry its error counts and completion flag,
every row must carry elapsed time, and the file must say what produced it.
"""

import importlib.util
import json
import pathlib
import sys
import unittest

from tests.support import FIXTURES, REPO_ROOT, needs_sdk

STATUS = FIXTURES / "system_simulation_status.json"
SCRIPT = REPO_ROOT / "python" / "scripts" / "simulate_all_systems.py"

# Known broken, with the root cause. EMPTY, and the goal is to keep it that
# way: every one of the 102 catalog systems completes the recorded mode cleanly.
KNOWN_BAD: dict = {}


def _load_sweep():
    spec = importlib.util.spec_from_file_location(
        "status_sweep_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["status_sweep_under_test"] = module
    spec.loader.exec_module(module)
    return module


@needs_sdk
class TestSystemSimulationStatus(unittest.TestCase):
    def setUp(self):
        self.sweep = _load_sweep()
        self.verdict = json.loads(STATUS.read_text(encoding="utf-8"))
        self.rows = self.verdict["systems"]
        self.failing = sorted(r["name"] for r in self.rows if r["status"] != "ok")

    def test_the_verdict_declares_a_SCHEMA_VERSION(self):
        """So both readers can refuse an unknown shape rather than fail on it.

        The rows moved under a `systems` key once already and broke
        `generate_samples.py`'s gate with `TypeError: string indices must be
        integers`. A declared version makes the next migration explicit
        (Sol, `234`).
        """
        self.assertEqual(
            self.sweep.SCHEMA_VERSION,
            self.verdict["produced_by"].get("schema_version"),
            "unknown verdict schema — a reader must refuse it, not guess")

    def test_the_verdict_describes_this_catalogue_EXACTLY(self):
        """Both directions, on `(name, family)`, with no duplicates.

        Checking only for MISSING rows let three fabrications through: an
        extra invented system, a duplicate of a real row, and a real row
        carrying the wrong family (Sol, `234`). A verdict that describes a
        system the catalogue does not have is not evidence about this
        catalogue.
        """
        from btap.modeling.hvac import catalog

        catalogue = sorted((row["name"], row.get("family"))
                           for row in catalog.rows())
        recorded = sorted((row["name"], row.get("family"))
                          for row in self.rows)
        self.assertEqual(
            len(recorded), len(set(recorded)),
            "a duplicated row means one system was verdicted twice, and "
            "which verdict stands is undefined")
        self.assertEqual(
            catalogue, recorded,
            "the verdict must describe exactly this catalogue — re-run "
            "python/scripts/simulate_all_systems.py")

    def test_the_verdict_was_produced_from_THIS_catalogue(self):
        """The coupling that makes this a gate rather than a dated snapshot.

        Sol's `234` B1: he changed the first catalogue row's family from
        `psz` to `no_such_family`, keeping its public name, and every status
        test stayed green — 6 passed, 102 subtests — while running that one
        system gave `build_error`. Name comparison cannot see a row EDITED
        under its own name, which is the ordinary shape of a builder
        regression.

        So the verdict records the digest of the catalogue it describes, and
        this compares it. A row edit now fails here with an instruction to
        re-run the sweep.

        **This is a digest of the catalogue DATA, not of builder source.** A
        source hash is the machinery-hash pattern D-103 retired: it proves
        the code changed, not that the systems still simulate. This proves
        the verdict and the catalogue are talking about the same set of
        rows. It does NOT catch a change inside a builder whose catalogue
        row is untouched — that gap is real, it is Sol's B1 second half, and
        closing it needs the sweep to run in CI rather than another hash.

        I recorded this digest and did not compare it, so the fabrication
        "catalogue_sha256 = 000...0" passed all eight tests (measured). A
        field nothing reads is not a check.
        """
        import hashlib

        from btap.modeling.hvac import catalog

        catalogue_path = pathlib.Path(catalog.__file__).with_name(
            "data") / "systems.json"
        digest = hashlib.sha256(catalogue_path.read_bytes()).hexdigest()
        self.assertEqual(
            digest, self.verdict["produced_by"].get("catalogue_sha256"),
            "systems.json has changed since this verdict was produced, so "
            "the verdict describes a catalogue that no longer exists — "
            "re-run python/scripts/simulate_all_systems.py and commit the "
            "moved verdict with the change")

    def test_every_row_carries_RUN_EVIDENCE_OF_THE_RIGHT_TYPE(self):
        """Apply the producer's schema instead of maintaining a second one.

        A build or fixture failure never reached EnergyPlus, so requiring its
        counters fabricated evidence the producer cannot emit. `ok` and
        `simulation_error` did reach it and retain the strict counter and
        completion contract.
        """
        try:
            rows, mode = self.sweep.validate_status_payload(self.verdict)
        except ValueError as error:
            self.fail(f"invalid producer verdict: {error}")
        self.assertEqual(self.rows, rows)
        self.assertEqual(self.verdict["produced_by"]["mode"], mode)

    def _assert_valid_producer(self, produced):
        self.assertIsInstance(produced, dict)
        for field in ("openstudio_sdk", "energyplus", "fixture", "epw",
                      "ddy", "mode", "source_revision", "generated_utc"):
            with self.subTest(field=field):
                self.assertTrue(produced.get(field),
                                f"`produced_by.{field}` is missing")
        self.assertRegex(
            produced["openstudio_sdk"], r"^\d+\.\d+\.\d+",
            "the SDK version must look like a version")
        self.assertRegex(
            produced["energyplus"], r"EnergyPlus.*\d+\.\d+\.\d+",
            "EnergyPlus is the program whose Severe/Fatal count this "
            "verdict reports, and its build must be identified")
        self.assertIn(
            produced["mode"], self.sweep.SUPPORTED_MODES,
            "the mode must identify one supported sweep claim exactly")
        for digest in ("fixture_sha256", "epw_sha256", "ddy_sha256"):
            with self.subTest(field=digest):
                self.assertRegex(
                    produced.get(digest, ""), r"^[0-9a-f]{64}$",
                    f"`{digest}` identifies WHICH bytes the rows attest to")
        self.assertRegex(
            produced["source_revision"], r"^[0-9a-f]{40}$",
            "the source revision says which builder implementation ran")
        self.assertRegex(
            produced["generated_utc"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
            "a timestamp, whose absence this module cited as part of the "
            "problem it was fixing")

    def test_produced_by_names_the_PRODUCER_and_the_INPUTS(self):
        """Semantically validated, not merely non-empty.

        Replacing every value with the string "fabricated" passed the first
        version. And the record named the SDK and an `openstudio` CLI probe
        while OMITTING EnergyPlus — the program whose success is the verdict
        — and the DDY that supplies the design days (Sol, `234`).

        Validated against the artifact's own contract, NOT against this
        host: evidence produced on one supported machine must stay readable
        on another.
        """
        self._assert_valid_producer(self.verdict.get("produced_by"))

    def test_ANNUAL_is_an_admissible_stronger_verdict_mode(self):
        """An annual sweep includes the sizing periods and may be committed."""
        produced = dict(self.verdict["produced_by"])
        produced["mode"] = self.sweep.ANNUAL_MODE
        self._assert_valid_producer(produced)

    def test_the_status_file_covers_every_catalog_system(self):
        from btap.modeling.hvac import catalog
        catalog_names = sorted(r["name"] for r in catalog.rows())
        recorded = sorted(r["name"] for r in self.rows)
        missing = [n for n in catalog_names if n not in recorded]
        self.assertEqual([], missing,
                         "system(s) never simulated — re-run the sweep: " + ", ".join(missing))

    def test_no_system_has_newly_broken(self):
        regressions = [n for n in self.failing if n not in KNOWN_BAD]
        self.assertEqual([], regressions,
                         "system(s) whose recorded simulation used to be clean "
                         "now fail: "
                         + ", ".join(regressions))

    def test_no_stale_exemptions(self):
        # A fixed system left on the list would silently absorb the next
        # regression in its family.
        fixed = [n for n in sorted(KNOWN_BAD) if n not in self.failing]
        self.assertEqual([], fixed,
                         "system(s) now simulate — remove them from KNOWN_BAD: "
                         + ", ".join(fixed))

    def test_every_non_heat_pump_family_is_clean(self):
        # Pins the blast radius: the conventional families are the ones a
        # user reaches for first and none of them may regress.
        dirty = list(dict.fromkeys(r["family"] for r in self.rows if r["status"] != "ok"))
        conventional = ["psz", "vav_reheat", "fan_coils", "mau_ptac", "baseboards",
                        "zone_terminal", "unit_heaters", "furnace", "evap_cooler",
                        "doas", "wshp", "zone_ervs"]
        broken = [f for f in dirty if f in conventional]
        self.assertEqual([], broken, "a conventional family broke: " + ", ".join(broken))


if __name__ == "__main__":
    unittest.main()
