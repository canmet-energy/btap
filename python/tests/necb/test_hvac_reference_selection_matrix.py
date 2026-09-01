"""D-58 — the proposed->reference verification matrix.

Every catalog system, built as a PROPOSED on the 5-zone fixture, characterized
and selected under four discriminating scenarios, must produce the ADJUDICATED
reference assignment vendored in fixtures/reference_selection_matrix.json — in
BOTH naming passes: 'catalog' (name resolution) and 'scrubbed' (randomized
names, forcing the structural detector foreign models hit).

The golden was adjudicated 2026-08-02 against Table 8.4.4.7.-A fetched from the
codes MCP (all 12 category rules match the printed table) plus the 8.4.4.13
heat-pump rules; see D-58 in docs/necb_decisions.md.

Default run: a representative subset (every family + every special-rule shape),
~2 min. FULL_MATRIX=1 runs all 97 (~7 min). The golden is NEVER regenerated
from Python — the Ruby suite's UPDATE_GOLDEN escape hatch is deliberately not
ported (D-79: the adjudicated matrix is the shared contract both ports read).
"""

from __future__ import annotations

import json
import os
import unittest

import btap.modeling as modeling
from btap.modeling.hvac import catalog
from btap.necb import hvac
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import FIXTURES, needs_sdk

GOLDEN = FIXTURES / 'reference_selection_matrix.json'

SCENARIOS = {
    'general_2storey': {'storeys': 2, 'type': 'office'},
    'general_3storey': {'storeys': 3, 'type': 'office'},
    'residential': {'storeys': 3, 'type': 'multi-unit residential'},
    'data_processing': {'storeys': 1, 'type': 'data centre'},
}

# One representative per family plus every special-rule shape the matrix
# found interesting: plant HPs (hs09/14), district variants, DOAS+fan-coil
# composite, MAU+PTAC, shared PSZ (electric AND ashp), wshp, vrf, MZ built-up.
SUBSET = [
    'Baseboard electric', 'Baseboard district hot water', 'Forced air furnace',
    'PSZ RTU Electric and DX Coils and Electric Baseboard',
    'PSZ RTU ASHP with Gas and ASHP with Gas Supp. Heat Coils and Electric Baseboard',
    'PSZ MAU Electric and DX Coils and Electric Baseboard with PTAC',
    'FPFC MAU Chilled Water Coils with Scroll Chiller',
    'TPFC MAU Chilled Water Coils with Scroll Chiller',
    'MZ BU RTU Electric Heating Coil Centrifugal Chiller and Electric Baseboard',
    'DOAS with fan coil air-cooled chiller with boiler',
    'DOAS with fan coil air-cooled chiller with district hot water',
    'DOAS with VRF', 'DOAS with water source heat pumps',
    'hs09_ccashp_baseboard', 'hs11_ashp_pthp', 'hs14_cgshp_fancoils',
    'hs16_ashp_cawhp_fancoils', 'Direct evap coolers with no heat',
    'Gas unit heaters', 'Window AC with baseboard electric', 'PTHP',
    'Water source heat pumps',
]

_KEYS = ('system', 'action', 'energy_type', 'catalog', 'zones')


@needs_sdk
class TestReferenceSelectionMatrix(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(GOLDEN, encoding='utf-8') as f:
            cls.golden = json.load(f)

    def names_under_test(self):
        all_names = [r['name'] for r in catalog.rows()]
        if os.environ.get('FULL_MATRIX'):
            return all_names

        # subset entries are prefixes-or-exact against the catalog (some names carry
        # long suffixes); every subset entry must match something or the test is lying
        names = []
        for want in SUBSET:
            found = next((n for n in all_names if n == want), None)
            if found is None:
                found = next((n for n in all_names if n.startswith(want)), None)
            if found is None:
                self.fail(f"SUBSET entry '{want}' matches no catalog name")
            if found not in names:
                names.append(found)
        return names

    def compute_row(self, name):
        row = next(r for r in catalog.rows() if r['name'] == name)
        record = {'name': name, 'family': row['family']}
        for pass_ in ('catalog', 'scrubbed'):
            model = load_fixture()
            zones = sorted_zones(model)
            modeling.build_system(model, name, zones)
            if pass_ == 'scrubbed':
                for i, loop in enumerate(model.getAirLoopHVACs()):
                    loop.setName(f'Air System {i + 1}')
                for i, loop in enumerate(model.getPlantLoops()):
                    loop.setName(f'Plant {i + 1}')
            facts = modeling.characterize(model, audit=None)
            for label, scenario in SCENARIOS.items():
                zone_names = []
                for g in facts['zone_groups']:
                    for z in g['zones']:
                        if z not in zone_names:
                            zone_names.append(z)
                zone_types = {z: scenario['type'] for z in zone_names}
                info = {'storeys': scenario['storeys'], 'zone_types': zone_types,
                        'winter_design_temp_c': -20}
                assignments = []
                for a in hvac.select_reference_systems(facts=facts, building=info,
                                                       vintage='2020', audit=None):
                    entry = {'system': a.reference_system, 'action': str(a.action),
                             'energy_type': a.energy_type, 'catalog': a.catalog_name,
                             'zones': len(a.zones)}
                    if entry not in assignments:
                        assignments.append(entry)
                record[f'{pass_}_{label}'] = assignments
        return record

    @staticmethod
    def normalize(assignments):
        out = []
        for a in (assignments or []):
            out.append({k: a.get(k) for k in _KEYS})
        return out

    def test_reference_assignments_match_the_adjudicated_golden(self):
        for name in self.names_under_test():
            expected = next((r for r in self.golden if r['name'] == name), None)
            self.assertIsNotNone(
                expected, f"'{name}' missing from the golden — regenerate and re-adjudicate (D-58)")
            actual = self.compute_row(name)
            for pass_ in ('catalog', 'scrubbed'):
                for label in SCENARIOS:
                    key = f'{pass_}_{label}'
                    self.assertEqual(
                        self.normalize(expected[key]), self.normalize(actual[key]),
                        f'{name} / {key}: reference assignment drifted from the adjudicated matrix')

    def test_catalog_and_scrubbed_passes_agree_in_the_golden(self):
        for row in self.golden:
            for label in SCENARIOS:
                self.assertEqual(
                    self.normalize(row[f'catalog_{label}']),
                    self.normalize(row[f'scrubbed_{label}']),
                    f"{row['name']} / {label}: the golden itself carries a naming-pass divergence — "
                    'foreign proposeds would get a different reference than gem-built ones')

    def test_golden_covers_the_whole_catalog(self):
        golden_names = {r['name'] for r in self.golden}
        missing = [r['name'] for r in catalog.rows() if r['name'] not in golden_names]
        self.assertEqual(
            [], missing,
            'catalog systems missing from the adjudicated golden (new system added? re-run D-58)')
