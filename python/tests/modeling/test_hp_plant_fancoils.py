import unittest

from tests.support import load_fixture, needs_sdk


@needs_sdk
class TestHpPlantFanCoils(unittest.TestCase):
    def test_hs14_gshp_plants_and_fancoils(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'hs14_cgshp_fancoils', zones,
                                       namer='necb_pipe_name')

        # zone side: 4-pipe fan coils + diffusers
        self.assertEqual(len(zones), len(model.getZoneHVACFourPipeFanCoils()))
        self.assertEqual(len(zones), len(model.getAirTerminalSingleDuctUncontrolleds()))

        # HW plant: W2W equation-fit HP with structural curves + electric boiler in series
        hps = model.getHeatPumpWaterToWaterEquationFitHeatings()
        self.assertEqual(1, len(hps))
        self.assertEqual('HEATPUMP_WATERTOWATER_HCAPF',
                         hps[0].heatingCapacityCurve().nameString())
        self.assertEqual(1, len(model.getBoilerHotWaters()))

        # CHW plant: water-cooled + series air-cooled chillers
        chillers = model.getChillerElectricEIRs()
        self.assertEqual(['ChillerAirCooled', 'ChillerWaterCooled'],
                         sorted(c.nameString() for c in chillers))

        # GLHX condenser loop: district heating + cooling in series, HP + chiller on demand
        glhx = next((pl for pl in model.getPlantLoops()
                     if 'GLHX' in pl.nameString()), None)
        self.assertIsNotNone(glhx)
        self.assertEqual(1, len(model.getDistrictCoolings()))
        demand_types = [c.iddObjectType().valueName() for c in glhx.demandComponents()]
        self.assertTrue(any('HeatPump' in t for t in demand_types))
        self.assertTrue(any('Chiller' in t for t in demand_types))
        self.assertEqual(3, len(model.getPlantLoops()), 'HW + CHW + GLHX')

        # all water coils (air loop + fan coils) attached to the HP plants
        self.assertTrue(all(c.plantLoop().is_initialized()
                            for c in model.getCoilHeatingWaters()))
        self.assertTrue(all(c.plantLoop().is_initialized()
                            for c in model.getCoilCoolingWaters()))

        # legacy naming (coil_chw segment dropped by the namer; sh>none for coil_hw; raw fancoil tokens)
        self.assertEqual('sys_1|doas|shr>none|sh>none|ssf>cv|zh>fancoil_4pipe|zc>fancoil_4pipe|srf>none|',
                         result.air_loops[0].nameString())

    def test_hs15_cawhp_companion_heat_pumps(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'hs15_cawhp_fancoils', zones)

        htg_hps = model.getHeatPumpPlantLoopEIRHeatings()
        clg_hps = model.getHeatPumpPlantLoopEIRCoolings()
        self.assertEqual(1, len(htg_hps))
        self.assertEqual(1, len(clg_hps))
        hp = htg_hps[0]
        self.assertEqual('AirSource', hp.condenserType(),
                         "condenser type correct (legacy 'AirSoure' typo, fixed both sides since #2119)")
        self.assertAlmostEqual(-15.0, hp.minimumSourceInletTemperature(), delta=1e-6)
        self.assertTrue(hp.companionCoolingHeatPump().is_initialized())
        self.assertEqual('CAWHP-HS15-HCAPFT',
                         hp.capacityModifierFunctionofTemperatureCurve().nameString())
        self.assertEqual(1, len(model.getBoilerHotWaters()))
        self.assertEqual(2, len(model.getPlantLoops()), 'HW + CHW (no ground loop)')
        self.assertEqual(0, len(model.getChillerElectricEIRs()))

    def test_hs16_uses_ashp_doas(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'hs16_ashp_cawhp_fancoils', zones)

        self.assertEqual(1, sum(1 for c in model.getCoilCoolingDXSingleSpeeds()
                                if 'ASHP' in c.nameString()))
        self.assertEqual(1, sum(1 for c in model.getCoilHeatingDXSingleSpeeds()
                                if 'ASHP' in c.nameString()))
        # supplemental electric coil on the DOAS + CAWHP plants below
        self.assertEqual(1, len(model.getHeatPumpPlantLoopEIRHeatings()))
        # fan-coil water coils go to the CAWHP plants (air loop uses DX, so counts = zones)
        self.assertEqual(len(zones), len(model.getCoilHeatingWaters()))
        self.assertTrue(all(c.plantLoop().is_initialized()
                            for c in model.getCoilHeatingWaters()))


if __name__ == '__main__':
    unittest.main()
