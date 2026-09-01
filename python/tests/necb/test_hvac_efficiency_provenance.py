"""D-59 — the vendored NECB 2020 equipment-efficiency values, pinned to the
PRINTED tables they were verified against (fetched via the codes MCP,
2026-08-02). Each assertion states the printed value and the unit conversion
that reaches the vendored one, so a future data regeneration that drifts
from the code text fails HERE with the printed number in the message.

SDK-free: reads the vendored JSON directly."""

from __future__ import annotations

import json
import pathlib
import re
import unittest

DATA_DIR = pathlib.Path(__file__).resolve().parents[2] / 'btap' / 'necb' / 'hvac' / 'data'

with open(DATA_DIR / 'efficiencies_2020.json', encoding='utf-8') as f:
    DATA = json.load(f)
with open(DATA_DIR / 'efficiencies_2025.json', encoding='utf-8') as f:
    DATA_2025 = json.load(f)

KW_PER_TON = 3.51685


def rows(family, **criteria):
    return [r for r in DATA[family] if all(r.get(k) == v for k, v in criteria.items())]


class TestEfficiencyProvenance(unittest.TestCase):

    # Table 5.2.12.1.-K Path B: full-load COPc, vendored as kW/ton.
    def test_chillers_are_table_k_path_b_full_load_cops(self):
        expected = {
            # positive displacement (scroll/recip/screw),
            # bins < 264 / 264-528 / 528-1055 / 1055-2110 / >= 2110 kW
            'Scroll': [4.513, 4.694, 5.177, 5.633, 6.018],
            'Reciprocating': [4.513, 4.694, 5.177, 5.633, 6.018],
            'Rotary Screw': [4.513, 4.694, 5.177, 5.633, 6.018],
            # centrifugal, bins < 528 / 528-1055 / 1055-1407 / >= 1407 kW
            'Centrifugal': [5.065, 5.544, 5.917, 6.018],
        }
        for compressor, cops in expected.items():
            ladder = sorted(rows('chillers', cooling_type='WaterCooled',
                                 compressor_type=compressor),
                            key=lambda r: float(r['minimum_capacity']))
            self.assertEqual(len(cops), len(ladder),
                             f'{compressor}: bin count vs the printed table')
            for row, cop in zip(ladder, cops):
                self.assertAlmostEqual(
                    cop, KW_PER_TON / row['minimum_full_load_efficiency'], delta=0.001,
                    msg=f"{compressor} {row['minimum_capacity']}: printed Table -K Path B COPc {cop}")
        air = rows('chillers', cooling_type='AirCooled')
        self.assertEqual(1, len(air))
        self.assertAlmostEqual(2.866, KW_PER_TON / air[0]['minimum_full_load_efficiency'],
                               delta=0.001,
                               msg='air-cooled: printed Table -K Path B COPc 2.866')

    # Table 5.2.12.1.-N boilers.
    def test_boilers_are_table_n(self):
        gas = sorted(rows('boilers', fuel_type='Gas'),
                     key=lambda r: float(r['maximum_capacity']))
        self.assertEqual([0.9, 0.9, 0.9],
                         [gas[0]['minimum_annual_fuel_utilization_efficiency'],
                          gas[1]['minimum_thermal_efficiency'],
                          gas[2]['minimum_combustion_efficiency']],
                         'printed: AFUE 90% (< 88 kW) / Et 90% (88-733) / Ec 90% (>= 733), water')
        oil = sorted(rows('boilers', fuel_type='Oil'),
                     key=lambda r: float(r['maximum_capacity']))
        self.assertEqual([0.86, 0.87, 0.88],
                         [oil[0]['minimum_annual_fuel_utilization_efficiency'],
                          oil[1]['minimum_thermal_efficiency'],
                          oil[2]['minimum_combustion_efficiency']],
                         'printed: AFUE 86% / Et 87% / Ec 88%, water')

    # Table 5.2.12.1.-A large AC EER ladder (electric-or-none / other heating).
    def test_unitary_acs_are_table_a(self):
        for sub in ('Single Package', 'Split System'):
            ladder = [r['minimum_energy_efficiency_ratio']
                      for r in sorted(
                          [r for r in rows('unitary_acs', equipment_type='Air Conditioners',
                                           subcategory=sub)
                           if r.get('minimum_energy_efficiency_ratio') is not None],
                          key=lambda r: (float(r['minimum_capacity']), r['heating_type']))]
            self.assertEqual(sorted([10.8, 11.0, 11.0, 11.2, 9.8, 10.0, 9.5, 9.7]),
                             sorted(ladder),
                             f'{sub}: printed EER 11.2/11.0, 11.0/10.8, 10.0/9.8, 9.7/9.5 by bin')

    # Table 5.2.12.1.-G PTAC: EER = 14.1 - 1.0435 x Cap_kW in the middle bin,
    # vendored per kBtu/h: 1.0435 / 3.412 = 0.3058.
    def test_ptac_formula_is_table_g_unit_converted(self):
        mid = next(r for r in rows('unitary_acs', equipment_type='PTAC')
                   if float(r['minimum_capacity']) > 0)
        self.assertAlmostEqual(14.1, mid['ptac_eer_coefficient_1'], delta=1e-9)
        self.assertAlmostEqual(1.0435 / 3.412, mid['ptac_eer_coefficient_2'], delta=0.0005,
                               msg='printed 1.0435 per kW = 0.3058 per kBtu/h')
        coefficients = [r['ptac_eer_coefficient_1']
                        for r in rows('unitary_acs', equipment_type='PTAC')]
        self.assertEqual([9.5, 14.1], [min(coefficients), max(coefficients)],
                         'printed floor EER 9.5 and formula intercept 14.1')

    # Table 5.2.12.1.-A heat pumps in heating mode.
    def test_heat_pump_heating_is_table_a(self):
        ladder = sorted(DATA['heat_pumps_heating'],
                        key=lambda r: float(r['minimum_capacity']))
        self.assertAlmostEqual(
            7.4, ladder[0]['minimum_heating_seasonal_performance_factor'], delta=1e-9,
            msg='printed small single-package HSPF 7.4')
        cops = sorted({r['minimum_coefficient_of_performance_heating'] for r in ladder
                       if r.get('minimum_coefficient_of_performance_heating') is not None})
        self.assertEqual([3.2, 3.3], cops,
                         'printed COPh 3.30 (19-40 kW) and 3.20 (>= 40 kW) at 8.3 C')

    def test_small_heat_pump_cooling_is_table_a_seer_15(self):
        small = [row for row in DATA['heat_pumps']
                 if float(row['minimum_capacity']) == 0]
        self.assertEqual(4, len(small))
        self.assertTrue(all(row.get('minimum_seasonal_efficiency') == 15.0
                            and row.get('minimum_full_load_efficiency') is None
                            for row in small),
                        'printed 2020 Table 5.2.12.1-A: small air-cooled heat pumps '
                        'are SEER 15, not Table-B SPVAC EER 11')

    # The heat_rejection family cites ASHRAE 90.1 and is VESTIGIAL for the
    # reference path: apply_efficiencies never reads it (the tower fan comes from
    # Table 5.2.12.2 via _apply_tower_rules, D-26). Pin the vestigiality so a
    # future consumer has to face the 90.1 provenance deliberately.
    def test_heat_rejection_family_is_declared_vestigial(self):
        self.assertTrue(all(re.search(r'90\.1', str(r.get('notes') or ''))
                            for r in DATA['heat_rejection']),
                        'every heat_rejection row cites its 90.1 source')
        source = (DATA_DIR.parent / 'efficiency.py').read_text(encoding='utf-8')
        self.assertNotRegex(source, r'heat_rejection',
                            'apply_efficiencies grew a heat_rejection consumer — re-verify its '
                            'values against the printed NECB table first (they are 90.1 '
                            'vintages, D-59)')

    # ==================== NECB 2025 (D-60) ====================

    # 2025 -K/-N and the -G PTAC coefficients are byte-identical to 2020's
    # printed tables (verified 2026-08-02) — so the vendored families must stay
    # identical across editions.
    def test_2025_shared_families_are_identical_to_2020(self):
        def strip(rs):
            return [{k: v for k, v in r.items() if k != 'notes'} for r in rs]

        for family in ('chillers', 'boilers', 'heat_rejection'):
            self.assertEqual(strip(DATA[family]), strip(DATA_2025[family]),
                             f"{family}: printed 2025 tables are identical to 2020's — the "
                             'vendored data must match')

        def ptac(d):
            return [{k: v for k, v in r.items() if k != 'notes'} for r in d['unitary_acs']
                    if r.get('equipment_type') == 'PTAC']

        self.assertEqual(ptac(DATA), ptac(DATA_2025),
                         'Table -G (PTAC) is identical in both printed editions')

    # Table -A 2025: split-system small HSPF 7.8 (printed; 2020 printed 7.4),
    # single-package stays 7.4; the COPh ladder is unchanged.
    def test_2025_heat_pump_heating_matches_printed_table_a(self):
        small = [r for r in DATA_2025['heat_pumps_heating']
                 if float(r['minimum_capacity']) == 0]
        by_sub = {r['subcategory']: r.get('minimum_heating_seasonal_performance_factor')
                  for r in small}
        self.assertAlmostEqual(7.4, by_sub['Single Package'], delta=1e-9,
                               msg='printed 2025: single-package others HSPF 7.4')
        self.assertAlmostEqual(7.8, by_sub['Split System'], delta=1e-9,
                               msg='printed 2025: split-system others HSPF 7.8')
        low_temp = sorted({r['minimum_coefficient_of_performance_heating_low_temp']
                           for r in DATA_2025['heat_pumps_heating']
                           if r.get('minimum_coefficient_of_performance_heating_low_temp')
                           is not None})
        self.assertEqual([2.05, 2.25], low_temp,
                         'printed -8.3 C COPh vendored informationally')

    # Both editions' Table -A small-HP cooling class is SEER 15.
    def test_2025_small_heat_pump_cooling_is_seer_15(self):
        small = [r for r in DATA_2025['heat_pumps']
                 if float(r['minimum_capacity']) == 0
                 and not re.search(r'single-phase', str(r.get('subcategory') or ''))]
        self.assertTrue(small)
        self.assertTrue(all(r.get('minimum_seasonal_efficiency') == 15.0 for r in small),
                        'printed 2025 -A: small air conditioners AND heat pumps, others — SEER 15')

    # The SEER2 single-phase additions (printed 14.3) are INERT for the engine:
    # their subcategory never matches the Single Package lookup.
    def test_2025_seer2_rows_are_present_and_inert(self):
        seer2 = [r for r in DATA_2025['unitary_acs']
                 if r.get('minimum_seasonal_energy_efficiency_ratio_2')]
        self.assertEqual(4, len(seer2))
        self.assertTrue(all(r['minimum_seasonal_energy_efficiency_ratio_2'] == 14.3
                            for r in seer2), 'printed SEER2 14.3')
        self.assertTrue(all(re.search(r'single-phase', str(r.get('subcategory') or ''))
                            for r in seer2),
                        "single-phase subcategory — never matched by the engine's "
                        "'Single Package' lookup")


if __name__ == '__main__':
    unittest.main()
