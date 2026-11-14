import unittest

from tests.support import load_fixture, needs_sdk

ELEC = 'PSZ MAU Electric and DX Coils and Electric Baseboard with PTAC'
HW = 'PSZ MAU Hot Water and DX Coils and Hot Water Baseboard with PTAC'


@needs_sdk
class TestMauPtac(unittest.TestCase):
    def test_electric_mau_ptac_builds(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, ELEC, zones)

        # one 100% OA MAU + per-zone PTAC + baseboards + diffusers
        self.assertEqual(1, len(result.air_loops))
        air_loop = result.air_loops[0]
        self.assertEqual(len(zones), len(air_loop.thermalZones()))
        self.assertEqual(len(zones),
                         len(model.getZoneHVACPackagedTerminalAirConditioners()))
        self.assertEqual(len(zones),
                         len(model.getZoneHVACBaseboardConvectiveElectrics()))
        self.assertEqual(len(zones), len(model.getAirTerminalSingleDuctUncontrolleds()))
        self.assertEqual(len(zones) + 1, len(model.getCoilCoolingDXSingleSpeeds()),
                         'MAU DX + one per PTAC')
        self.assertEqual(0, len(model.getBoilerHotWaters()))

        # MAU sizing: 100% OA on ventilation requirement, 20C constant supply
        s = air_loop.sizingSystem()
        self.assertTrue(s.allOutdoorAirinCooling())
        self.assertTrue(s.allOutdoorAirinHeating())
        self.assertEqual('VentilationRequirement', s.typeofLoadtoSizeOn())
        self.assertEqual(43.0, s.centralHeatingDesignSupplyAirTemperature())
        sat = next((sch for sch in model.getScheduleRulesets()
                    if sch.nameString() == 'Makeup-Air Unit Supply Air Temp'), None)
        self.assertIsNotNone(sat)

        # PTAC details: always-off heating section + fan op schedule, ~zero OA
        ptac = model.getZoneHVACPackagedTerminalAirConditioners()[0]
        fan_op_sch = ptac.supplyAirFanOperatingModeSchedule()
        if hasattr(fan_op_sch, 'get'):
            fan_op_sch = fan_op_sch.get()
        self.assertEqual('Always Off', fan_op_sch.nameString())
        self.assertEqual(
            'Always Off',
            ptac.heatingCoil().to_CoilHeatingElectric().get()
                .availabilitySchedule().nameString())
        self.assertAlmostEqual(1.0e-5,
                               ptac.outdoorAirFlowRateDuringCoolingOperation().get(),
                               delta=1e-9)

    def test_hot_water_variant_builds_boiler_for_mau_and_baseboards(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, HW, zones)

        self.assertEqual(2, len(model.getBoilerHotWaters()))
        self.assertEqual(1, len(model.getCoilHeatingWaters()), 'MAU hot-water coil')
        self.assertEqual(len(zones),
                         len(model.getZoneHVACBaseboardConvectiveWaters()))

    def test_pipe_name_matches_legacy_convention(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, ELEC, zones, namer='necb_pipe_name')
        self.assertEqual('sys_1|doas|shr>none|sc>dx|sh>c-e|ssf>cv|zh>b-e|zc>ptac|srf>none|',
                         result.air_loops[0].nameString())


if __name__ == '__main__':
    unittest.main()
