import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk

ELECTRIC = 'PSZ RTU Electric and DX Coils and Electric Baseboard'
GAS_HW = 'PSZ RTU Gas and DX Coils and Hot Water Baseboard'
SYS4 = 'PSZ RTU with exhaust Gas and DX Coils and Electric Baseboard'


@needs_sdk
class TestPSZ(unittest.TestCase):
    def test_electric_psz_builds_on_bare_zones(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, ELECTRIC, zones)

        self.assertEqual(1, len(result.air_loops))
        air_loop = result.air_loops[0]
        self.assertEqual(1, len(model.getAirLoopHVACs()))
        self.assertEqual(len(zones), len(air_loop.thermalZones()))

        # topology: CV fan + electric coil + DX coil + OA system + SZR setpoint manager
        self.assertEqual(1, len(model.getFanConstantVolumes()))
        self.assertEqual(1, len(model.getCoilHeatingElectrics()))
        self.assertEqual(1, len(model.getCoilCoolingDXSingleSpeeds()))
        self.assertEqual(1, len(model.getAirLoopHVACOutdoorAirSystems()))
        spms = model.getSetpointManagerSingleZoneReheats()
        self.assertEqual(1, len(spms))
        self.assertEqual(13.0, spms[0].minimumSupplyAirTemperature())
        self.assertEqual(43.0, spms[0].maximumSupplyAirTemperature())
        self.assertEqual(str(result.control_zone.handle()),
                         str(spms[0].controlZone().get().handle()))

        # zone equipment: one electric baseboard + one uncontrolled diffuser per zone
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))
        self.assertEqual(len(zones), len(model.getAirTerminalSingleDuctUncontrolleds()))
        self.assertEqual(0, len(model.getBoilerHotWaters()),
                         'all-electric system must not create a boiler')

        # NECB curves on the DX coil
        coil = model.getCoilCoolingDXSingleSpeeds()[0]
        self.assertEqual(
            'DXCOOL-NECB2011-REF-CAPFT',
            coil.totalCoolingCapacityFunctionOfTemperatureCurve().nameString())
        self.assertEqual('CoilCoolingDXSingleSpeed_dx', coil.nameString())

    def test_zone_and_system_sizing_applied(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, ELECTRIC, zones)

        s = result.air_loops[0].sizingSystem()
        self.assertEqual(13.0, s.centralCoolingDesignSupplyAirTemperature())
        self.assertEqual(43.0, s.centralHeatingDesignSupplyAirTemperature())
        self.assertEqual('ZoneSum', s.systemOutdoorAirMethod())
        self.assertFalse(s.allOutdoorAirinCooling())

        for zone in zones:
            sz = zone.sizingZone()
            self.assertEqual('TemperatureDifference',
                             sz.zoneCoolingDesignSupplyAirTemperatureInputMethod())
            self.assertEqual(11.0, sz.zoneCoolingDesignSupplyAirTemperatureDifference())
            self.assertEqual(21.0, sz.zoneHeatingDesignSupplyAirTemperatureDifference())
            self.assertEqual(1.1, sz.zoneCoolingSizingFactor().get())
            self.assertEqual(1.3, sz.zoneHeatingSizingFactor().get())

        oa = model.getControllerOutdoorAirs()[0]
        self.assertEqual('ZoneSum',
                         oa.controllerMechanicalVentilation().systemOutdoorAirMethod())

    def test_gas_hot_water_builds_and_reuses_hw_loop(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, GAS_HW, zones)

        self.assertEqual(1, len(model.getCoilHeatingGass()))
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(2, len(model.getBoilerHotWaters()), 'primary + secondary boiler')
        self.assertEqual(sorted(['Primary Boiler', 'Secondary Boiler']),
                         sorted(b.nameString() for b in model.getBoilerHotWaters()))
        self.assertEqual(1, len(model.getPlantLoops()))

        # second hydronic system on other zones reuses the loop (no boiler proliferation)
        modeling.build_system(model, GAS_HW, [zones[0]], control_zone=zones[0],
                              remove_existing=True)
        self.assertEqual(2, len(model.getBoilerHotWaters()))
        self.assertEqual(1, len(model.getPlantLoops()))

    def test_sys4_control_zone_and_pipe_naming(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, SYS4, zones,
                                       control_zone=zones[2], namer='necb_pipe_name')
        self.assertEqual(zones[2], result.control_zone)
        self.assertEqual('sys_4|mixed|shr>none|sc>dx|sh>c-g|ssf>cv|zh>b-e|zc>none|srf>none|',
                         result.air_loops[0].nameString())

    def test_remove_existing_replaces(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, GAS_HW, zones)
        self.assertTrue(len(model.getBoilerHotWaters()))

        modeling.build_system(model, ELECTRIC, zones, remove_existing=True)
        self.assertEqual(0, len(model.getBoilerHotWaters()), 'orphaned boiler loop torn down')
        self.assertEqual(1, len(model.getAirLoopHVACs()))
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))
        self.assertEqual(0, len(model.getZoneHVACBaseboardConvectiveWaters()))

    def test_validation_errors(self):
        import openstudio

        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())

        outsider = openstudio.model.ThermalZone(model)
        with self.assertRaises(ValueError) as ctx:
            modeling.build_system(model, ELECTRIC, zones, control_zone=outsider)
        self.assertRegex(str(ctx.exception), r'control_zone')
        outsider.remove()

        for thermostat in model.getThermostatSetpointDualSetpoints():
            thermostat.remove()
        with self.assertRaises(ValueError) as ctx:
            modeling.build_system(model, ELECTRIC, list(model.getThermalZones()))
        self.assertRegex(str(ctx.exception), r'thermostat')


if __name__ == '__main__':
    unittest.main()
