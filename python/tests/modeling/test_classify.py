"""P1 gate: modeling.characterize round-trips every catalog family (build ->
characterize recovers family/energy facts) and classifies foreign OSMs
structurally. (Port of btap-modeling/test/test_classify.rb.)"""

import json
import unittest

import btap.modeling as modeling
from btap.audit import AuditLog
from tests.support import load_fixture, needs_sdk

# family -> (catalog name, expectations)
ROUND_TRIP = {
    'baseboards': ('Baseboard gas boiler',
                   {'heated': True, 'cooled': False, 'heat_fuel': 'NaturalGas', 'air_loop': False}),
    'psz': ('PSZ RTU Gas and DX Coils and Electric Baseboard',
            {'heated': True, 'cooled': True, 'heat_fuel': 'NaturalGas',
             'cool_fuel': 'Electricity', 'air_loop': True}),
    'vav_reheat': ('MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard',
                   {'heated': True, 'cooled': True, 'heat_fuel': 'NaturalGas',
                    'terminal': 'vav_reheat', 'air_loop': True}),
    'fan_coils': ('FPFC MAU DX Coils with Scroll Chiller',
                  {'heated': True, 'cooled': True, 'air_loop': True}),
    'mau_ptac': ('PSZ MAU Electric and DX Coils and Electric Baseboard with PTAC',
                 {'heated': True, 'cooled': True, 'air_loop': True}),
    'zone_terminal': ('PTHP', {'heated': True, 'cooled': True, 'heat_pump': True, 'air_loop': False}),
    'unit_heaters': ('Gas unit heaters',
                     {'heated': True, 'cooled': False, 'heat_fuel': 'NaturalGas', 'air_loop': False}),
    'furnace': ('Forced air furnace', {'heated': True, 'air_loop': True}),
    'evap_cooler': ('Direct evap coolers with no heat', {'cooled': True, 'air_loop': True}),
    'wshp': ('Water source heat pumps',
             {'heated': True, 'cooled': True, 'heat_pump': True, 'air_loop': False}),
    'doas': ('DOAS ventilation only', {'air_loop': True}),
    'vrf': ('VRF', {'heated': True, 'cooled': True, 'heat_pump': True, 'air_loop': False}),
    'doas_pthp': ('hs11_ashp_pthp', {'heated': True, 'cooled': True, 'heat_pump': True}),
    'ecm_ashp_baseboard': ('hs12_ashp_baseboard', {'heated': True}),
    'ecm_doas_vrf': ('hs08_ccashp_vrf', {'heated': True, 'cooled': True, 'heat_pump': True}),
    'ecm_hp_fancoils': ('hs15_cawhp_fancoils', {'heated': True, 'cooled': True}),
}


