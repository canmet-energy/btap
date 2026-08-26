import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk


@needs_sdk
class TestVrfErvGshpComposites(unittest.TestCase):
    """Covers VRF (standalone and DOAS-paired) topologies, zone ERVs, GSHP/cooling-tower
    WSHP loop variants, and the air-cooled/district chilled-water fan-coil composite matrix."""

    def test_standalone_vrf_self_ventilates(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'VRF', zones)

        self.assertEqual(1, len(model.getAirConditionerVariableRefrigerantFlows()))
        terminals = model.getZoneHVACTerminalUnitVariableRefrigerantFlows()
        self.assertEqual(len(zones), len(terminals))
        self.assertTrue(terminals[0].isOutdoorAirFlowRateDuringCoolingOperationAutosized(),
                        'standalone VRF terminals ventilate (autosized OA)')
        self.assertEqual(0, len(model.getAirLoopHVACs()))

    def test_doas_with_vrf_zeroes_terminal_oa(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'DOAS with VRF', zones)

        self.assertEqual(1, len(result.air_loops), 'the DOAS')
        terminal = model.getZoneHVACTerminalUnitVariableRefrigerantFlows()[0]
        self.assertAlmostEqual(
            1.0e-6, terminal.outdoorAirFlowRateDuringCoolingOperation().get(), delta=1e-10,
            msg='DOAS ventilates; terminal OA ~zero')

    def test_gshp_variant_ground_hx_no_boiler(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(
            model, 'DOAS with water source heat pumps with ground source heat pump', zones)

        self.assertEqual(1, len(model.getGroundHeatExchangerVerticals()))
        self.assertEqual(0, len(model.getBoilerHotWaters()), 'GSHP loop has no boiler')
        self.assertEqual(len(zones), len(model.getZoneHVACWaterToAirHeatPumps()))

    def test_cooling_tower_wshp_variant(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(
            model, 'DOAS with water source heat pumps cooling tower with boiler', zones)

        self.assertEqual(1, len(model.getCoolingTowerSingleSpeeds()))
        self.assertEqual(0, len(model.getEvaporativeFluidCoolerSingleSpeeds()))
        self.assertEqual(1, len(model.getBoilerHotWaters()))

    def test_fan_coil_air_cooled_chiller_district_hot_water(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(
            model, 'DOAS with fan coil air-cooled chiller with district hot water', zones)

        chillers = model.getChillerElectricEIRs()
        self.assertEqual(1, len(chillers), 'single air-cooled chiller')
        self.assertEqual('AirCooled', chillers[0].condenserType())
        self.assertEqual(0, len(model.getCoolingTowerSingleSpeeds()),
                         'no condenser loop for air-cooled')
        self.assertEqual(0, len(model.getBoilerHotWaters()), 'district hot water, no boilers')
        districts = len(model.getDistrictHeatingWaters())
        self.assertGreaterEqual(districts, 1)
        self.assertEqual(len(zones), len(model.getZoneHVACFourPipeFanCoils()))

    def test_fan_coil_district_chilled_water(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(
            model, 'DOAS with fan coil district chilled water with boiler', zones)

        self.assertEqual(0, len(model.getChillerElectricEIRs()))
        self.assertEqual(1, len(model.getDistrictCoolings()))
        self.assertEqual(2, len(model.getBoilerHotWaters()))

    def test_zone_ervs(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'Zone ERVs', zones)

        ervs = model.getZoneHVACEnergyRecoveryVentilators()
        self.assertEqual(len(zones), len(ervs))
        self.assertEqual(len(zones), len(model.getHeatExchangerAirToAirSensibleAndLatents()))


if __name__ == '__main__':
    unittest.main()
