import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk


@needs_sdk
class TestCbecsNames(unittest.TestCase):
    """CBECS descriptive names mapped onto the gem's families (first increment: the
    clean-topology matches). Zone partitioning (heated-only vs cooled, unit heaters
    for leftovers) remains the caller's job, as in openstudio-standards cbecs_hvac."""

    def test_baseboard_electric(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'Baseboard electric', zones)

        self.assertEqual(0, len(result.air_loops), 'baseboards-only: no air system')
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))
        self.assertEqual(0, len(model.getAirLoopHVACs()))
        self.assertEqual(0, len(model.getPlantLoops()))

    def test_baseboard_gas_boiler(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'Baseboard gas boiler', zones)

        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(2, len(model.getBoilerHotWaters()))
        self.assertTrue(all(b.fuelType() == 'NaturalGas' for b in model.getBoilerHotWaters()))

    def test_psz_ac_gas_coil_builds_one_unit_per_zone(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, 'PSZ-AC with gas coil', zones)

        # CBECS/90.1 convention: one packaged unit per zone
        self.assertEqual(len(zones), len(result.air_loops))
        self.assertTrue(all(len(al.thermalZones()) == 1 for al in result.air_loops))
        self.assertEqual(len(zones), len(model.getCoilCoolingDXSingleSpeeds()))
        self.assertEqual(len(zones), len(model.getCoilHeatingGass()))
        self.assertEqual(len(zones), len(model.getSetpointManagerSingleZoneReheats()))
        # each unit controls its own zone
        for spm in model.getSetpointManagerSingleZoneReheats():
            al = spm.airLoopHVAC().get()
            self.assertEqual(str(al.thermalZones()[0].handle()),
                             str(spm.controlZone().get().handle()))
        self.assertEqual(0, len(model.getZoneHVACBaseboardConvectiveElectrics()),
                         "baseboard_type 'None'")

    def test_psz_ac_electric_coil(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'PSZ-AC with electric coil', zones)
        self.assertEqual(len(zones), len(model.getCoilHeatingElectrics()))
        self.assertEqual(0, len(model.getCoilHeatingGass()))

    def test_catalog_filter_by_origin(self):
        # Ruby Hash#[] yields nil for rows without an 'origin' key; .get mirrors that.
        cbecs = [r for r in modeling.systems() if r.get('origin') == 'cbecs']
        self.assertGreaterEqual(len(cbecs), 4)


if __name__ == '__main__':
    unittest.main()