@needs_sdk
class TestClassify(unittest.TestCase):
    def build_and_characterize(self, name, audit=None):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, name, zones)
        return model, modeling.characterize(model, audit=audit)

    def test_round_trip_all_families(self):
        failures = []
        for family, (name, expect) in ROUND_TRIP.items():
            try:
                _, facts = self.build_and_characterize(name)
                groups = facts['zone_groups']
                air_groups = [g for g in groups if g['air_loop']]

                if expect.get('air_loop'):
                    if not air_groups:
                        failures.append(f"{family}: no air-loop group")
                    # gem fast path must recognize the catalog name on at least one loop
                    if not any(g['family'] == family or (family == 'furnace' and g['family'])
                               for g in air_groups):
                        families = sorted({g['family'] for g in air_groups}, key=str)
                        failures.append(
                            f"{family}: catalog name not recognized (families: {families})")
                if expect.get('heated') and not any(g['heated'] for g in groups):
                    failures.append(f"{family}: heated not detected")
                if expect.get('cooled') and not any(g['cooled'] for g in groups):
                    failures.append(f"{family}: cooled not detected")
                if expect.get('heat_pump') and not any(g['heat_pump'] for g in groups):
                    failures.append(f"{family}: heat pump not detected")
                if (expect.get('heat_fuel') and
                        not any(expect['heat_fuel'] in g['heating_energy_types'] for g in groups)):
                    seen = sorted({f for g in groups for f in g['heating_energy_types']})
                    failures.append(
                        f"{family}: heating fuel {expect['heat_fuel']} missing ({seen})")
                if (expect.get('cool_fuel') and
                        not any(expect['cool_fuel'] in g['cooling_energy_types'] for g in groups)):
                    failures.append(f"{family}: cooling fuel {expect['cool_fuel']} missing")
                if (expect.get('terminal') and
                        not any(g['terminal_type'] == expect['terminal'] for g in groups)):
                    failures.append(f"{family}: terminal {expect['terminal']} missing")
            except Exception as e:  # the Ruby rescues StandardError per family
                failures.append(f"{family} ({name}): {type(e).__name__} {e}")
        self.assertEqual([], failures, '\n'.join(failures))

    def test_gem_built_flag_and_composite(self):
        _, facts = self.build_and_characterize('DOAS with fan coil chiller with boiler')
        self.assertTrue(facts['built_by_gem'], 'composite parts stamp resolvable catalog names')
        self.assertTrue(any(g['heated'] and g['cooled'] for g in facts['zone_groups']))

    def test_foreign_model_structural_classification(self):
        model, _ = self.build_and_characterize(
            'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard')
        for i, al in enumerate(model.getAirLoopHVACs()):
            al.setName(f"Building HVAC {i + 1}")
        facts = modeling.characterize(model)

        self.assertFalse(facts['built_by_gem'])
        group = next(g for g in facts['zone_groups'] if g['air_loop'])
        self.assertIsNone(group['catalog_name'])
        self.assertEqual('multizone_vav', group['family_guess'])
        self.assertTrue(group['heated'] and group['cooled'])
        self.assertIn('NaturalGas', group['heating_energy_types'])  # via boiler on the HW loop

    def test_purchased_energy_detected(self):
        _, facts = self.build_and_characterize('Baseboard district hot water')
        self.assertTrue(facts['purchased_energy']['heating'],
                        'district hot water = purchased heating energy')
        group = facts['zone_groups'][0]
        self.assertIn('Purchased', group['heating_energy_types'])

    def test_design_cooling_kw_and_audit(self):
        audit = AuditLog()
        model, facts = self.build_and_characterize(
            'PSZ RTU Electric and DX Coils and Electric Baseboard', audit=audit)

        cooled = [g for g in facts['zone_groups'] if g['cooled']]
        self.assertTrue(all(g['design_cooling_kw'] is None for g in cooled),
                        'unsized -> nil, never a partial sum')
        self.assertTrue(any('cooling capacity unsized' in w['action'] for w in audit.warnings))

        for c in model.getCoilCoolingDXSingleSpeeds():
            c.setRatedTotalCoolingCapacity(10_000.0)
        facts2 = modeling.characterize(model)
        cooled2 = [g for g in facts2['zone_groups'] if g['cooled']]
        self.assertTrue(all(abs(g['design_cooling_kw'] - 10.0) < 0.01 for g in cooled2))

        # audit is serializable both ways
        parsed = json.loads(audit.to_json())
        self.assertTrue(isinstance(parsed, list) and parsed)
        self.assertIn('characterize', str(audit))
        self.assertTrue(any(e.get('evidence') for e in audit.entries),
                        'evidence recorded for conclusions')

    def test_plants_classified(self):
        _, facts = self.build_and_characterize(
            'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard')
        types = [p['type'] for p in facts['plants']]
        self.assertIn('hot_water', types)
        self.assertIn('chilled_water', types)
        hw = next(p for p in facts['plants'] if p['type'] == 'hot_water')
        self.assertIn('NaturalGas', hw['fuels'])


if __name__ == '__main__':
    unittest.main()
