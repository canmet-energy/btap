"""Port of test_system_simulation_status.rb.

Every catalog system must produce a model EnergyPlus can at least start.
The defect class this guards is a required performance-curve field left
UNSET — the SDK models that as merely absent, so every in-process assertion
passes and the model looks fine right up until E+ refuses it (the VRF
defrost-EIR curve incident).

Simulating 97 systems takes minutes even parallel, so the sweep lives in
python/scripts/simulate_all_systems.py (the Ruby twin commits the verdict
this reads: btap-modeling/test/fixtures/system_simulation_status.json — ONE
shared verdict file, Ruby-owned). This test is hard in BOTH directions: a
newly-broken system fails here, and so does a system that starts working,
because a stale exemption would hide the next regression behind it.
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
        self.rows = json.loads(STATUS.read_text(encoding="utf-8"))
        self.failing = sorted(r["name"] for r in self.rows if r["status"] != "ok")

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
