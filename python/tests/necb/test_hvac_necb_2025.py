"""NECB 2025 vintage: same reference-rule VALUES as 2020 but the performance path moved
from Subsection 8.4.4 to 8.4.5 (verified via the codes MCP edition diff). Selections
must be identical across vintages while citations carry the 2025 article numbers.
Efficiencies are native 2025 (efficiencies_2025.json, transcribed from Tables
5.2.12.1.-K/-N/-O/-A): chillers/boilers/furnaces/unitary-AC ladder verified identical
to 2020; the two real changes are HP cooling <19 kW EER 11.0 -> SEER 15 and
split-system HP heating HSPF 7.4 -> 7.8."""

from __future__ import annotations

import re
import unittest

import btap.modeling as modeling
from btap._compat import sorted_by_name
from btap.necb import hvac
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk


def group(zones=None, heated=True, cooled=True, heat_fuels=None,
          heat_pump=False, cooling_kw=10.0):
    return {'zones': zones or ['Z1'], 'air_loop': 'L1', 'family': None,
            'catalog_name': None, 'family_guess': None,
            'heated': heated, 'cooled': cooled,
            'heating_energy_types': ['NaturalGas'] if heat_fuels is None else heat_fuels,
            'cooling_energy_types': ['Electricity'] if cooled else [],
            'heat_pump': heat_pump,
            'terminal_type': 'none', 'design_cooling_kw': cooling_kw, 'evidence': []}


def select(groups, zone_types, storeys=1, vintage='2025'):
    return hvac.select_reference_systems(
        facts={'built_by_gem': False, 'zone_groups': groups, 'plants': [],
               'purchased_energy': {'heating': False, 'cooling': False}},
        building={'storeys': storeys, 'zone_types': zone_types}, vintage=vintage)


@needs_sdk
class TestNecb2025(unittest.TestCase):

    # selections are identical across 2020/2025 for a spread of scenarios
    def test_2025_selections_match_2020(self):
        scenarios = [
            ([group()], {'Z1': 'Office - enclosed'}, 2),
            ([group()], {'Z1': 'Office - enclosed'}, 5),
            ([group(cooling_kw=25.0)], {'Z1': 'Data centre'}, 1),
            ([group()], {'Z1': 'Warehouse - med/blk'}, 1),
            ([group(heat_pump=True)], {'Z1': 'Office - enclosed'}, 1),
            ([group(heated=True, cooled=False, cooling_kw=0.0)],
             {'Z1': 'Multi-unit residential'}, 3),
        ]
        for groups, types_, storeys in scenarios:
            a20 = select([dict(g) for g in groups], types_, storeys=storeys, vintage='2020')
            a25 = select([dict(g) for g in groups], types_, storeys=storeys, vintage='2025')
            self.assertEqual([a.reference_system for a in a20],
                             [a.reference_system for a in a25],
                             f'selection diverged for {list(types_.values())[0]} @ {storeys} storeys')
            self.assertEqual([a.catalog_name for a in a20], [a.catalog_name for a in a25])
            self.assertEqual([a.action for a in a20], [a.action for a in a25])

    # 2025 citations carry the renumbered articles (8.4.5.x, Table 8.4.5.7.-A)
    def test_2025_article_renumbering(self):
        a = select([group(heat_pump=True)], {'Z1': 'Office - enclosed'})[0]
        joined = '; '.join(a.articles)
        self.assertRegex(joined, r'8\.4\.5\.7')
        self.assertRegex(joined, r'8\.4\.5\.13')
        self.assertNotRegex(joined, r'8\.4\.4\.\d',
                            '2020 article numbers must not leak into 2025 output')

        rules = hvac.rules('2025')
        self.assertEqual('8.4.5.8.(1)-(2)', rules['oversizing']['article'])
        self.assertEqual('2025', rules['provenance']['edition'])
        self.assertIsNone(rules['provenance'].get('efficiency_vintage_fallback'),
                          'fallback lifted')

    # end-to-end reference_hvac at vintage 2025: correct topology, native efficiencies,
    # and NO fallback warning
    def test_reference_hvac_2025_native_efficiencies(self):
        model = load_fixture()
        modeling.build_system(model, 'Baseboard gas boiler', sorted_zones(model))
        types_ = {z.nameString(): 'Office - enclosed' for z in model.getThermalZones()}

        result = hvac.reference_hvac(model, vintage='2025',
                                     building={'storeys': 1, 'zone_types': types_})

        self.assertEqual([3], sorted({a.reference_system for a in result.assignments}))
        self.assertTrue(len(result.model.getAirLoopHVACs()))
        selection = next(e for e in result.audit.entries
                         if e['step'] == 'selection' and e['level'] == 'decision')
        self.assertRegex(selection['article'], r'8\.4\.5')
        self.assertEqual([], [w for w in result.audit.warnings if 'fall back' in w['action']],
                         '2025 efficiencies are native — no fallback warning')

    def test_effective_vintage_native_for_both(self):
        for v in ('2020', '2025'):
            vintage, reason = hvac.efficiency.effective_vintage(v)
            self.assertEqual(v, vintage)
            self.assertIsNone(reason)

    # The two REAL 2025 efficiency changes (everything else verified identical to 2020):
    # HP cooling < 19 kW: EER 11.0 (2020) -> SEER 15 (2025 Table 5.2.12.1.-A merged class)
    def test_2025_small_heat_pump_cooling_is_seer_15(self):
        cops = {}
        for vintage in ('2020', '2025'):
            model = load_fixture()
            modeling.build_system(
                model,
                'PSZ RTU ASHP with Electric and ASHP with Electric Supp. Heat Coils and '
                'Electric Baseboard', sorted_zones(model))
            for c in model.getCoilCoolingDXSingleSpeeds():
                c.setRatedTotalCoolingCapacity(12_000.0)
            for c in model.getCoilHeatingDXSingleSpeeds():
                c.setRatedTotalHeatingCapacity(12_000.0)
            hvac.apply_efficiencies(model, vintage=vintage)
            coil = sorted_by_name(model.getCoilCoolingDXSingleSpeeds())[0]
            value = coil.ratedCOP()
            cops[vintage] = value.get() if hasattr(value, 'is_initialized') else value
        # 2020: eer_to_cop_no_fan(11.0) = ((11*0.29307)+0.12)/0.88 ~= 3.800
        self.assertAlmostEqual(3.800, cops['2020'], delta=0.01)
        # 2025: seer_to_cop_no_fan(15) = -0.0076*225 + 0.3796*15 = 3.984
        self.assertAlmostEqual(3.984, cops['2025'], delta=0.01)
        # heating side unchanged: 7.4 HSPF (Single Package) both vintages

    def test_2025_boiler_and_chiller_values_unchanged(self):
        model = load_fixture()
        modeling.build_system(
            model, 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard',
            sorted_zones(model))
        for b in model.getBoilerHotWaters():
            b.setNominalCapacity(100_000.0)
        for c in model.getChillerElectricEIRs():
            c.setReferenceCapacity(200_000.0)
        hvac.apply_efficiencies(model, vintage='2025')

        primary = next(b for b in model.getBoilerHotWaters() if 'Primary' in b.nameString())
        # -N: AFUE 90, unchanged
        self.assertAlmostEqual(0.90, primary.nominalThermalEfficiency(), delta=1e-6)
        chiller = sorted_by_name(model.getChillerElectricEIRs())[0]
        # -K Path B, unchanged
        self.assertAlmostEqual(3.517 / 0.77927, chiller.referenceCOP(), delta=1e-3)


if __name__ == '__main__':
    unittest.main()
