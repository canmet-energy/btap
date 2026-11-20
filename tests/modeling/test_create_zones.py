"""`modeling.create` zones what it creates (#237).

The ported wizards made SPACES but no thermal zones, unlike `bar()` and
`create_from_footprint()`. A zoneless model took no thermostats from the NECB
loads pass, and EnergyPlus drops every surface of one while reporting success:
an empty building simulated cleanly. A user only found out at `build_system`,
from "zones must be a non-empty Array of ThermalZones".
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk

SHAPES = [("rectangle", {"length": 30, "width": 20, "storeys": 2}),
          ("l", {"length": 40, "width": 30, "storeys": 2}),
          ("courtyard", {}), ("h", {}), ("t", {}), ("u", {}), ("aspect_ratio", {})]


@needs_sdk
class TestEveryCreatedSpaceIsZoned(unittest.TestCase):

    def test_each_shape(self):
        from btap import modeling
        self.assertEqual({s for s, _ in SHAPES}, set(modeling.SHAPES))
        for shape, kw in SHAPES:
            with self.subTest(shape=shape):
                model = modeling.create(shape=shape, **kw)
                spaces = list(model.getSpaces())
                self.assertTrue(spaces)
                self.assertEqual([], [s.nameString() for s in spaces
                                      if not s.thermalZone().is_initialized()])
                zone = spaces[0].thermalZone().get()
                self.assertEqual(f"Zone {spaces[0].nameString()}", zone.nameString())

    def test_a_callers_existing_space_is_left_alone(self):
        import openstudio

        from btap import modeling
        model = openstudio.model.Model()
        mine = openstudio.model.Space(model)
        modeling.create(shape="rectangle", model=model, length=20, width=10, storeys=1)
        self.assertFalse(mine.thermalZone().is_initialized())
        self.assertGreater(len(model.getThermalZones()), 0)

    def test_the_audit_records_the_zones_created(self):
        from btap import modeling
        from btap.audit import AuditLog
        audit = AuditLog()
        model = modeling.create(shape="l", length=40, width=30, storeys=2, audit=audit)
        entry = next(e for e in audit.entries if e["action"] == "l massing created")
        self.assertEqual(len(model.getThermalZones()), entry["inputs"]["thermal_zones_created"])


if __name__ == "__main__":
    unittest.main()
