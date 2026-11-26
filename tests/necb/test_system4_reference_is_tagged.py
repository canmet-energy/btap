"""A System 4 reference is TAGGED System 4 in the model it builds (D-113).

NECB System 4 has no catalogue row of its own: its definition in each
edition's reference_rules.json names the System 3 row with
``sys_abbr: "sys_4"`` in its config, and that tag is what names the reference's
System 4 objects. Fable (PR #241): nothing tied the rules data to the built
reference, so deleting the override would have passed every behavioural test.
This builds the reference through the real selection, from the rules.
"""

from __future__ import annotations

import unittest

from btap.audit import AuditLog
from tests.support import needs_sdk


def _tags(model):
    names = [o.nameString() for o in model.objects()]
    return {tag for tag in ("sys_3", "sys_4") if any(n.startswith(tag + " ") for n in names)}


@needs_sdk
class TestTheSystem4ReferenceIsTagged(unittest.TestCase):

    def reference(self, code, *, hooded):
        import openstudio

        from btap.codes.necb import hvac
        from tests.necb.hvac_helpers import proposed_with_hvac
        proposed = proposed_with_hvac('bb-hwbb-gasboiler')
        zones = sorted(proposed.getThermalZones(), key=lambda z: z.nameString())
        building = {'storeys': 1}
        if hooded:
            for space_type in proposed.getSpaceTypes():
                if space_type.spaces():
                    space_type.setStandardsSpaceType('Food preparation area')
            for zone in zones:
                openstudio.model.FanZoneExhaust(proposed).addToThermalZone(zone)
            building['kitchen_hood_zones'] = [z.nameString() for z in zones]
        result = hvac.reference_hvac(proposed, code=code, audit=AuditLog(), building=building)
        return result

    def test_system_4_objects_say_sys_4(self):
        for code in ("necb2020", "necb2025"):
            with self.subTest(code=code):
                result = self.reference(code, hooded=True)
                self.assertEqual({4}, {a.reference_system for a in result.assignments},
                                 "precondition: hooded food preparation selects System 4")
                self.assertEqual({"sys_4"}, _tags(result.model))

    def test_the_control_system_3_says_sys_3(self):
        result = self.reference("necb2025", hooded=False)
        self.assertEqual({3}, {a.reference_system for a in result.assignments},
                         "precondition: a one-storey unhooded block selects System 3")
        self.assertEqual({"sys_3"}, _tags(result.model))


if __name__ == "__main__":
    unittest.main()
