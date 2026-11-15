import unittest

import btap.modeling as modeling
from btap.modeling.hvac import catalog


class TestCatalog(unittest.TestCase):
    def test_list_all(self):
        rows = modeling.systems()
        self.assertGreaterEqual(len(rows), 8)
        self.assertTrue(all(r.get('name') and r.get('family') for r in rows))

    def test_list_filtered(self):
        gas = modeling.systems(filter='Gas')
        self.assertTrue(gas)
        self.assertTrue(
            all('gas' in r['name'].lower() or 'gas' in r['canonical_name'].lower()
                for r in gas),
            'filter matches legacy or canonical names, case-insensitively')

        psz = modeling.systems(family='psz')
        self.assertTrue(psz)
        self.assertTrue(all(r['family'] == 'psz' for r in psz))

    def test_resolve_merges_sizing_block(self):
        config = catalog.resolve('PSZ RTU Gas and DX Coils and Hot Water Baseboard')
        self.assertEqual('psz', config['family'])
        self.assertEqual('Gas', config['heating_coil_type'])
        self.assertEqual(True, config['needs_boiler'])
        self.assertIsInstance(config['sizing'], dict)
        self.assertEqual('TemperatureDifference',
                         config['sizing']['zone_cooling_design_supply_air_temperature_input_method'])
        self.assertEqual(1.1, config['sizing']['zone_cooling_sizing_factor'])

    def test_unknown_name_raises_with_suggestions(self):
        with self.assertRaises(ValueError) as ctx:
            catalog.resolve('PSZ Gas Rooftop Thing')
        self.assertRegex(str(ctx.exception), r'unknown system name')
        self.assertRegex(str(ctx.exception), r'PSZ RTU')  # suggestions included


if __name__ == '__main__':
    unittest.main()
