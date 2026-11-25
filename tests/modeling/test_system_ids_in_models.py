"""What a build writes into the model under the HVAC taxonomy (D-112).

Ids reach the model; legacy names are accepted as input and never emitted; a
legacy name in the input is recorded; an over-long emitted name is reported
rather than shortened.
"""

from __future__ import annotations

import re
import unittest

from tests.support import needs_sdk

ID = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


@needs_sdk
class TestEmittedNames(unittest.TestCase):

    def build(self, name, zone_name=None):
        from btap import modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from tests.support import load_fixture
        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        if zone_name:
            zones[0].setName(zone_name)
        audit = AuditLog()
        result = modeling.build_system(model, name, zones, audit=audit,
                                       control_zone=zones[0])
        return model, result, audit

    def test_the_id_names_the_loops_and_the_legacy_name_is_not_written(self):
        from btap.modeling.hvac import catalog
        row = catalog.resolve("psz-gas-hwbb-gasboiler")
        model, result, audit = self.build(row["legacy_name"])
        names = [o.nameString() for o in model.objects()]
        self.assertTrue(result.air_loops)
        for loop in result.air_loops:
            self.assertTrue(loop.nameString().startswith("psz-gas-hwbb-gasboiler"),
                            loop.nameString())
        self.assertEqual([], [n for n in names if row["legacy_name"] in n])
        entries = audit.entries
        legacy = [e for e in entries if e["level"] == "info" and "legacy name" in e["action"]]
        self.assertEqual(1, len(legacy))
        self.assertEqual("psz-gas-hwbb-gasboiler", legacy[0]["target"])
        built = [e for e in entries if e["action"].startswith("built ")]
        self.assertEqual(["built psz-gas-hwbb-gasboiler"], [e["action"] for e in built])

    def test_building_by_id_records_no_legacy_entry(self):
        _, _, audit = self.build("psz-gas-hwbb-gasboiler")
        self.assertEqual([], [e for e in audit.entries if "legacy name" in e["action"]])

    def test_every_id_is_file_safe(self):
        from btap.modeling.hvac import catalog
        for row in catalog.rows():
            self.assertRegex(row["id"], ID)
            self.assertLessEqual(len(row["id"]), 40)

    def test_a_long_zone_name_is_reported_not_shortened(self):
        zone = "Z" * 50 + " " + "y" * 60
        _, result, audit = self.build("psz-gas-hwbb-gasboiler", zone_name=zone)
        loops = [loop.nameString() for loop in result.air_loops]
        self.assertTrue(any(zone in n for n in loops), loops)
        warned = [e for e in audit.entries
                  if e["level"] == "warning" and "longer than 100" in e["action"]]
        self.assertEqual(len([n for n in loops if len(n) > 100]), len(warned))
        self.assertTrue(warned)

    def test_an_ordinary_build_stays_under_the_idd_limit(self):
        # ID (<= 40) + " | " + the fixture's zone names: well inside 100.
        _, result, audit = self.build("mau-fc4-gas-chw-gasboiler-centrifchiller")
        self.assertEqual([], [e for e in audit.entries if "longer than 100" in e["action"]])


if __name__ == "__main__":
    unittest.main()
