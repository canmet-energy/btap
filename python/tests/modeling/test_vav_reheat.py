import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk

ELECTRIC_SCROLL = 'MZ BU RTU Electric Heating Coil Scroll Chiller and Electric Baseboard'
HW_CENTRIFUGAL = 'MZ BU RTU Hot Water Heating Coil Centrifugal Chiller and Hot Water Baseboard'


@needs_sdk
class TestVAVReheat(unittest.TestCase):
    def test_electric_vav_builds_full_plant_and_air_side(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, ELECTRIC_SCROLL, zones)

        # fixture has one story containing all zones -> one air loop
        self.assertEqual(1, len(result.air_loops))
        air_loop = result.air_loops[0]
        self.assertEqual(len(zones), len(air_loop.thermalZones()))

        # supply + return VAV fans with load-bearing names
        fans = model.getFanVariableVolumes()
        self.assertEqual(2, len(fans))
        self.assertTrue(any('Supply' in f.nameString() for f in fans))
        self.assertTrue(any('Return' in f.nameString() for f in fans))

        # chilled-water cooling coil on the CHW loop; electric heat (1 main + 5 reheat)
        self.assertEqual(1, len(model.getCoilCoolingWaters()))
        self.assertEqual(1 + len(zones), len(model.getCoilHeatingElectrics()))

        # chilled + condenser plant with named chillers and a cooling tower
        chillers = model.getChillerElectricEIRs()
        self.assertEqual(2, len(chillers))
        self.assertEqual(['Primary Chiller WaterCooled Scroll',
                          'Secondary Chiller WaterCooled Scroll'],
                         sorted(c.nameString() for c in chillers))
        self.assertEqual(1, len(model.getCoolingTowerSingleSpeeds()))
        self.assertEqual(2, len(model.getPlantLoops()),
                         'CHW + CW loops (no boiler for all-electric)')
        self.assertEqual(0, len(model.getBoilerHotWaters()))

        # VAV terminals with NECB minimums
        terminals = model.getAirTerminalSingleDuctVAVReheats()
        self.assertEqual(len(zones), len(terminals))
        for terminal in terminals:
            self.assertEqual(43.0, terminal.maximumReheatAirTemperature())
            self.assertEqual('Normal', terminal.damperHeatingAction())
            self.assertGreater(terminal.fixedMinimumAirFlowRate().get(), 0.0)

        # constant 13C supply-air setpoint
        spm = next((m for m in model.getSetpointManagerScheduleds()
                    if str(m.setpointNode().get().handle())
                    == str(air_loop.supplyOutletNode().handle())), None)
        self.assertIsNotNone(spm)

        # sizing: sparse sys6 block (13/13.1 SATs, 0.3 min flow ratio)
        s = air_loop.sizingSystem()
        self.assertEqual(13.0, s.centralCoolingDesignSupplyAirTemperature())
        self.assertEqual(13.1, s.centralHeatingDesignSupplyAirTemperature())
        ratio = s.centralHeatingMaximumSystemAirFlowRatio()
        if hasattr(ratio, 'is_initialized'):
            ratio = ratio.get()
        self.assertAlmostEqual(0.3, float(ratio), delta=1e-6)

    def test_hot_water_variant_builds_boiler_and_hydronic_coils(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, HW_CENTRIFUGAL, zones)

        self.assertEqual(2, len(model.getBoilerHotWaters()))
        self.assertEqual(3, len(model.getPlantLoops()), 'HW + CHW + CW')
        # 1 main + 5 reheat hot-water coils, all on the HW loop
        self.assertEqual(1 + len(zones), len(model.getCoilHeatingWaters()))
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertTrue(all('Centrifugal' in c.nameString()
                            for c in model.getChillerElectricEIRs()))

    def test_pipe_name_uses_sys6_token_order(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, ELECTRIC_SCROLL, zones,
                                       namer='necb_pipe_name')
        # sys6 legacy order: sh> BEFORE sc> (observed from legacy build)
        self.assertEqual('sys_6|mixed|shr>none|sh>c-e|sc>c-chw|ssf>vv|zh>b-e|zc>none|srf>vv|',
                         result.air_loops[0].nameString())

    def test_remove_existing_replaces_vav_with_psz(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, HW_CENTRIFUGAL, zones)
        self.assertTrue(len(model.getChillerElectricEIRs()))

        modeling.build_system(model, 'PSZ RTU Electric and DX Coils and Electric Baseboard',
                              zones, remove_existing=True)
        self.assertEqual(0, len(model.getChillerElectricEIRs()),
                         'chiller + condenser chain torn down')
        self.assertEqual(0, len(model.getCoolingTowerSingleSpeeds()))
        self.assertEqual(0, len(model.getBoilerHotWaters()))
        self.assertEqual(1, len(model.getAirLoopHVACs()))


if __name__ == '__main__':
    unittest.main()
