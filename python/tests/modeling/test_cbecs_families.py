import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk


@needs_sdk
class TestCbecsFamilies(unittest.TestCase):
    """Covers CBECS system families: forced-air furnace, residential central AC,
    district hot water baseboards, PVAV with gas boiler reheat, direct evap coolers,
    WSHP, and the DOAS fan-coil/WSHP composites."""

    def test_forced_air_furnace(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'Forced air furnace', zones)

        self.assertEqual(len(zones), len(result.air_loops), 'one furnace loop per zone')
        self.assertEqual(len(zones), len(model.getCoilHeatingGass()))
        self.assertEqual(0, len(model.getCoilCoolingDXSingleSpeeds()), 'heating only')
        self.assertEqual(len(zones), len(model.getAirLoopHVACOutdoorAirSystems()), 'ventilating')

    def test_residential_ac_composite(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'Residential AC with baseboard electric', zones)

        self.assertEqual('composite', result.family)
        self.assertEqual(len(zones), len(result.air_loops))
        self.assertEqual(len(zones), len(model.getCoilCoolingDXSingleSpeeds()))
        self.assertEqual(0, len(model.getCoilHeatingGass()), 'cooling-only central AC')
        self.assertEqual(0, len(model.getAirLoopHVACOutdoorAirSystems()),
                         'no OA on residential AC')
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))

    def test_baseboard_district_hot_water(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'Baseboard district hot water', zones)

        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(0, len(model.getBoilerHotWaters()), 'district source, no boilers')
        districts = len(model.getDistrictHeatingWaters()) + (
            len(model.getDistrictHeatings()) if hasattr(model, 'getDistrictHeatings') else 0)
        self.assertGreaterEqual(districts, 1)

    def test_pvav_dx_cooling(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'PVAV with gas boiler reheat', zones)

        self.assertEqual(1, len(model.getCoilCoolingDXTwoSpeeds()), 'packaged DX cooling')
        self.assertEqual(0, len(model.getChillerElectricEIRs()), 'no chiller plant')
        self.assertEqual(len(zones), len(model.getAirTerminalSingleDuctVAVReheats()))
        self.assertEqual(1 + len(zones), len(model.getCoilHeatingWaters()),
                         'HW main + reheat from gas boiler')
        self.assertTrue(all(b.fuelType() == 'NaturalGas' for b in model.getBoilerHotWaters()))

    def test_direct_evap_coolers_with_baseboards(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'Direct evap coolers with baseboard electric', zones)

        self.assertEqual(len(zones), len(model.getEvaporativeCoolerDirectResearchSpecials()))
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))
        spms = model.getSetpointManagerFollowOutdoorAirTemperatures()
        self.assertEqual(len(zones), len(spms))
        self.assertEqual('OutdoorAirWetBulb', spms[0].referenceTemperatureType())

    def test_doas_with_wshp_composite(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(
            model, 'DOAS with water source heat pumps fluid cooler with boiler', zones)

        # DOAS half
        self.assertEqual(1, len(result.air_loops))
        self.assertEqual(len(zones), len(model.getAirTerminalSingleDuctUncontrolleds()))
        # WSHP half: per-zone units on the heat pump loop
        wshps = model.getZoneHVACWaterToAirHeatPumps()
        self.assertEqual(len(zones), len(wshps))
        hp_loop = next((pl for pl in model.getPlantLoops()
                        if pl.nameString() == 'Heat Pump Loop'), None)
        self.assertIsNotNone(hp_loop)
        self.assertEqual(1, len(model.getEvaporativeFluidCoolerSingleSpeeds()))
        self.assertEqual(1, len(model.getBoilerHotWaters()))
        self.assertEqual(len(zones), len(model.getCoilHeatingWaterToAirHeatPumpEquationFits()))
        self.assertTrue(all(c.plantLoop().is_initialized()
                            for c in model.getCoilHeatingWaterToAirHeatPumpEquationFits()))

    def test_doas_with_fan_coils_composite(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'DOAS with fan coil chiller with boiler', zones)

        # exactly ONE air loop (the DOAS) — the fan-coil part must not build its MAU
        self.assertEqual(1, len(result.air_loops))
        self.assertEqual(1, len(model.getAirLoopHVACs()))
        self.assertEqual(len(zones), len(model.getZoneHVACFourPipeFanCoils()))
        # full hydronic plant from the fan-coil part
        self.assertEqual(2, len(model.getChillerElectricEIRs()))
        self.assertEqual(2, len(model.getBoilerHotWaters()))
        self.assertEqual(1, len(model.getCoolingTowerSingleSpeeds()))


if __name__ == '__main__':
    unittest.main()
