"""P1 gate: the vendored NECB loads data is structurally sound, equals the legacy
MERGED runtime tables, and matches MCP-verified code values.

Port of btap-necb/test/test_loads_data_integrity.rb. Its last case,
``test_structural_equality_vs_legacy_merged_tables``, compares against the LIVE
Ruby oracle; Python cannot load that, so its Leg-C equivalent lives in
``test_oracle_goldens_loads.py`` (the frozen ``loads_merged_tables.json``).
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk


@needs_sdk
class TestLoadsDataIntegrity(unittest.TestCase):
    SCHEDULE_CATEGORIES = ['Occupancy', 'Lighting', 'Electric-Equipment', 'Fan',
                           'Service Water Heating', 'Thermostat Setpoint-Heating',
                           'Thermostat Setpoint-Cooling']

    @property
    def space_types(self):
        from btap.necb import loads
        return loads.table('2020', 'space_types')

    @property
    def schedules(self):
        from btap.necb import loads
        return loads.table('2020', 'schedules')

    def test_counts_and_keys(self):
        self.assertEqual(308, len(self.space_types))
        self.assertEqual(80, len(self.space_types[0].keys()))
        self.assertEqual(240, len(self.schedules))
        for key in ['building_type', 'space_type', 'occupancy_per_area',
                    'electric_equipment_per_area', 'ventilation_per_area',
                    'ventilation_per_person', 'occupancy_schedule',
                    'heating_setpoint_schedule', 'necb_schedule_type']:
            self.assertIn(key, self.space_types[0], f"space-type records carry {key}")

    def test_schedule_letters_have_complete_category_sets(self):
        by_name = {r['name'] for r in self.schedules}
        for letter in 'ABCDEFGHI':
            for category in self.SCHEDULE_CATEGORIES:
                name = f"NECB-{letter}-{category}"
                self.assertIn(name, by_name, f"{name} present")
        self.assertIn('NECB-Activity', by_name)
        self.assertIn('Always On', by_name)

    def test_every_space_type_schedule_reference_resolves(self):
        names = {r['name'] for r in self.schedules}
        missing = []
        for st in self.space_types:
            for key in ['occupancy_schedule', 'occupancy_activity_schedule',
                        'electric_equipment_schedule', 'infiltration_schedule',
                        'heating_setpoint_schedule', 'cooling_setpoint_schedule']:
                ref = st[key]
                if ref is not None and ref not in names:
                    missing.append(f"{st['space_type']}: {key}={ref}")
        self.assertEqual([], missing, f"dangling schedule references: {missing[:5]}")

    def test_mcp_verified_schedule_a_values(self):
        # Table A-8.4.3.2.(1)-A (2020) == A-8.4.3.2.(1)(b)-A (2025), cell-verified via MCP:
        occ = next(r for r in self.schedules
                   if r['name'] == 'NECB-A-Occupancy' and r['day_types'] == 'Default|Wkdy')
        self.assertEqual([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.7, 0.9, 0.9, 0.9, 0.5, 0.5,
                          0.9, 0.9, 0.9, 0.7, 0.3, 0.1, 0.1, 0.1, 0.1, 0.0],
                         [float(v) for v in occ['values']])

        # NOTE legacy transcription convention: all schedules are MIDNIGHT-FIRST —
        # values[0] corresponds to the code table's trailing "12" (midnight) column,
        # then 1a..11p. The 24-value multisets match the code table exactly.
        equip = next(r for r in self.schedules
                     if r['name'] == 'NECB-A-Electric-Equipment'
                     and r['day_types'] == 'Default|Wkdy')
        self.assertEqual([0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.3, 0.8, 0.9, 0.9, 0.9, 0.9, 0.9,
                          0.9, 0.9, 0.9, 0.9, 0.5, 0.3, 0.3, 0.2, 0.2, 0.2],
                         [float(v) for v in equip['values']])

        heat = next(r for r in self.schedules
                    if r['name'] == 'NECB-A-Thermostat Setpoint-Heating'
                    and r['day_types'] == 'Default|Wkdy')
        self.assertEqual([18.0] * 6 + [20.0] + [22.0] * 14 + [18.0] * 3,
                         [float(v) for v in heat['values']])

        sat = next(r for r in self.schedules
                   if r['name'] == 'NECB-A-Occupancy' and 'Sat' in r['day_types'])
        self.assertEqual([0.0] * 24, [float(v) for v in sat['values']],
                         'schedule A Saturdays unoccupied')

    def test_mcp_verified_load_densities(self):
        # Table A-8.4.3.2.(2)-B: Office 20 m2/occupant + 7.5 W/m2 receptacle, schedule A.
        # Legacy IP: people/1000ft2 = 1000/(20 x 10.7639) = 4.645; W/ft2 = 7.5/10.7639.
        office = next((r for r in self.space_types
                       if r['building_type'] == 'Space Function'
                       and r['space_type'] == 'Office enclosed > 25 m2'), None)
        self.assertIsNotNone(office)
        self.assertAlmostEqual(1000.0 / (20 * 10.7639), float(office['occupancy_per_area']),
                               delta=0.05)
        self.assertAlmostEqual(7.5 / 10.7639, float(office['electric_equipment_per_area']),
                               delta=0.01)
        self.assertEqual('A', office['necb_schedule_type'])

        # Computer/Server room: 100 m2/occupant, 200 W/m2 receptacle (per-schedule variants)
        server = next((r for r in self.space_types
                       if r['space_type'] == 'Computer/Server room-sch-A'
                       and r['building_type'] == 'Space Function'), None)
        self.assertIsNotNone(server)
        self.assertAlmostEqual(200 / 10.7639, float(server['electric_equipment_per_area']),
                               delta=0.05)

    def test_2025_aliases_2020_with_renumbered_citations(self):
        from btap.necb import loads
        rules = loads.rules('2025')
        self.assertEqual('2020', loads.data_vintage('2025'))
        self.assertEqual('A-8.4.3.2.(1)(b)', rules['schedule_table_prefix'])
        self.assertEqual('A-8.4.3.2.(1)', loads.rules('2020')['schedule_table_prefix'])
        self.assertRegex(rules['provenance']['method'], 'row-by-row')
        self.assertEqual(len(loads.table('2020', 'space_types')),
                         len(loads.table('2025', 'space_types')))

    def test_coverage_manifest_lint(self):
        from btap.necb import loads
        for vintage in ('2020', '2025'):
            coverage = loads.rules(vintage)['article_coverage']['articles']
            # 5 core 8.4.3 entries + 8.4.2.7. internal loads (ffb58bc38) + 8.4.3.6.
            # outdoor air (f42f19533) — bump this pin when the manifest grows.
            # 8.4.3.2. is declared per sentence (3 rows) since the coverage-depth pass.
            self.assertEqual(9, len(coverage),
                             f"{vintage}: subsection 8.4.3 + shared entries accounted")
            # The per-sentence split preserves the cross-gem delegation honesty: the
            # schedule sentence still names both sibling gems in its gaps.
            article = next(a for a in coverage if a['article'] == '8.4.3.2.(1)')
            self.assertEqual('partial', article['status'],
                             'honest: lighting + SHW schedules delegated')
            self.assertRegex(article['gaps'], 'lighting')
            self.assertRegex(article['gaps'], 'shw')
            semi = next(a for a in coverage if a['article'] == '8.4.3.2.(3)')
            self.assertEqual('modeller', semi['gap_owner'],
                             '(3) set-point-from-specs is a modeller input')
            for a in coverage:
                self.assertIn(a['status'], ['implemented', 'partial', 'not_implemented',
                                            'satisfied_by_clone', 'host_scope'])
                self.assertTrue(a.get('gaps') or a.get('how'), f"{a['article']}: has how/gaps")

    def test_space_type_lookup_api(self):
        from btap.necb import loads
        record = loads.SpaceTypes.record(building_type='Space Function',
                                         space_type='Office enclosed > 25 m2')
        self.assertEqual('A', record['necb_schedule_type'])
        with self.assertRaises(ValueError):
            loads.SpaceTypes.record(building_type='Nope', space_type='Nada')
        self.assertEqual(308, len(loads.SpaceTypes.list_pairs()))


if __name__ == '__main__':
    unittest.main()
