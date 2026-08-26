import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk


@needs_sdk
class TestZoneTerminal(unittest.TestCase):
    def test_ptac_with_baseboard_electric(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'PTAC with baseboard electric', zones)

        self.assertEqual([], result.air_loops, 'self-ventilating: no central air system')
        ptacs = model.getZoneHVACPackagedTerminalAirConditioners()
        self.assertEqual(len(zones), len(ptacs))
        # no-heat PTAC: always-off zero-capacity electric section (baseboards do the heating)
        for ptac in ptacs:
            coil = ptac.heatingCoil().to_CoilHeatingElectric().get()
            self.assertEqual(0.0, coil.nominalCapacity().get())
            self.assertIn('Off', coil.availabilitySchedule().nameString())
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))
        self.assertEqual(0, len(model.getBoilerHotWaters()))

    def test_ptac_with_baseboard_gas_boiler(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'PTAC with baseboard gas boiler', zones)

        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(2, len(model.getBoilerHotWaters()))
        self.assertTrue(all(b.fuelType() == 'NaturalGas'
                            for b in model.getBoilerHotWaters()))

    def test_pthp(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'PTHP', zones)

        pthps = model.getZoneHVACPackagedTerminalHeatPumps()
        self.assertEqual(len(zones), len(pthps))
        for pthp in pthps:
            self.assertTrue(pthp.heatingCoil().to_CoilHeatingDXSingleSpeed().is_initialized())
            self.assertTrue(
                pthp.supplementalHeatingCoil().to_CoilHeatingElectric().is_initialized())

    def test_window_ac(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'Window AC with baseboard electric', zones)

        acs = model.getZoneHVACPackagedTerminalAirConditioners()
        self.assertEqual(len(zones), len(acs))
        coil = acs[0].coolingCoil().to_CoilCoolingDXSingleSpeed().get()
        cop = coil.ratedCOP()
        if hasattr(cop, 'is_initialized'):
            cop = cop.get()
        self.assertAlmostEqual(2.49, cop, delta=0.01, msg='EER 8.5 -> COP ~2.49')
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))

    def test_unit_heaters(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'Gas unit heaters', zones)

        heaters = model.getZoneHVACUnitHeaters()
        self.assertEqual(len(zones), len(heaters))
        self.assertEqual(len(zones), len(model.getCoilHeatingGass()))

    def test_composite_psz_gas_boiler(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'PSZ-AC with gas boiler', zones)

        self.assertEqual(len(zones), len(result.air_loops), 'per-zone packaged units')
        self.assertEqual(len(zones), len(model.getCoilHeatingWaters()),
                         'hot-water coils on each unit')
        self.assertEqual(2, len(model.getBoilerHotWaters()))
        self.assertTrue(all(b.fuelType() == 'NaturalGas'
                            for b in model.getBoilerHotWaters()))

    def test_composite_vav_chiller_gas_boiler_reheat(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'VAV chiller with gas boiler reheat', zones)

        self.assertEqual(len(zones), len(model.getAirTerminalSingleDuctVAVReheats()))
        self.assertEqual(1 + len(zones), len(model.getCoilHeatingWaters()),
                         'main + reheat coils')
        self.assertTrue(len(model.getChillerElectricEIRs()))
        self.assertTrue(all(b.fuelType() == 'NaturalGas'
                            for b in model.getBoilerHotWaters()))


if __name__ == '__main__':
    unittest.main()
