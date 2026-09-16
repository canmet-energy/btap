"""D-91: zone equipment dispatch in one-unit-per-block System 3/4 references.

With the legacy creation order the baseboard is `SequentialLoad` priority 1: it
answers the zone load predicted before the supply air arrives, and the always-on
constant-volume rooftop then delivers outdoor-air-cooled air with little load left
to meet — the corpus 01 reference missed its heating setpoint for ~800 occupied
hours. D-91 offers the full load to the rooftop terminal first, in both orders,
and lets the baseboard serve the residual.

Pinned here: the scheme, both priorities and all four sequential fractions are set
explicitly (a proposed `UniformLoad` scheme survives the clone and teardown); the
rule reaches only zones with their own System 3/4 loop holding exactly one
constant-volume terminal and one baseboard; shared units and System 6 are left
alone; and every application is an audited D-91 decision citing the edition's
terminal/secondary capacity article and 8.4.2.10.(2).
"""

import unittest

from btap.audit import AuditLog
from btap.codes.necb import hvac
from tests.necb.hvac_helpers import proposed_with_hvac
from tests.support import needs_sdk

CONSTANT_VOLUME_TERMINALS = ('OS_AirTerminal_SingleDuct_ConstantVolume_NoReheat',
                             'OS_AirTerminal_SingleDuct_Uncontrolled')
ARTICLE = {'necb2020': '8.4.4.9.(3); 8.4.2.10.(2)', 'necb2025': '8.4.5.9.(3); 8.4.2.10.(2)'}


def build_reference(proposed, code='necb2025', storeys=1):
    audit = AuditLog()
    result = hvac.reference_hvac(proposed, code=code, building={'storeys': storeys}, audit=audit)
    return result.model, audit


def types(sequence):
    return [e.iddObjectType().valueName() for e in sequence]


def dispatch_decisions(audit):
    return [e for e in audit.entries if e.get('ruling') == 'D-91']


@needs_sdk
class TestZoneDispatch(unittest.TestCase):

    def assert_air_terminal_first(self, zone):
        self.assertEqual('SequentialLoad', zone.loadDistributionScheme(), zone.nameString())
        for sequence in (zone.equipmentInHeatingOrder(), zone.equipmentInCoolingOrder()):
            kinds = types(sequence)
            self.assertEqual(2, len(kinds), zone.nameString())
            self.assertIn(kinds[0], CONSTANT_VOLUME_TERMINALS, zone.nameString())
            self.assertIn('Baseboard', kinds[1], zone.nameString())
        for component in zone.equipmentInHeatingOrder():
            self.assertAlmostEqual(1.0, float(zone.sequentialHeatingFraction(component)))
            self.assertAlmostEqual(1.0, float(zone.sequentialCoolingFraction(component)))

    def test_one_unit_per_zone_system_3_runs_the_air_terminal_first(self):
        for code in ('necb2020', 'necb2025'):
            with self.subTest(code=code):
                reference, audit = build_reference(proposed_with_hvac('Baseboard gas boiler'),
                                                   code=code)
                loops = list(reference.getAirLoopHVACs())
                self.assertTrue(loops)
                self.assertTrue(all(len(loop.thermalZones()) == 1 for loop in loops))
                for zone in reference.getThermalZones():
                    self.assert_air_terminal_first(zone)
                decisions = dispatch_decisions(audit)
                self.assertEqual(len(loops), len(decisions))
                for entry in decisions:
                    self.assertEqual('decision', entry['level'])
                    self.assertEqual(ARTICLE[code], entry['article'])
                    self.assertEqual(3, entry['inputs']['reference_system'])
                    self.assertIn('accepted', entry['value'])

    def test_a_non_sequential_proposed_scheme_is_overwritten(self):
        proposed = proposed_with_hvac('Baseboard gas boiler')
        for zone in proposed.getThermalZones():
            zone.setLoadDistributionScheme('UniformLoad')
        reference, _ = build_reference(proposed)
        for zone in reference.getThermalZones():
            self.assert_air_terminal_first(zone)

    def test_a_shared_system_3_unit_is_left_alone(self):
        proposed = proposed_with_hvac('PSZ RTU Gas and DX Coils and Hot Water Baseboard')
        reference, audit = build_reference(proposed)
        loops = list(reference.getAirLoopHVACs())
        self.assertTrue(any(len(loop.thermalZones()) > 1 for loop in loops),
                        'fixture precondition: one unit serving several zones')
        self.assertFalse(dispatch_decisions(audit))
        for zone in reference.getThermalZones():
            self.assertIn('Baseboard', types(zone.equipmentInHeatingOrder())[0])

    def test_a_system_4_zone_exhaust_fan_does_not_block_dispatch(self):
        # Sol, PR #49 P1: teardown keeps FanZoneExhaust (code-required exhaust),
        # and a kitchen hood selects System 4 — the exhaust fan is not
        # conditioning equipment, so it must not make the zone ineligible.
        import openstudio

        proposed = proposed_with_hvac('Baseboard gas boiler')
        for space_type in proposed.getSpaceTypes():
            if space_type.spaces():
                space_type.setStandardsSpaceType('Food preparation area')
        zones = sorted(proposed.getThermalZones(), key=lambda z: z.nameString())
        for zone in zones:
            openstudio.model.FanZoneExhaust(proposed).addToThermalZone(zone)

        audit = AuditLog()
        result = hvac.reference_hvac(
            proposed, code='necb2025', audit=audit,
            building={'storeys': 1, 'kitchen_hood_zones': [z.nameString() for z in zones]})
        reference = result.model
        self.assertEqual({4}, {a.reference_system for a in result.assignments},
                         'fixture precondition: hooded food preparation selects System 4')
        decisions = dispatch_decisions(audit)
        self.assertEqual(len(zones), sum(e['inputs']['zones'] for e in decisions))
        self.assertTrue(all(e['inputs']['reference_system'] == 4 for e in decisions))
        for zone in reference.getThermalZones():
            self.assertEqual('SequentialLoad', zone.loadDistributionScheme())
            for sequence in (zone.equipmentInHeatingOrder(), zone.equipmentInCoolingOrder()):
                kinds = types(sequence)
                self.assertIn(kinds[0], CONSTANT_VOLUME_TERMINALS, zone.nameString())
                self.assertIn('Baseboard', kinds[1], zone.nameString())
                self.assertEqual('OS_Fan_ZoneExhaust', kinds[2], zone.nameString())

    def test_system_6_is_left_alone(self):
        reference, audit = build_reference(proposed_with_hvac('Baseboard gas boiler'), storeys=3)
        self.assertFalse(dispatch_decisions(audit))
        self.assertTrue(any('VAV_Reheat' in kind for zone in reference.getThermalZones()
                            for kind in types(zone.equipmentInHeatingOrder())),
                        'fixture precondition: a System 6 VAV reheat reference')


if __name__ == '__main__':
    unittest.main()
