"""Port of btap-costing/test/test_hvac_costing_e2e.rb.

End-to-end costing: build -> (hard-)size -> cost. Uses hard-sized values so
the test is standalone and fast; a full sizing-run flow behaves identically
via autosized accessors."""

import unittest

import btap.modeling as modeling
from btap.costing.hvac import report as hvac_report
from btap.costing.hvac.ventilation import VentilationQuantifier
from btap.modeling.hvac.builder import FAMILIES
from tests.costing.support import load_fixture, needs_sdk


def _note(item):
    return str(item.get('note', ''))


@needs_sdk
class TestCostingE2E(unittest.TestCase):
    def sorted_zones(self, model):
        from btap._compat import sorted_by_name
        return sorted_by_name(model.getThermalZones())

    def test_family_ahu_manifest_covers_air_loop_families(self):
        air_loop_families = [f for f in FAMILIES
                             if f not in ('baseboards', 'zone_terminal', 'unit_heaters',
                                          'wshp', 'vrf', 'zone_ervs')]
        for family in air_loop_families:
            self.assertIn(family, VentilationQuantifier.FAMILY_SYS_TYPE,
                          f"family '{family}' missing from the AHU manifest")

    def test_psz_system_costs_end_to_end(self):
        model = load_fixture()
        zones = self.sorted_zones(model)
        result = modeling.build_system(
            model, 'PSZ RTU Electric and DX Coils and Electric Baseboard', zones)

        # hard-size in lieu of a sizing run
        for al in result.air_loops:
            al.setDesignSupplyAirFlowRate(2.0)  # m3/s (~4238 cfm)
        for c in model.getCoilCoolingDXSingleSpeeds():
            c.setRatedTotalCoolingCapacity(40_000.0)
        for b in model.getZoneHVACBaseboardConvectiveElectrics():
            b.setNominalCapacity(2_000.0)

        report = hvac_report.cost(model, systems=[result], city='TORONTO',
                                  province_state='ONTARIO')

        self.assertGreater(report.total, 0)
        self.assertGreater(report.by_category.get('VENTILATION', 0.0), 0,
                           'AHU assembly costed')
        self.assertGreater(report.by_category.get('DISTRIBUTION', 0.0), 0,
                           'zone duct/diffusers costed')
        self.assertGreater(report.by_category.get('ZONAL', 0.0), 0,
                           'electric baseboards costed')
        self.assertTrue(any('AHU' in _note(i) for i in report.items))
        self.assertTrue(any('mech room -> roof' in _note(i) for i in report.items),
                        'geometry-derived utility runs costed')

    def test_hydronic_vav_costs_plant_and_ahu(self):
        model = load_fixture()
        zones = self.sorted_zones(model)
        result = modeling.build_system(
            model,
            'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard',
            zones)

        for al in result.air_loops:
            al.setDesignSupplyAirFlowRate(3.0)
        for b in model.getBoilerHotWaters():
            b.setNominalCapacity(80_000.0)
        for c in model.getChillerElectricEIRs():
            c.setReferenceCapacity(120_000.0)
        for p in model.getPumpVariableSpeeds():
            p.setRatedPowerConsumption(1500.0)
        for c in model.getCoilHeatingWaterBaseboards():
            c.setHeatingDesignCapacity(4000.0)

        report = hvac_report.cost(model, systems=[result], city='VANCOUVER',
                                  province_state='BRITISH COLUMBIA')

        self.assertGreater(report.by_category.get('HEATING_COOLING', 0.0), 0,
                           'boilers + chillers + tower + pumps')
        self.assertGreater(report.by_category.get('VENTILATION', 0.0), 0,
                           'sys6 HW/CHW AHU assembly')
        self.assertTrue(any('chiller' in _note(i) for i in report.items))
        self.assertTrue(any('boiler' in _note(i) for i in report.items))

    def test_foreign_air_loop_warns_but_still_costs_plant(self):
        import openstudio

        model = load_fixture()
        zones = self.sorted_zones(model)
        modeling.build_system(model, 'Baseboard gas boiler', zones)
        for b in model.getBoilerHotWaters():
            b.setNominalCapacity(50_000.0)
        # a hand-made air loop the gem did not build
        foreign = openstudio.model.AirLoopHVAC(model)
        foreign.setName('SomeoneElsesLoop')
        foreign.setDesignSupplyAirFlowRate(1.0)

        report = hvac_report.cost(model, city='TORONTO', province_state='ONTARIO')
        self.assertGreater(report.by_category.get('HEATING_COOLING', 0.0), 0)
        self.assertTrue(any('SomeoneElsesLoop' in w for w in report.warnings))

    def test_city_inferred_from_site(self):
        model = load_fixture()
        model.getSite().setLatitude(43.65)
        model.getSite().setLongitude(-79.38)
        zones = self.sorted_zones(model)
        modeling.build_system(model, 'Electric unit heaters', zones)
        for c in model.getCoilHeatingElectrics():
            c.setNominalCapacity(5000.0)
        report = hvac_report.cost(model)
        self.assertEqual('TORONTO', report.city.upper())


if __name__ == '__main__':
    unittest.main()
