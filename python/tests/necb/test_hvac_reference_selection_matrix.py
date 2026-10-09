"""D-58 — the proposed->reference verification matrix.

Every catalog system, built as a PROPOSED on the 5-zone fixture, characterized
and selected under four discriminating scenarios, must produce the ADJUDICATED
reference assignment vendored in fixtures/reference_selection_matrix.json — in
BOTH naming passes: 'catalog' (name resolution) and 'scrubbed' (randomized
names, forcing the structural detector foreign models hit).

The golden was adjudicated 2026-08-02 against Table 8.4.4.7.-A fetched from the
codes MCP (all 12 category rules match the printed table) plus the 8.4.4.13
heat-pump rules; see D-58 in docs/necb_decisions.md.

Default run: a representative subset (every family + every special-rule shape).
FULL_MATRIX=1 runs all 97. The golden is NEVER regenerated from Python — the
Ruby suite's UPDATE_GOLDEN escape hatch is deliberately not ported (D-79: the
adjudicated matrix is the shared contract both ports read).

SCHEMA, since D-101: each scenario lists ONE ROW PER ASSIGNMENT with
``blocks`` — the thermal blocks that assignment serves — and the rows are NOT
deduplicated. The old schema carried a ``zones`` count per DEDUPLICATED row
(`if entry not in assignments`), so five single-zone units over five thermal
blocks and one shared unit over one block produced the same row, and the
schema could not express the thing the ruling changed. The adjudicated content
— system, action, energy type, catalog — is preserved verbatim from the
pre-change file; only multiplicity was derived, by applying D-101 to the
golden's own ``*_groups`` data (the conditioned blocks are the sum of ``zones``
over groups that are heated or cooled). Renaming the key was deliberate: a
stale golden fails on the schema instead of silently comparing two different
meanings of one number. The test additionally asserts the assignments PARTITION
the retained conditioned blocks, computed from the model, because five rows
naming one block are otherwise indistinguishable from five rows naming five.

One test per system, generated below, so pytest-xdist spreads the matrix over
every worker. As a single loop it was the longest test in CI (301 s of the
verify job's 332 s suite on 36 vCPUs); the subset-matching and one-test-per-
system checks keep the split from silently testing fewer systems.
"""

from __future__ import annotations

import json
import os
import re
import unittest

import btap.modeling as modeling
from btap.codes.necb import hvac
from btap.modeling.hvac import catalog
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

#: `blocks` replaced `zones` with D-101. The old key counted the zones of
#: ONE assignment under serving-set grouping; this one counts the thermal
#: blocks of one assignment with every assignment listed, so the schema
#: change itself fails a stale golden instead of silently comparing two
#: different meanings of the same number.
_KEYS = ('system', 'action', 'energy_type', 'catalog', 'blocks')

#: The prefix every generated per-system test carries.
PER_SYSTEM_PREFIX = 'test_reference_assignments_match_the_adjudicated_golden__'


def names_under_test():
    """``(names, unmatched subset entries)``. Subset entries are prefixes-or-exact
    against the catalog (some names carry long suffixes)."""
    all_names = [r['name'] for r in catalog.rows()]
    if os.environ.get('FULL_MATRIX'):
        return all_names, []
    names, unmatched = [], []
    for want in SUBSET:
        found = next((n for n in all_names if n == want), None)
        if found is None:
            found = next((n for n in all_names if n.startswith(want)), None)
        if found is None:
            unmatched.append(want)
        elif found not in names:
            names.append(found)
    return names, unmatched


def _test_name(index, name):
    slug = re.sub(r'[^0-9a-zA-Z]+', '_', name).strip('_').lower()
    return f'{PER_SYSTEM_PREFIX}{index:03d}_{slug}'


@needs_sdk
class TestReferenceSelectionMatrix(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(GOLDEN, encoding='utf-8') as f:
            cls.golden = json.load(f)

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
                # The retained CONDITIONED blocks — what the assignments must
                # partition. An unheated, uncooled group gets no system.
                conditioned = []
                for g in facts['zone_groups']:
                    if not (g['heated'] or g['cooled']):
                        continue
                    for z in g['zones']:
                        if z not in conditioned:
                            conditioned.append(z)
                zone_types = {z: scenario['type'] for z in zone_names}
                info = {'storeys': scenario['storeys'], 'zone_types': zone_types,
                        'winter_design_temp_c': -20}
                assignments = []
                covered = []
                for a in hvac.select_reference_systems(facts=facts, building=info,
                                                       code='necb2020', audit=None):
                    # NO DEDUPE. Multiplicity is the point since D-101: five
                    # single-zone units over five thermal blocks is a different
                    # reference from one unit over five, and collapsing
                    # identical rows hid exactly that. `blocks` replaces
                    # `zones` so a stale golden fails loudly rather than
                    # comparing a count against a count that now means
                    # something else.
                    assignments.append(
                        {'system': a.reference_system, 'action': str(a.action),
                         'energy_type': a.energy_type, 'catalog': a.catalog_name,
                         'blocks': len(a.zones)})
                    covered.extend(a.zones)
                record[f'{pass_}_{label}'] = assignments
                record[f'{pass_}_{label}__covered'] = covered
                record[f'{pass_}_{label}__conditioned'] = conditioned
        return record

    @staticmethod
    def normalize(assignments):
        out = []
        for a in (assignments or []):
            out.append({k: a.get(k) for k in _KEYS})
        return out

    def check_system(self, name):
        expected = next((r for r in self.golden if r['name'] == name), None)
        self.assertIsNotNone(
            expected,
            f"'{name}' missing from the golden. The golden is NEVER regenerated "
            f"from Python (D-79): ADD the row and adjudicate it against Table "
            f"8.4.x.7.-A, or remove the catalogue entry. 'Regenerate' is what "
            f"the file header forbids, and this message used to say it")
        actual = self.compute_row(name)
        for pass_ in ('catalog', 'scrubbed'):
            for label in SCENARIOS:
                key = f'{pass_}_{label}'
                self.assertEqual(
                    self.normalize(expected[key]), self.normalize(actual[key]),
                    f'{name} / {key}: reference assignment drifted from the adjudicated matrix')
                # D-101: the assignments must PARTITION the retained
                # conditioned blocks — every one covered, none twice. The row
                # comparison above would accept five assignments that all name
                # the same block, or four that leave one unconditioned.
                covered = actual[f'{key}__covered']
                conditioned = actual[f'{key}__conditioned']
                self.assertEqual(
                    sorted(conditioned), sorted(covered),
                    f'{name} / {key}: the assignments must cover every retained '
                    f'conditioned block exactly once')
                self.assertEqual(
                    len(set(covered)), len(covered),
                    f'{name} / {key}: a block is served by two assignments')

    def test_every_subset_entry_matches_a_catalog_system(self):
        _names, unmatched = names_under_test()
        self.assertEqual([], unmatched,
                         'SUBSET entries that match no catalog name — the matrix would '
                         'silently test fewer systems')

    def test_one_generated_test_per_system_under_test(self):
        names, _unmatched = names_under_test()
        generated = sorted(n for n in dir(type(self)) if n.startswith(PER_SYSTEM_PREFIX))
        self.assertEqual(sorted(_test_name(i, n) for i, n in enumerate(names)), generated)

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


def _add_per_system_tests():
    names, _unmatched = names_under_test()
    for index, name in enumerate(names):
        def test(self, name=name):
            self.check_system(name)
        test.__name__ = _test_name(index, name)
        test.__doc__ = f'D-58 matrix: {name}'
        setattr(TestReferenceSelectionMatrix, test.__name__, test)


_add_per_system_tests()
