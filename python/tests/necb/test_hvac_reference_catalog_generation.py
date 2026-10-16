"""Catalog-wide proposed-to-reference construction and translation gate.

The D-58 matrix proves selection. This module proves the next boundary: every
catalog topology can be cloned, torn down, rebuilt as its adjudicated reference,
serialized, reloaded, and translated in both supported editions.

Every row runs the two-storey office case. One explicitly adjudicated
representative of each distinct four-scenario assignment signature also runs
the other three scenarios. This keeps input-topology coverage exhaustive while
avoiding four identical reconstructions of every catalog variant.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import openstudio

import btap.modeling as modeling
from btap.codes.necb import hvac
from btap.modeling.hvac import catalog
from btap.modeling.hvac.systems import vav_reheat
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.necb.reference_matrix_support import (
    CODES,
    GOLDEN,
    SCENARIOS,
    SIGNATURE_REPRESENTATIVES,
    assignment_signature,
    normalize_expected,
)
from tests.support import needs_sdk

PRIMARY_SCENARIO = 'general_2storey'
MODERN_ERV_ROWS = {
    'VAV chiller with gas boiler reheat and rotary ERV',
    'PVAV with gas boiler reheat and plate HRV',
}
MERGED_REFERENCE_SYSTEMS = {1, 2, 5, 6}


def _test_name(index, name):
    slug = re.sub(r'[^0-9a-zA-Z]+', '_', name).strip('_').lower()
    return f'test_catalog_reference_generation__{index:03d}_{slug}'


def _actual_assignments(assignments):
    return [
        {
            'system': assignment.reference_system,
            'action': str(assignment.action),
            'energy_type': assignment.energy_type,
            'catalog': assignment.catalog_name,
            'blocks': len(assignment.zones),
        }
        for assignment in assignments
    ]


def _expected_generated_assignments(assignments):
    """Apply the independently adjudicated D-28/D-101 construction scope.

    Selection stays one assignment per thermal block. Construction combines
    matching Systems 1/2/5 under Table -B Note (2), and System 6 under Note
    (3). Systems 3/4 and heat-pump redirects stay one unit per block.
    """
    generated = []
    for assignment in normalize_expected(assignments):
        mergeable = (
            assignment['system'] in MERGED_REFERENCE_SYSTEMS
            and assignment['action'] in ('build', 'through_the_wall')
        )
        key = (
            assignment['system'],
            assignment['catalog'],
            assignment['energy_type'],
        ) if mergeable else None
        existing = next(
            (item for item in generated if item['merge_key'] == key),
            None,
        ) if key is not None else None
        if existing is None:
            generated.append({
                'merge_key': key,
                'assignment': dict(assignment),
                'source_actions': {assignment['action']},
            })
            continue
        existing['assignment']['blocks'] += assignment['blocks']
        existing['source_actions'].add(assignment['action'])
        if len(existing['source_actions']) > 1:
            existing['assignment']['action'] = 'mixed'
    return [item['assignment'] for item in generated]


def _catalog_owned(objects):
    owned = []
    for obj in objects:
        source = obj.additionalProperties().getFeatureAsString(
            vav_reheat.ENERGY_RECOVERY_SOURCE_FEATURE)
        if (source.is_initialized()
                and source.get() == vav_reheat.ENERGY_RECOVERY_SOURCE_CATALOG):
            owned.append(obj.nameString())
    return owned


@needs_sdk
class TestCatalogReferenceGeneration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN.read_text(encoding='utf-8'))
        cls.expected = {row['name']: row for row in cls.golden}
        cls.temp = tempfile.TemporaryDirectory(
            prefix='catalog-reference-generation-')
        cls.temp_path = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def check_system(self, index, name):
        expected = self.expected[name]
        proposed = load_fixture()
        modeling.build_system(proposed, name, sorted_zones(proposed))
        before = self.temp_path / f'{index:03d}-proposed-before.osm'
        after = self.temp_path / f'{index:03d}-proposed-after.osm'
        proposed.save(openstudio.path(str(before)), True)

        scenarios = [PRIMARY_SCENARIO]
        if name in SIGNATURE_REPRESENTATIVES:
            scenarios.extend(
                scenario for scenario in SCENARIOS
                if scenario != PRIMARY_SCENARIO)

        for code in CODES:
            for scenario_name in scenarios:
                with self.subTest(code=code, scenario=scenario_name):
                    scenario = SCENARIOS[scenario_name]
                    zone_names = [
                        zone.nameString()
                        for zone in proposed.getThermalZones()
                    ]
                    building = {
                        'storeys': scenario['storeys'],
                        'zone_types': {
                            zone_name: scenario['type']
                            for zone_name in zone_names
                        },
                        'winter_design_temp_c': -20,
                    }
                    result = hvac.reference_hvac(
                        proposed, code=code, building=building)

                    self.assertEqual(
                        _expected_generated_assignments(
                            expected[f'catalog_{scenario_name}']),
                        _actual_assignments(result.assignments),
                        f'{name} / {code} / {scenario_name}')
                    covered = [
                        zone_name
                        for assignment in result.assignments
                        for zone_name in assignment.zones
                    ]
                    conditioned_blocks = sum(
                        group['zones']
                        for group in expected['catalog_groups']
                        if group['heated'] or group['cooled'])
                    self.assertEqual(conditioned_blocks, len(covered))
                    self.assertEqual(
                        len(covered), len(set(covered)),
                        'reference assignments must partition the conditioned '
                        'thermal blocks')
                    self.assertEqual(
                        sorted(zone_names),
                        sorted(
                            zone.nameString()
                            for zone in result.model.getThermalZones()))
                    self.assertIsNot(proposed, result.model)

                    self._assert_modern_teardown(
                        name, result.model)
                    self._assert_round_trip_translates(
                        index, name, code, scenario_name, result.model,
                        len(zone_names))

        proposed.save(openstudio.path(str(after)), True)
        self.assertEqual(
            before.read_bytes(), after.read_bytes(),
            f'{name}: reference generation mutated the proposed model')

    def _assert_modern_teardown(self, name, reference):
        if 'chilled beams' in name:
            self.assertEqual(
                0,
                len(reference
                    .getAirTerminalSingleDuctConstantVolumeCooledBeams()))
            self.assertEqual(0, len(reference.getCoilCoolingCooledBeams()))
        elif name.startswith('Dual-duct VAV'):
            self.assertEqual(0, len(reference.getAirTerminalDualDuctVAVs()))
        elif name in MODERN_ERV_ROWS:
            self.assertEqual(
                [],
                _catalog_owned(
                    reference
                    .getHeatExchangerAirToAirSensibleAndLatents()))
            self.assertEqual(
                [], _catalog_owned(reference.getTableLookups()))
            self.assertEqual(
                [], _catalog_owned(reference.getTableIndependentVariables()))

    def _assert_round_trip_translates(
            self, index, name, code, scenario, reference, zone_count):
        tag = re.sub(
            r'[^0-9a-zA-Z]+', '-', f'{index}-{code}-{scenario}-{name}'
        ).strip('-').lower()
        path = self.temp_path / f'{tag}.osm'
        reference.save(openstudio.path(str(path)), True)
        loaded = openstudio.osversion.VersionTranslator().loadModel(
            openstudio.path(str(path)))
        self.assertTrue(loaded.is_initialized(), f'{tag}: OSM did not reload')
        reloaded = loaded.get()
        self.assertEqual(zone_count, len(reloaded.getThermalZones()))
        workspace = openstudio.energyplus.ForwardTranslator().translateModel(
            reloaded)
        self.assertEqual(
            zone_count,
            len(workspace.getObjectsByType(
                openstudio.IddObjectType('Zone'))),
            f'{tag}: forward translation lost thermal zones')

    def test_signature_representatives_cover_the_adjudicated_matrix(self):
        all_signatures = {
            assignment_signature(row)
            for row in self.golden
        }
        representative_signatures = {
            assignment_signature(self.expected[name])
            for name in SIGNATURE_REPRESENTATIVES
        }
        self.assertEqual(all_signatures, representative_signatures)
        self.assertEqual(
            len(all_signatures), len(SIGNATURE_REPRESENTATIVES),
            'each representative must cover exactly one signature')

    def test_golden_and_catalog_names_are_identical(self):
        self.assertEqual(
            {row['name'] for row in catalog.rows()},
            set(self.expected))


def _add_per_system_tests():
    for index, row in enumerate(catalog.rows()):
        name = row['name']

        def test(self, index=index, name=name):
            self.check_system(index, name)

        test.__name__ = _test_name(index, name)
        test.__doc__ = f'Full reference generation: {name}'
        setattr(TestCatalogReferenceGeneration, test.__name__, test)


_add_per_system_tests()


if __name__ == '__main__':
    unittest.main()
