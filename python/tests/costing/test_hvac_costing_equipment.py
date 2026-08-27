"""Port of btap-costing/test/test_hvac_costing_equipment.rb.

C1 generic equipment costing: build (unsized) topologies, quantify
hard-sizeable pieces, and verify ledger contents. (Capacity-dependent items
are exercised in the sized coverage test at C3; here we hard-size a few
objects to prove the pipeline.)"""

import re
import unittest

import btap.modeling as modeling
from btap.costing.hvac.database import Database
from btap.costing.hvac.ledger import Ledger
from btap.costing.hvac.quantify_equipment import EquipmentQuantifier
from tests.costing.support import load_fixture, needs_sdk


def _note(item):
    return str(item.get('note', ''))


@needs_sdk
class TestCostingEquipment(unittest.TestCase):
    def quantify(self, model):
        db = Database()
        ledger = Ledger()
        quantifier = EquipmentQuantifier(db, ledger)
        quantifier.quantify_plant(model)
        quantifier.quantify_zonal(model)
        return ledger, quantifier

    def sorted_zones(self, model):
        from btap._compat import sorted_by_name
        return sorted_by_name(model.getThermalZones())

    def test_pick_next_largest_and_multi_unit_fallback(self):
        db = Database()
        q = EquipmentQuantifier(db, Ledger())
        row, units = q.pick('GasBoilers', 50.0, 'test')
        self.assertEqual(59.5, float(row['Size']), 'smallest size >= 50 kW')
        self.assertEqual(1.0, units)

        row, units = q.pick('GasBoilers', 99_999.0, 'test')
        self.assertGreater(units, 1.0, 'oversize falls back to N x largest')

        self.assertIsNone(q.pick('NoSuchMaterial', 1, 'test'))
        self.assertTrue(any('NoSuchMaterial' in w for w in q.warnings))

    def test_boiler_bucketing_and_ledger_items(self):
        model = load_fixture()
        zones = self.sorted_zones(model)
        modeling.build_system(model, 'Baseboard gas boiler', zones)
        # hard-size so quantification works without a sizing run
        for b in model.getBoilerHotWaters():
            b.setNominalCapacity(50_000.0)  # 50 kW
        ledger, quantifier = self.quantify(model)

        boiler_items = [i for i in ledger.items
                        if re.fullmatch(r'boiler .* kW', _note(i))]
        self.assertEqual(2, len(boiler_items), 'primary + secondary')
        # geometry pass adds flue + fuel/electrical runs + header piping for
        # the boiler loop
        self.assertTrue(any('flue' in _note(i) for i in ledger.items),
                        'gas boiler flue costed')
        self.assertTrue(any('header piping' in _note(i) for i in ledger.items),
                        'header piping costed')
        # NECB boiler efficiency not applied (unsized) -> default eff -> bucket
        # varies; assert costed either way
        self.assertTrue(any('HEATING_COOLING' in i['tags'] for i in ledger.items))
        # HW baseboards produce ConvectCopper items with capacity warning
        # (unsized) or entries
        self.assertTrue(any('baseboard' in w for w in quantifier.warnings) or
                        any('baseboard' in _note(i) for i in ledger.items))

    def test_zonal_walk_covers_gem_families(self):
        model = load_fixture()
        zones = self.sorted_zones(model)
        modeling.build_system(model, 'PTHP', zones)
        for c in model.getCoilCoolingDXSingleSpeeds():
            c.setRatedTotalCoolingCapacity(5000.0)
        ledger, _ = self.quantify(model)

        pthp_items = [i for i in ledger.items if 'PTHP' in _note(i)]
        self.assertEqual(len(zones), len(pthp_items))
        self.assertTrue(all('ZONAL' in i['tags'] for i in pthp_items))

    def test_vrf_outdoor_and_terminals(self):
        model = load_fixture()
        zones = self.sorted_zones(model)
        modeling.build_system(model, 'VRF', zones)
        for u in model.getAirConditionerVariableRefrigerantFlows():
            u.setGrossRatedTotalCoolingCapacity(40_000.0)
        for c in model.getCoilCoolingDXVariableRefrigerantFlows():
            c.setRatedTotalCoolingCapacity(5000.0)
        ledger, _ = self.quantify(model)

        self.assertTrue(any('VRF outdoor' in _note(i) for i in ledger.items))
        terminals = [i for i in ledger.items if 'VRF terminal' in _note(i)]
        self.assertEqual(len(zones), len(terminals))

    def test_district_produces_warning_not_silent_zero(self):
        model = load_fixture()
        zones = self.sorted_zones(model)
        modeling.build_system(model, 'Baseboard district hot water', zones)
        _, quantifier = self.quantify(model)
        self.assertTrue(any('district' in w for w in quantifier.warnings))

    def test_priced_end_to_end_with_placeholders(self):
        model = load_fixture()
        zones = self.sorted_zones(model)
        modeling.build_system(model, 'Gas unit heaters', zones)
        for c in model.getCoilHeatingGass():
            c.setNominalCapacity(10_000.0)
        ledger, _ = self.quantify(model)
        db = Database()
        result = ledger.price(db, province_state='ONTARIO', city='TORONTO')
        self.assertGreater(result['total'], 0)
        self.assertGreater(result['by_category']['ZONAL'], 0)


if __name__ == '__main__':
    unittest.main()
