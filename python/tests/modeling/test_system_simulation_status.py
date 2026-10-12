"""Port of test_system_simulation_status.rb.

Every catalog system must produce a model EnergyPlus can at least start.
The defect class this guards is a required performance-curve field left
UNSET — the SDK models that as merely absent, so every in-process assertion
passes and the model looks fine right up until E+ refuses it (the VRF
defrost-EIR curve incident).

Simulating 97 systems takes about eight minutes one at a time, so the sweep
lives in `python/scripts/simulate_all_systems.py` and this test reads the
verdict it writes. That script is PYTHON and owns the file: the Ruby twin
this docstring used to name retired at R6 under D-84, which left the verdict
with no producer at all — and 97 hand-written `"ok"` rows carrying no run
evidence (Claude, 2026-10-12).

This test is hard in BOTH directions: a newly-broken system fails here, and
so does a system that starts working, because a stale exemption would hide
the next regression behind it. It is also hard about the verdict ITSELF —
every row must carry the error counts, the completion flag and the elapsed
time from a real run, and the file must say what produced it.
"""

import json
import math
import pathlib
import unittest

from tests.support import FIXTURES, needs_sdk

STATUS = FIXTURES / "system_simulation_status.json"

# Known broken, with the root cause. EMPTY, and the goal is to keep it that
# way: every one of the 97 catalog systems produces a model EnergyPlus will
# start.
KNOWN_BAD: dict = {}


@needs_sdk
class TestSystemSimulationStatus(unittest.TestCase):
    def setUp(self):
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
            1, self.verdict["produced_by"].get("schema_version"),
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
        """`"ok"` alone is indistinguishable from `"ok"` somebody typed.

        And so is evidence of the wrong TYPE. `severe=False, fatal=False,
        completed="NO completion line", seconds=True` satisfied every
        assertion in the first version of this test, because `False == 0`,
        a non-empty string is truthy and `True > 0` (Sol, `234`). Booleans
        are integers in Python, so the counts must be checked for not being
        booleans explicitly.
        """
        statuses = ("ok", "build_error", "simulation_error", "sweep_error",
                    "fixture_error")
        for row in self.rows:
            with self.subTest(system=row["name"]):
                self.assertIn(
                    row["status"], statuses,
                    "status must come from the producer's closed vocabulary")
                for field in ("severe", "fatal"):
                    value = row.get(field)
                    self.assertIsInstance(
                        value, int,
                        f"{field} must be an integer count")
                    self.assertNotIsInstance(
                        value, bool,
                        f"{field} is a COUNT, and a bool satisfies "
                        "`isinstance(x, int)` while carrying no count")
                    self.assertGreaterEqual(value, 0, field)
                self.assertIsInstance(
                    row.get("completed"), bool,
                    "completed is a flag; a non-empty string is truthy and "
                    "says nothing")
                seconds = row.get("seconds")
                self.assertIsInstance(seconds, (int, float))
                self.assertNotIsInstance(
                    seconds, bool, "seconds is a duration, not a flag")
                self.assertTrue(
                    math.isfinite(seconds) and seconds > 0,
                    "a run that took no time did not run")
                if row["status"] == "ok":
                    self.assertIs(
                        True, row["completed"],
                        f"{row['name']}: claims ok and EnergyPlus never "
                        "printed its completion line")
                    self.assertEqual(
                        (0, 0), (row["severe"], row["fatal"]),
                        f"{row['name']}: claims ok with "
                        f"{row['severe']} severe / {row['fatal']} fatal")

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
        produced = self.verdict.get("produced_by")
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
        self.assertIn("sizing", produced["mode"].lower(),
                      "the mode must say what was actually run")
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
                         "system(s) that used to build a simulate-able model now do not: "
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
