"""Serial EnergyPlus gate for catalog proposed-to-reference generation.

The proposed catalog sweep already runs all 102 inputs. This module exercises
the other side of the boundary: full compliance sizing of every modern input
and one representative of each remaining D-58 assignment signature, in both
supported editions. All 24 pipelines stay in one test method so this module
never starts concurrent EnergyPlus processes on its own.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import btap.modeling as modeling
from btap.codes import performance_compliance
from btap.modeling.hvac.systems import vav_reheat
from btap.simulation import runner
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.necb.reference_matrix_support import (
    CODES,
    ENGINE_CASES,
    GOLDEN,
    MODERN_ROWS,
    SCENARIOS,
    SIGNATURE_REPRESENTATIVES,
    assignment_signature,
)
from tests.support import DDY, EPW, needs_engine

MODERN_ERV_ROWS = {
    'VAV chiller with gas boiler reheat and rotary ERV',
    'PVAV with gas boiler reheat and plate HRV',
}


def _slug(value):
    return re.sub(r'[^0-9a-zA-Z]+', '-', value).strip('-').lower()


def _catalog_owned(objects):
    owned = []
    for obj in objects:
        source = obj.additionalProperties().getFeatureAsString(
            vav_reheat.ENERGY_RECOVERY_SOURCE_FEATURE)
        if (source.is_initialized()
                and source.get() == vav_reheat.ENERGY_RECOVERY_SOURCE_CATALOG):
            owned.append(obj.nameString())
    return owned


class TestReferenceEngineCaseManifest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN.read_text(encoding='utf-8'))
        cls.expected = {row['name']: row for row in cls.golden}

    def test_cases_cover_every_signature_and_every_modern_row(self):
        case_names = {name for name, _scenario in ENGINE_CASES}
        self.assertTrue(set(MODERN_ROWS).issubset(case_names))
        self.assertEqual(
            {
                assignment_signature(self.expected[name])
                for name in SIGNATURE_REPRESENTATIVES
            },
            {
                assignment_signature(self.expected[name])
                for name in case_names
            },
        )

    def test_case_names_and_scenarios_are_registered(self):
        self.assertEqual(len(ENGINE_CASES), len(set(ENGINE_CASES)))
        self.assertEqual(
            set(), {name for name, _scenario in ENGINE_CASES} - set(self.expected))
        self.assertEqual(
            set(),
            {scenario for _name, scenario in ENGINE_CASES} - set(SCENARIOS),
        )


@needs_engine
class TestCatalogReferenceEnergyPlus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='catalog-reference-e2e-')
        cls.temp_path = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_every_signature_and_modern_input_sizes_cleanly(self):
        weather = {'epw': str(EPW), 'ddy': str(DDY)}
        for index, (name, scenario_name) in enumerate(ENGINE_CASES):
            for code in CODES:
                with self.subTest(system=name, scenario=scenario_name, code=code):
                    proposed = load_fixture()
                    modeling.build_system(
                        proposed, name, sorted_zones(proposed))
                    scenario = SCENARIOS[scenario_name]
                    building = {
                        'storeys': scenario['storeys'],
                        'zone_types': {
                            zone.nameString(): scenario['type']
                            for zone in proposed.getThermalZones()
                        },
                        'winter_design_temp_c': -20,
                    }
                    run_dir = (
                        self.temp_path
                        / f'{index:02d}-{_slug(name)}-{code}-{scenario_name}'
                    )
                    result = performance_compliance(
                        proposed,
                        code=code,
                        simulate='sizing',
                        weather=weather,
                        building=building,
                        run_dir=str(run_dir),
                        hdd=3890,
                        province_state='ONTARIO',
                    )

                    self.assertIsNone(
                        result.compliant,
                        'sizing mode must not claim a compliance verdict')
                    self.assertIsNotNone(result.proposed_model)
                    self.assertIsNotNone(result.reference_model)
                    for phase in ('proposed_sizing', 'reference_sizing'):
                        output = run_dir / phase / 'run'
                        self.assertTrue(
                            runner.is_clean_run(output),
                            f'{name} / {code} / {phase}: EnergyPlus was not clean')
                        self.assertTrue((output / 'eplusout.sql').is_file())
                    self.assertTrue(
                        result.proposed_model.sqlFile().is_initialized())
                    self.assertTrue(
                        result.reference_model.sqlFile().is_initialized())

                    self._assert_modern_reference_cleanup(
                        name, result.reference_model)

    def _assert_modern_reference_cleanup(self, name, reference):
        if 'chilled beams' in name:
            self.assertEqual(
                0,
                len(reference
                    .getAirTerminalSingleDuctConstantVolumeCooledBeams()))
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

if __name__ == '__main__':
    unittest.main()
