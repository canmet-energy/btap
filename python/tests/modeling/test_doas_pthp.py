import unittest

from tests.support import load_fixture, needs_sdk

HS11 = 'hs11_ashp_pthp'


@needs_sdk
class TestDoasPthp(unittest.TestCase):
    def test_hs11_builds_doas_and_zone_pthps(self):
        from btap._compat import sorted_by_name
        import btap.modeling as modeling

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, HS11, zones)

        # one DOAS loop serving all zones through uncontrolled diffusers
        self.assertEqual(1, len(result.air_loops))
        air_loop = result.air_loops[0]
        self.assertEqual(len(zones), len(air_loop.thermalZones()))
        self.assertEqual(len(zones), len(model.getAirTerminalSingleDuctUncontrolleds()))

        # DOAS sizing: 100% OA on ventilation requirement, 13/22 SATs
        s = air_loop.sizingSystem()
        self.assertTrue(s.allOutdoorAirinCooling())
        self.assertTrue(s.allOutdoorAirinHeating())
        self.assertEqual('VentilationRequirement', s.typeofLoadtoSizeOn())
        self.assertEqual(22.0, s.centralHeatingDesignSupplyAirTemperature())

        # air-loop ASHP: DX heat + DX cool + electric supplemental + CV supply fan
        self.assertEqual(1, sum(1 for c in model.getCoilCoolingDXSingleSpeeds()
                                if 'ASHP' in c.nameString()))
        self.assertEqual(1, sum(1 for c in model.getCoilHeatingDXSingleSpeeds()
                                if 'ASHP' in c.nameString()))
        ashp_htg = next(c for c in model.getCoilHeatingDXSingleSpeeds()
                        if 'ASHP' in c.nameString())
        self.assertEqual('ReverseCycle', ashp_htg.defrostStrategy())
        self.assertTrue(any('Supply' in f.nameString()
                            for f in model.getFanConstantVolumes()))

        # per-zone PTHPs with DX coils + electric supplemental, ~zero OA
        pthps = model.getZoneHVACPackagedTerminalHeatPumps()
        self.assertEqual(len(zones), len(pthps))
        for pthp in pthps:
            self.assertTrue(pthp.heatingCoil().to_CoilHeatingDXSingleSpeed().is_initialized())
            self.assertTrue(pthp.coolingCoil().to_CoilCoolingDXSingleSpeed().is_initialized())
            self.assertTrue(
                pthp.supplementalHeatingCoil().to_CoilHeatingElectric().is_initialized())
            self.assertAlmostEqual(
                1.0e-6, pthp.outdoorAirFlowRateDuringCoolingOperation().get(),
                delta=1e-10)

        # ECM zone sizing: ABSOLUTE supply temps (not TemperatureDifference)
        sz = zones[0].sizingZone()
        self.assertEqual('SupplyAirTemperature',
                         sz.zoneCoolingDesignSupplyAirTemperatureInputMethod())
        self.assertEqual(13.0, sz.zoneCoolingDesignSupplyAirTemperature())
        self.assertEqual(43.0, sz.zoneHeatingDesignSupplyAirTemperature())

        self.assertEqual(0, len(model.getPlantLoops()),
                         'electric supplemental: no boiler')

    def test_hs11_pipe_name_matches_legacy_format(self):
        from btap._compat import sorted_by_name
        import btap.modeling as modeling

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, HS11, zones, namer='necb_pipe_name')
        self.assertEqual('sys_1|doas|shr>none|sc>ashp|sh>ashp|ssf>cv|zh>pthp|zc>pthp|srf>none|',
                         result.air_loops[0].nameString())


if __name__ == '__main__':
    unittest.main()
