import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk

SYS3_ASHP = 'PSZ RTU ASHP with Gas and ASHP with Gas Supp. Heat Coils and Electric Baseboard'
SYS4_ASHP = ('PSZ RTU with exhaust ASHP with Electric and ASHP with Electric Supp. Heat Coils '
             'and Hot Water Baseboard')
SYS1_ASHP = 'PSZ RTU ASHP with Gas and ASHP Coils and Electric Baseboard with Gas Reheat'


@needs_sdk
class TestReferenceHp(unittest.TestCase):
    """NECB reference heat pump variants (sys1/3/4 ASHP). The legacy regional-fuel lookup is
    unnecessary here: the supplemental/reheat fuel is encoded in the descriptive name."""

    def test_sys3_ashp_dx_heat_with_gas_supplemental(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, SYS3_ASHP, zones, namer='necb_pipe_name')

        self.assertEqual(1, len(result.air_loops), 'NECB shared-unit convention')
        # ASHP DX coils with the load-bearing _ashp names + NECB curves
        clg = model.getCoilCoolingDXSingleSpeeds()[0]
        htg = model.getCoilHeatingDXSingleSpeeds()[0]
        self.assertEqual('CoilCoolingDXSingleSpeed_ashp', clg.nameString())
        self.assertEqual('CoilHeatingDXSingleSpeed_ashp', htg.nameString())
        self.assertAlmostEqual(
            -10.0, htg.minimumOutdoorDryBulbTemperatureforCompressorOperation(), delta=1e-6)
        self.assertEqual(1, len(model.getCoilHeatingGass()), 'gas supplemental coil on the loop')
        # DX sizing factors 1.0/1.3
        sz = zones[0].sizingZone()
        self.assertEqual(1.0, sz.zoneCoolingSizingFactor().get())
        self.assertEqual(1.3, sz.zoneHeatingSizingFactor().get())
        # legacy naming: sc>ashp + sh>ashp>c-g
        self.assertEqual('sys_3|mixed|shr>none|sc>ashp|sh>ashp>c-g|ssf>cv|zh>b-e|zc>none|srf>none|',
                         result.air_loops[0].nameString())

    def test_sys4_ashp_electric_supp_hot_water_baseboards(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, SYS4_ASHP, zones)

        self.assertEqual(1, len(model.getCoilHeatingDXSingleSpeeds()))
        self.assertEqual(1, len(model.getCoilHeatingElectrics()), 'electric supplemental')
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(2, len(model.getBoilerHotWaters()))

    def test_sys1_ashp_mau_with_cav_reheat_terminals(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, SYS1_ASHP, zones, namer='necb_pipe_name')

        air_loop = result.air_loops[0]
        # MAU: ASHP DX heat/cool, warmest SPM 13-20, Total load sizing
        self.assertEqual(1, len(model.getCoilHeatingDXSingleSpeeds()))
        spms = model.getSetpointManagerWarmests()
        self.assertEqual(1, len(spms))
        self.assertAlmostEqual(20.0, spms[0].maximumSetpointTemperature(), delta=1e-6)
        self.assertEqual('Total', air_loop.sizingSystem().typeofLoadtoSizeOn())

        # zones: CAV reheat terminals with gas reheat (fuel from the name), NO PTACs
        terminals = model.getAirTerminalSingleDuctConstantVolumeReheats()
        self.assertEqual(len(zones), len(terminals))
        self.assertEqual(len(zones), len(model.getCoilHeatingGass()),
                         'gas reheat coil per terminal')
        self.assertEqual(0, len(model.getZoneHVACPackagedTerminalAirConditioners()))
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))

        # legacy naming: sys_oa 'mixed' for the ref-HP variant, zc>none
        self.assertEqual('sys_1|mixed|shr>none|sc>ashp|sh>ashp>c-g|ssf>cv|zh>b-e|zc>none|srf>none|',
                         air_loop.nameString())


if __name__ == '__main__':
    unittest.main()
