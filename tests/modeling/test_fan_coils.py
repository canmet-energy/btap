import unittest

from tests.support import load_fixture, needs_sdk

FPFC_DX = 'FPFC MAU DX Coils with Scroll Chiller'
FPFC_CHW = 'FPFC MAU Chilled Water Coils with Centrifugal Chiller'
TPFC_DX = 'TPFC MAU DX Coils with Scroll Chiller'


@needs_sdk
class TestFanCoils(unittest.TestCase):
    def test_fpfc_dx_builds_mau_fan_coils_and_full_plant(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, FPFC_DX, zones)

        # one MAU air loop delivering to all zones through uncontrolled diffusers
        self.assertEqual(1, len(result.air_loops))
        self.assertEqual(len(zones), len(result.air_loops[0].thermalZones()))
        self.assertEqual(len(zones), len(model.getAirTerminalSingleDuctUncontrolleds()))

        # per-zone four-pipe fan coils with hydronic coils on both loops
        self.assertEqual(len(zones), len(model.getZoneHVACFourPipeFanCoils()))
        self.assertEqual(len(zones), len(model.getCoilHeatingWaters()))
        self.assertEqual(len(zones), len(model.getCoilCoolingWaters()),
                         'FC cooling coils only (MAU is DX)')

        # MAU: CV fan + gas heat + DX cooling with NECB curves on the seasonal cooling schedule
        self.assertEqual(1 + len(zones), len(model.getFanConstantVolumes()),
                         'MAU fan + one per fan coil')
        self.assertEqual(1, len(model.getCoilHeatingGass()))
        dxs = model.getCoilCoolingDXSingleSpeeds()
        self.assertTrue(dxs)
        dx = dxs[0]
        self.assertEqual('tpfc_clg_availability',
                         dx.availabilitySchedule().nameString(),
                         'legacy quirk preserved')

        # full plant: HW + CHW + CW
        self.assertEqual(3, len(model.getPlantLoops()))
        self.assertEqual(2, len(model.getBoilerHotWaters()))
        self.assertEqual(2, len(model.getChillerElectricEIRs()))
        self.assertEqual(1, len(model.getCoolingTowerSingleSpeeds()))

        # MAU SPM preserved legacy min/max (13.1 / 13.0 inverted)
        spm = model.getSetpointManagerSingleZoneReheats()[0]
        self.assertAlmostEqual(13.1, spm.minimumSupplyAirTemperature(), delta=1e-6)
        self.assertAlmostEqual(13.0, spm.maximumSupplyAirTemperature(), delta=1e-6)

    def test_tpfc_uses_seasonal_availability_schedules(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, TPFC_DX, zones)

        fc = model.getZoneHVACFourPipeFanCoils()[0]
        self.assertEqual(
            'tpfc_htg_availability',
            fc.heatingCoil().to_CoilHeatingWater().get().availabilitySchedule().nameString())
        self.assertEqual(
            'tpfc_clg_availability',
            fc.coolingCoil().to_CoilCoolingWater().get().availabilitySchedule().nameString())

    def test_hydronic_mau_cooling_coil_on_chw_loop(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, FPFC_CHW, zones)

        self.assertEqual(0, len(model.getCoilCoolingDXSingleSpeeds()),
                         'hydronic MAU: no DX')
        self.assertEqual(len(zones) + 1, len(model.getCoilCoolingWaters()),
                         'FC coils + MAU coil')
        self.assertTrue(all('Centrifugal' in c.nameString()
                            for c in model.getChillerElectricEIRs()))

    def test_pipe_names_match_legacy_convention(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        r1 = modeling.build_system(model, FPFC_DX, zones, namer='necb_pipe_name')
        self.assertEqual('sys_2|doas|shr>none|sc>dx|sh>c-g|ssf>cv|zh>fpfc|zc>fpfc|srf>none|',
                         r1.air_loops[0].nameString())

        m2 = load_fixture()
        z2 = sorted_by_name(m2.getThermalZones())
        r2 = modeling.build_system(m2, TPFC_DX, z2, namer='necb_pipe_name')
        self.assertEqual('sys_5|doas|shr>none|sc>dx|sh>c-g|ssf>cv|zh>tpfc|zc>tpfc|srf>none|',
                         r2.air_loops[0].nameString())

    def test_remove_existing_tears_down_fan_coil_plant(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, FPFC_DX, zones)
        self.assertEqual(3, len(model.getPlantLoops()))

        modeling.build_system(model, 'PSZ RTU Electric and DX Coils and Electric Baseboard',
                              zones, remove_existing=True)
        self.assertEqual(0, len(model.getPlantLoops()), 'HW + CHW + CW all reclaimed')
        self.assertEqual(0, len(model.getZoneHVACFourPipeFanCoils()))
        self.assertEqual(1, len(model.getAirLoopHVACs()))


if __name__ == '__main__':
    unittest.main()
