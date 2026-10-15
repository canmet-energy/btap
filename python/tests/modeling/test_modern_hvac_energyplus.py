"""Operating gates for the modern catalog additions.

All simulations stay in one test method so this module never starts concurrent
EnergyPlus processes on its own.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import btap.modeling as modeling
from tests.support import DDY, EPW, load_fixture, needs_engine

MODERN_ROWS = (
    'DOAS with active chilled beams and electric baseboards',
    'DOAS with passive chilled beams and electric baseboards',
    'DOAS with hydronic radiant floors, gas boiler and air-cooled chiller',
    'VAV chiller with gas boiler reheat and rotary ERV',
    'PVAV with gas boiler reheat and plate HRV',
    'Dual-duct VAV with gas boiler and water-cooled chiller',
)
BEAM_TABLE = 'AirTerminal:SingleDuct:ConstantVolume:CooledBeam'
RADIANT_TABLE = 'ZoneHVAC:LowTemperatureRadiant:VariableFlow'


def _output(model, name, key='*'):
    import openstudio

    variable = openstudio.model.OutputVariable(name, model)
    variable.setKeyValue(key)
    variable.setReportingFrequency('Hourly')
    return variable


def _sql_double(sql, query):
    value = sql.execAndReturnFirstDouble(query)
    return value.get() if value.is_initialized() else None


def _sizing_sum(sql, table, column):
    return _sql_double(
        sql,
        "SELECT SUM(CAST(Value AS REAL)) FROM TabularDataWithStrings "
        "WHERE ReportName='ComponentSizingSummary' "
        f"AND TableName='{table}' AND ColumnName='{column}'")


@needs_engine
class TestModernHVACEnergyPlus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='modern-hvac-eplus-')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_every_new_row_operates_in_heating_and_cooling(self):
        import btap.simulation as simulation
        from btap._compat import sorted_by_name

        for index, name in enumerate(MODERN_ROWS):
            with self.subTest(system=name):
                model = load_fixture()
                modeling.build_system(
                    model, name, sorted_by_name(model.getThermalZones()))

                moisture_controlled = (
                    'chilled beams' in name or 'radiant floors' in name)
                if moisture_controlled:
                    _output(
                        model, 'Schedule Value',
                        'Chilled Water Loop Chilled Water Setpoint')
                if name.endswith(('rotary ERV', 'plate HRV')):
                    _output(model, 'Heat Exchanger Sensible Heating Rate')
                    _output(model, 'Heat Exchanger Sensible Cooling Rate')

                result = simulation.run(
                    model,
                    run_dir=str(Path(self.temp.name) / f'row-{index:02d}'),
                    weather={'epw': str(EPW), 'ddy': str(DDY)},
                    sizing_only=False)
                self.assertTrue(result.is_clean(), f'{name}: annual run is not clean')
                self.assertGreater(
                    result.energy['end_uses_kwh']['heating'] or 0.0, 0.0,
                    f'{name}: no annual heating energy')
                self.assertGreater(
                    result.energy['end_uses_kwh']['cooling'] or 0.0, 0.0,
                    f'{name}: no annual cooling energy')

                sql = model.sqlFile().get()
                if 'chilled beams' in name:
                    self.assertGreater(
                        _sizing_sum(
                            sql, BEAM_TABLE,
                            'Maximum Total Chilled Water Flow Rate') or 0.0,
                        0.0, f'{name}: beam water flow did not size')
                elif 'radiant floors' in name:
                    for column in (
                            'Design Size Heating Design Capacity',
                            'Design Size Cooling Design Capacity'):
                        self.assertGreater(
                            _sizing_sum(sql, RADIANT_TABLE, column) or 0.0,
                            0.0, f'{name}: {column} did not size')
                elif name.startswith('Dual-duct'):
                    self.assertGreater(
                        _sizing_sum(
                            sql, 'Coil:Heating:Water',
                            'Design Size Rated Capacity') or 0.0,
                        0.0, f'{name}: hot-deck capacity did not size')
                    self.assertGreater(
                        _sizing_sum(
                            sql, 'Coil:Cooling:Water',
                            'Design Size Design Coil Load') or 0.0,
                        0.0, f'{name}: cold-deck capacity did not size')
                    self.assertLessEqual(
                        result.unmet_hours['heating'], 100.0,
                        f'{name}: hot-deck sizing left excessive unmet heat')

                if moisture_controlled:
                    maximum = _sql_double(
                        sql,
                        "SELECT MAX(Value) FROM ReportData "
                        "JOIN ReportDataDictionary "
                        "USING (ReportDataDictionaryIndex) "
                        "WHERE Name='Schedule Value' "
                        "AND KeyValue="
                        "'CHILLED WATER LOOP CHILLED WATER SETPOINT'")
                    self.assertGreater(
                        maximum or 0.0, 15.0,
                        f'{name}: humid-weather dew-point reset never moved')

                if name.endswith(('rotary ERV', 'plate HRV')):
                    for variable_name in (
                            'Heat Exchanger Sensible Heating Rate',
                            'Heat Exchanger Sensible Cooling Rate'):
                        maximum = _sql_double(
                            sql,
                            "SELECT MAX(Value) FROM ReportData "
                            "JOIN ReportDataDictionary "
                            "USING (ReportDataDictionaryIndex) "
                            f"WHERE Name='{variable_name}'")
                        self.assertGreater(
                            maximum or 0.0, 0.0,
                            f'{name}: {variable_name} never operated')

    def test_existing_vrf_uses_simultaneous_heat_recovery(self):
        import btap.simulation as simulation
        from btap._compat import sorted_by_name

        model = load_fixture()
        modeling.build_system(
            model, 'VRF', sorted_by_name(model.getThermalZones()))
        for name in (
                'VRF Heat Pump Terminal Unit Cooling Load Rate',
                'VRF Heat Pump Terminal Unit Heating Load Rate',
                'VRF Heat Pump Heat Recovery Rate'):
            _output(model, name)

        result = simulation.run(
            model, run_dir=str(Path(self.temp.name) / 'vrf-heat-recovery'),
            weather={'epw': str(EPW), 'ddy': str(DDY)}, sizing_only=False)
        self.assertTrue(result.is_clean(), 'VRF annual run is not clean')
        sql = model.sqlFile().get()
        simultaneous = _sql_double(
            sql,
            """SELECT COUNT(*) FROM (
                 SELECT TimeIndex,
                   MAX(CASE WHEN Name =
                     'VRF Heat Pump Terminal Unit Cooling Load Rate'
                     THEN Value ELSE 0 END) AS Cooling,
                   MAX(CASE WHEN Name =
                     'VRF Heat Pump Terminal Unit Heating Load Rate'
                     THEN Value ELSE 0 END) AS Heating,
                   MAX(CASE WHEN Name =
                     'VRF Heat Pump Heat Recovery Rate'
                     THEN Value ELSE 0 END) AS Recovery
                 FROM ReportData
                 JOIN ReportDataDictionary
                   USING (ReportDataDictionaryIndex)
                 GROUP BY TimeIndex)
               WHERE Cooling > 0 AND Heating > 0 AND Recovery > 0""")
        self.assertGreater(
            simultaneous or 0.0, 0.0,
            'VRF never served simultaneous heating and cooling with recovery')


if __name__ == '__main__':
    unittest.main()
