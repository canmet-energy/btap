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

    def test_the_verdict_was_PRODUCED_and_says_by_what(self):
        """A verdict with no producer is a sentence somebody typed.

        Until 2026-10-12 this file held 97 rows of
        `{"family", "name", "status": "ok"}` — no run directory, no error
        counts, no provenance — and the script named as its producer did not
        exist. The docstring above pointed at a Ruby twin under
        `btap-modeling/`, and those gems retired at R6 under D-84, so the
        file had had no producer at all since the retirement. That is the
        "handwritten `ok` entries" `docs/HVAC_MODERN_SYSTEMS_PLAN.md` names
        as a release blocker for new catalogue rows.

        So the shape is now a claim with a provenance block, and this test
        requires it. `produced_by` is a RECORD and never a gate: nothing
        compares it against the running machine, because a verdict produced
        on one host must stay readable on another — the same stance as
        `freeze.py`'s per-scenario `produced_by`.
        """
        produced = self.verdict.get("produced_by")
        self.assertIsInstance(
            produced, dict,
            "the verdict must carry a `produced_by` block naming what "
            "produced it — run python/scripts/simulate_all_systems.py")
        for field in ("openstudio_cli", "openstudio_sdk", "fixture",
                      "weather", "mode"):
            with self.subTest(field=field):
                self.assertTrue(
                    produced.get(field),
                    f"`produced_by.{field}` is what lets a reader reproduce "
                    "this verdict or tell that they cannot")

    def test_every_row_carries_RUN_EVIDENCE_and_not_just_a_word(self):
        """`"ok"` alone is indistinguishable from `"ok"` somebody typed.

        Each row records the severe and fatal counts `eplusout.err` held,
        whether EnergyPlus printed its completion line, and how long the run
        took. A row claiming `ok` with no completion, or with a severe count
        above zero, is self-contradictory and fails here rather than being
        believed.
        """
        for row in self.rows:
            with self.subTest(system=row["name"]):
                for field in ("severe", "fatal", "completed", "seconds"):
                    self.assertIn(
                        field, row,
                        f"{row['name']}: a verdict without `{field}` is not "
                        "evidence of a run")
                if row["status"] == "ok":
                    self.assertTrue(
                        row["completed"],
                        f"{row['name']}: claims ok and EnergyPlus never "
                        "printed its completion line")
                    self.assertEqual(
                        (0, 0), (row["severe"], row["fatal"]),
                        f"{row['name']}: claims ok with "
                        f"{row['severe']} severe / {row['fatal']} fatal")
                self.assertGreater(
                    row["seconds"], 0,
                    f"{row['name']}: a run that took no time did not run")

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
