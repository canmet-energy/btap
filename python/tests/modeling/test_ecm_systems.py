import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk


@needs_sdk
class TestEcmSystems(unittest.TestCase):
    def test_hs12_ashp_baseboard_doas(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'hs12_ashp_baseboard', zones,
                                       namer='necb_pipe_name')

        self.assertEqual(1, len(result.air_loops))
        # ASHP single-speed DX on the loop
        self.assertEqual(1, sum(1 for c in model.getCoilHeatingDXSingleSpeeds()
                                if 'ASHP' in c.nameString()))
        # PTAC (electric-off heat section, DX cooling) + electric baseboards per zone
        self.assertEqual(len(zones), len(model.getZoneHVACPackagedTerminalAirConditioners()))
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))
        self.assertEqual(len(zones), sum(1 for c in model.getCoilCoolingDXSingleSpeeds()
                                         if 'PTAC' in c.nameString()))
        # legacy naming quirk: doas zone tokens read b-e/ptac
        self.assertEqual('sys_1|doas|shr>none|sc>ashp|sh>ashp|ssf>cv|zh>b-e|zc>ptac|srf>none|',
                         result.air_loops[0].nameString())

    def test_hs09_ccashp_uses_variable_speed_dx(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'hs09_ccashp_baseboard', zones,
                                       namer='necb_pipe_name')

        self.assertEqual(1, len(model.getCoilCoolingDXVariableSpeeds()))
        self.assertEqual(1, len(model.getCoilHeatingDXVariableSpeeds()))
        htg = model.getCoilHeatingDXVariableSpeeds()[0]
        self.assertAlmostEqual(
            -25.0, htg.minimumOutdoorDryBulbTemperatureforCompressorOperation(), delta=1e-6)
        self.assertIn('sc>ccashp', result.air_loops[0].nameString())
        self.assertIn('sh>ccashp', result.air_loops[0].nameString())

    def test_hs12_mixed_multizone_builds_vav(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'hs12_ashp_baseboard', zones,
                              config={'vent_type': 'mixed'})

        # multizone mixed: VV supply + return fans, VAV terminals w/ electric reheat, no PTACs
        self.assertEqual(2, len(model.getFanVariableVolumes()))
        self.assertEqual(len(zones), len(model.getAirTerminalSingleDuctVAVReheats()))
        self.assertEqual(0, len(model.getZoneHVACPackagedTerminalAirConditioners()))
        self.assertEqual(1, len(model.getSetpointManagerWarmests()))
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))

    def test_hs08_ccashp_vrf(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'hs08_ccashp_vrf', zones,
                                       namer='necb_pipe_name')

        # outdoor VRF unit with hs08 settings + one terminal per zone
        units = model.getAirConditionerVariableRefrigerantFlows()
        self.assertEqual(1, len(units))
        unit = units[0]
        self.assertTrue(unit.heatPumpWasteHeatRecovery())
        self.assertAlmostEqual(-25.0, unit.minimumOutdoorTemperatureinHeatingMode(),
                               delta=1e-6)
        self.assertEqual('ThermostatOffsetPriority', unit.masterThermostatPriorityControlType())
        terminals = model.getZoneHVACTerminalUnitVariableRefrigerantFlows()
        self.assertEqual(len(zones), len(terminals))
        self.assertEqual(len(zones), len(unit.terminals()))

        # DOAS with CCASHP variable-speed DX
        self.assertEqual(1, len(model.getCoilCoolingDXVariableSpeeds()))
        self.assertEqual('sys_1|doas|shr>none|sc>ccashp|sh>ccashp|ssf>cv|zh>vrf|zc>vrf|srf>none|',
                         result.air_loops[0].nameString())

    def test_hs13_is_hs08_with_single_speed_dx(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'hs13_ashp_vrf', zones)

        self.assertEqual(1, len(model.getAirConditionerVariableRefrigerantFlows()))
        self.assertEqual(0, len(model.getCoilCoolingDXVariableSpeeds()),
                         'hs13 uses single-speed ASHP on the DOAS')
        self.assertEqual(1, sum(1 for c in model.getCoilCoolingDXSingleSpeeds()
                                if 'ASHP' in c.nameString()))


if __name__ == '__main__':
    unittest.main()
