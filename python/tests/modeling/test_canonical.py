"""The consolidated canonical naming grammar: <primary>[ + <zone equipment>][ (<plant>)],
GENERATED from each row's structured config, resolvable alongside the legacy names."""

import unittest
from collections import Counter

import btap.modeling as modeling
from btap.modeling.hvac import canonical, catalog


class TestCanonical(unittest.TestCase):
    def test_all_canonical_names_unique_and_disjoint_from_legacy(self):
        rows = catalog.rows()
        canon = [canonical.name(r) for r in rows]
        collisions = [n for n, c in Counter(canon).items() if c > 1]
        self.assertEqual(len(rows), len(set(canon)),
                         f"canonical collisions: {collisions}")
        legacy = [r['name'] for r in rows]
        self.assertEqual(sorted(set(canon) & set(legacy)), [],
                         'canonical names must not shadow legacy names')

    def test_consolidation_examples(self):
        # the user's example pair: CBECS fuel-first vs NECB medium-first now share one grammar
        self.assertEqual('hot water baseboards (gas boiler)',
                         self.canonical_for('Baseboard gas boiler'))
        self.assertEqual(
            'packaged single-zone DX with gas heat + hot water baseboards (gas boiler)',
            self.canonical_for('PSZ RTU Gas and DX Coils and Hot Water Baseboard'))
        self.assertEqual('DOAS ASHP + zone PTHPs', self.canonical_for('hs11_ashp_pthp'))
        self.assertEqual('electric baseboards', self.canonical_for('Baseboard electric'))

    def test_composites_derive_from_parts(self):
        canon = self.canonical_for('DOAS with fan coil chiller with boiler')
        self.assertIn('DOAS ventilation', canon)
        self.assertIn('four-pipe fan coils', canon)

    def test_listing_includes_canonical_and_filter_matches_it(self):
        rows = modeling.systems()
        self.assertTrue(all(isinstance(r['canonical_name'], str) and r['canonical_name']
                            for r in rows))
        hits = modeling.systems(filter='packaged single-zone')
        self.assertTrue(hits, 'filter should match canonical names too')

    @unittest.skip('needs systems wave (M3)')
    def test_resolve_and_build_by_canonical_name(self):
        from btap._compat import sorted_by_name
        from tests.support import load_fixture

        config = catalog.resolve('hot water baseboards (gas boiler)')
        self.assertEqual('Baseboard gas boiler', config['name'])

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'hot water baseboards (gas boiler)', zones)
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(2, len(model.getBoilerHotWaters()))

    def canonical_for(self, legacy_name):
        row = next((r for r in catalog.rows() if r['name'] == legacy_name), None)
        self.assertIsNotNone(row, f"no catalog row named '{legacy_name}'")
        return canonical.name(row)


if __name__ == '__main__':
    unittest.main()
