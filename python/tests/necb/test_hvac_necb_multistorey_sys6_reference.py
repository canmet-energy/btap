"""P4 gate: the FIXTURE MONOCULTURE gap for multi-storey selection. Every other
reference_hvac test in this repo (including test_hvac_necb_reference's own
test_three_storey_office_to_sys6) runs on the single-storey 5-zone office
fixture and FAKES 3 storeys by overriding `building={'storeys': 3, ...}` —
the storeys count never comes from real geometry, so `_building_info`'s
`costing.hvac.geometry.above_ground_storeys(model)` auto-derivation path has
never been exercised for a System 6 selection, and no test has ever built a
REAL multi-storey zone stack through this path.

This file builds an actual >=3-storey model with btap.modeling's bar engine
(which tags space types with real NECB catalog names in the same step), runs
reference_hvac with NO storeys override, and asserts:
 1. the auto-derived storey count really is >= 3 and General Area zones
    select System 6 (not System 3);
 2. the built System 6 supply fan's total efficiency is 0.55 — asserted
    NOWHERE in the existing suite (test_hvac_necb_reference's sys6 test only
    checks supply pressureRise, never supply efficiency, even though it
    checks BOTH for the return fan)."""

from __future__ import annotations

import re
import unittest

import btap.modeling as modeling
from btap.audit import AuditLog
from btap.costing.hvac import geometry
from btap.necb import hvac, loads
from tests.necb.hvac_helpers import sorted_zones
from tests.support import needs_sdk


@needs_sdk
class TestNecbMultistoreySys6Reference(unittest.TestCase):

    def multistorey_proposed_model(self):
        """A real 3-storey office bar, tagged with the exact catalog office name in
        the SAME step (modeling.bar's ratio-tagging), loads applied (thermostats —
        build_system refuses zones without one), then a proposed HVAC system built
        on every zone."""
        model = modeling.bar(
            space_type_ratios={('Space Function', 'Office enclosed > 25 m2'): 1.0},
            length=40.0, width=20.0, num_stories_above_grade=3, wwr=0.3)
        loads.apply_loads(model, vintage='2020')
        modeling.build_system(model, 'Baseboard gas boiler', sorted_zones(model))
        return model

    def test_three_storey_bar_geometry_selects_system_6_not_system_3(self):
        model = self.multistorey_proposed_model()
        derived_storeys = geometry.above_ground_storeys(model)
        self.assertGreaterEqual(derived_storeys, 3,
                                'fixture precondition: real geometry, not a storeys override')

        audit = AuditLog()
        result = hvac.reference_hvac(model, vintage='2020', audit=audit)

        self.assertEqual(['General Area'], sorted({a.category for a in result.assignments}),
                         'bar-tagged Office enclosed > 25 m2 zones must vote General Area')
        self.assertEqual([6], sorted({a.reference_system for a in result.assignments}),
                         '>=3 storeys -> System 6 (Table 8.4.4.7.-A), not System 3')
        self.assertTrue(len(result.model.getFanVariableVolumes()),
                        'System 6 is VAV — variable-volume fans expected')

    # The gap this closes: supply-fan efficiency was asserted NOWHERE for System
    # 6 anywhere in the repo (test_hvac_necb_reference's sys6 test asserts supply
    # pressureRise and BOTH return pressureRise/efficiency, but never supply
    # efficiency). fans['system_6']['supply_efficiency'] in
    # data/reference_rules_2020.json declares 0.55 (8.4.4.18.(4)); assert
    # the BUILT model actually carries that value.
    def test_system_6_supply_fan_total_efficiency_matches_the_declared_0_55(self):
        model = self.multistorey_proposed_model()
        result = hvac.reference_hvac(model, vintage='2020')

        declared = hvac.rules('2020')['fans']['system_6']['supply_efficiency']
        self.assertAlmostEqual(0.55, declared, delta=1e-9,
                               msg='sanity: the data file still declares 0.55')

        supply_fans = [f for f in result.model.getFanVariableVolumes()
                       if not re.search(r'return', f.nameString(), re.IGNORECASE)]
        self.assertTrue(supply_fans, 'System 6 must have built supply fans')
        for fan in supply_fans:
            self.assertAlmostEqual(1000.0, fan.pressureRise(), delta=0.1,
                                   msg=f'{fan.nameString()}: supply pressure')
            self.assertAlmostEqual(
                declared, fan.fanTotalEfficiency(), delta=1e-6,
                msg=f'{fan.nameString()}: built supply fan total efficiency must match the '
                    'declared 8.4.4.18.(4) value (fans.system_6.supply_efficiency) — if this '
                    'ever mismatches, that is a FINDING against _apply_fan_rules '
                    '(necb/hvac/reference.py), not this test.')


if __name__ == '__main__':
    unittest.main()
