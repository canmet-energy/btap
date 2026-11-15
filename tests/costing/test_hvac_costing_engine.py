"""Port of btap-costing/test/test_hvac_costing_engine.rb: the cost database
(vendored data, record lookup, regional factors, closest location, custom
costs override) and the ledger (pricing math, categories, assemblies)."""

import tempfile
import unittest
from pathlib import Path

from btap.costing.hvac.database import Database
from btap.costing.hvac.ledger import Ledger


class TestCostingEngine(unittest.TestCase):
    @property
    def db(self):
        if not hasattr(self, '_db'):
            self._db = Database()
        return self._db

    def test_database_loads_vendored_data(self):
        self.assertGreater(len(self.db.materials_hvac), 1000)
        self.assertGreater(len(self.db.ahu_assemblies), 500)
        self.assertGreater(len(self.db.locations), 10)
        self.assertIsInstance(self.db.mech_sizing, list)
        self.assertTrue(any(c['component'] == 'piping' for c in self.db.mech_sizing))

    def test_cost_record_and_missing_id(self):
        rec = self.db.cost_record('240001')
        self.assertGreater(rec['materialOpCost'], 0)
        with self.assertRaises(ValueError):
            self.db.cost_record('NO_SUCH_ID')

    def test_regional_factors_match_and_fallback(self):
        mat, inst, _ = self.db.regional_factors('ONTARIO', 'BARRIE', '017777')
        self.assertEqual([100.0, 100.0], [mat, inst],
                         'Barrie prefix 01 factors are 100/100')
        mat, inst, _ = self.db.regional_factors('NOWHERE', 'NOCITY', '017777')
        self.assertEqual([100.0, 100.0], [mat, inst])
        self.assertTrue(any('NOCITY' in w for w in self.db.warnings),
                        'fallback records a warning')

    def test_closest_location(self):
        loc = self.db.closest_location(43.65, -79.38)  # downtown Toronto
        self.assertEqual('TORONTO', loc['city'].upper())

    def test_custom_costs_csv_overrides(self):
        custom = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', prefix='costs',
                                             delete=False)
        try:
            custom.write('id,sheet,source,description,city,province_state,'
                         'materialOpCost,laborOpCost,equipmentOpCost\n')
            custom.write('240001,materials_glazing,custom,test,,,999.0,1.0,0.0\n')
            custom.close()
            custom_db = Database(costs_csv=custom.name)
            self.assertAlmostEqual(999.0, custom_db.cost_record('240001')['materialOpCost'],
                                   delta=1e-6)
            self.assertGreater(custom_db.cost_record('240002')['materialOpCost'], 0,
                               'non-overridden ids still present')
        finally:
            Path(custom.name).unlink(missing_ok=True)

    def test_ledger_pricing_math_and_categories(self):
        ledger = Ledger()
        ledger.add(id='240001', quantity=2, tags=['HEATING_COOLING'])
        rec = self.db.cost_record('240001')
        result = ledger.price(self.db, province_state='ONTARIO', city='TORONTO')
        mat_f, inst_f, _ = self.db.regional_factors('ONTARIO', 'TORONTO', '240001')
        expected = (rec['materialOpCost'] * mat_f / 100.0 +
                    rec['laborOpCost'] * inst_f / 100.0) * 2
        self.assertAlmostEqual(expected, result['total'], delta=0.01)
        self.assertAlmostEqual(expected, result['by_category']['HEATING_COOLING'],
                               delta=0.01)

    def test_assembly_expansion(self):
        ledger = Ledger()
        ledger.add_assembly(id_layers='301,850', layer_multipliers='1,.5',
                            base_quantity=4, tags=['VENTILATION'])
        quantities = {i['id']: i['quantity'] for i in ledger.items}
        self.assertEqual(4.0, quantities['301'])
        self.assertEqual(2.0, quantities['850'])

    def test_zero_quantities_skipped(self):
        ledger = Ledger()
        ledger.add(id='240001', quantity=0, tags=['ZONAL'])
        self.assertEqual([], ledger.items)


if __name__ == '__main__':
    unittest.main()
