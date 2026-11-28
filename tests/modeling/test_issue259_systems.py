"""#259: the builder options behind the systems the catalogue could not express.

Each test builds the catalogue row on the five-zone fixture and reads back
the OBJECTS the option exists to produce, so deleting the option's branch in
the builder fails here rather than leaving a row that silently builds its
twin. SDK only; nothing here runs EnergyPlus (the sizing sweep does).
"""

import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk


def _zones(model):
    from btap._compat import sorted_by_name
    return sorted_by_name(model.getThermalZones())


def _build(system, config=None):
    model = load_fixture()
    modeling.build_system(model, system, _zones(model), config=config)
    return model


def _supply_types(air_loop):
    return [c.iddObjectType().valueName() for c in air_loop.supplyComponents()
            if c.iddObjectType().valueName() != 'OS_Node']


@needs_sdk
class TestParallelFanPoweredBoxes(unittest.TestCase):

    def test_the_pfp_rows_build_a_parallel_piu_per_zone_with_electric_reheat(self):
        for system in ('pvav-elec-pfp', 'vav-elec-pfp-scrollchiller'):
            with self.subTest(system=system):
                model = _build(system)
                zones = _zones(model)
                boxes = model.getAirTerminalSingleDuctParallelPIUReheats()
                self.assertEqual(len(zones), len(boxes))
                self.assertEqual(0, len(model.getAirTerminalSingleDuctVAVReheats()))
                for box in boxes:
                    self.assertTrue(box.reheatCoil().to_CoilHeatingElectric().is_initialized())
                    self.assertTrue(box.fan().to_FanConstantVolume().is_initialized())

    def test_the_default_terminal_is_unchanged(self):
        model = _build('vav-elec-elecbb-scrollchiller')
        self.assertEqual(0, len(model.getAirTerminalSingleDuctParallelPIUReheats()))
        self.assertEqual(len(_zones(model)), len(model.getAirTerminalSingleDuctVAVReheats()))

    def test_an_unknown_terminal_type_is_refused_before_the_teardown(self):
        model = _build('bb-elecbb')
        before = len(model.getZoneHVACBaseboardConvectiveElectrics())
        with self.assertRaises(ValueError):
            modeling.build_system(model, 'vav-elec-elecbb-scrollchiller', _zones(model),
                                  config={'terminal_type': 'series_piu'})
        self.assertEqual(before, len(model.getZoneHVACBaseboardConvectiveElectrics()))


@needs_sdk
class TestDualDuctOnDirectCoils(unittest.TestCase):

    def test_a_gas_hot_deck_and_a_dx_cold_deck_with_no_plant(self):
        model = _build('ddvav-gas-dx')
        self.assertEqual(0, len(model.getPlantLoops()))
        (loop,) = model.getAirLoopHVACs()
        hot, cold = loop.supplyOutletNodes()
        types = _supply_types(loop)
        self.assertIn('OS_Coil_Heating_Gas', types)
        self.assertIn('OS_Coil_Cooling_DX_TwoSpeed', types)
        self.assertNotIn('OS_Coil_Heating_Water', types)
        self.assertNotIn('OS_Coil_Cooling_Water', types)
        self.assertEqual(len(_zones(model)), len(model.getAirTerminalDualDuctVAVs()))

    def test_the_hydronic_row_still_builds_water_coils(self):
        model = _build('ddvav-hw-gasboiler-scrollchiller')
        types = _supply_types(model.getAirLoopHVACs()[0])
        self.assertIn('OS_Coil_Heating_Water', types)
        self.assertIn('OS_Coil_Cooling_Water', types)


@needs_sdk
class TestVentilationOnlyDoas(unittest.TestCase):

    def test_the_untempered_loop_has_a_fan_and_outdoor_air_and_no_coil(self):
        model = _build('doas-untempered')
        (loop,) = model.getAirLoopHVACs()
        types = _supply_types(loop)
        self.assertEqual(['OS_AirLoopHVAC_OutdoorAirSystem', 'OS_Fan_ConstantVolume'],
                         sorted(types))
        self.assertEqual(0, len(model.getSetpointManagerScheduleds()),
                         'a loop with no coil has nothing for a setpoint to control')

    def test_the_tempered_doas_keeps_its_coils(self):
        model = _build('doas-elec')
        types = _supply_types(model.getAirLoopHVACs()[0])
        self.assertIn('OS_Coil_Heating_Electric', types)
        self.assertIn('OS_Coil_Cooling_DX_SingleSpeed', types)


@needs_sdk
class TestFullOutdoorAirInOperation(unittest.TestCase):

    def _fraction_is_one(self, loop):
        controller = loop.airLoopHVACOutdoorAirSystem().get().getControllerOutdoorAir()
        for schedule in (controller.minimumFractionofOutdoorAirSchedule(),
                         controller.maximumFractionofOutdoorAirSchedule()):
            if not schedule.is_initialized():
                return False
            constant = schedule.get().to_ScheduleConstant()
            if not constant.is_initialized() or constant.get().value() != 1.0:
                return False
        return True

    def test_the_100oa_rows_fix_the_outdoor_air_fraction_at_one(self):
        for system in ('psz-gas-100oa-perzone', 'hv-hw-100oa-gasboiler-shared'):
            with self.subTest(system=system):
                model = _build(system)
                loops = model.getAirLoopHVACs()
                self.assertTrue(loops)
                for loop in loops:
                    self.assertTrue(self._fraction_is_one(loop), loop.nameString())
                    self.assertTrue(loop.sizingSystem().allOutdoorAirinCooling())
                    self.assertTrue(loop.sizingSystem().allOutdoorAirinHeating())

    def test_their_mixed_air_twins_do_not(self):
        for system in ('psz-gas-perzone', 'hv-hw-gasboiler-shared'):
            with self.subTest(system=system):
                model = _build(system)
                for loop in model.getAirLoopHVACs():
                    self.assertFalse(self._fraction_is_one(loop), loop.nameString())

    def test_classify_reads_the_fraction_not_the_sizing(self):
        def facts(system):
            model = _build(system)
            return [g['loop_full_outdoor_air']
                    for g in modeling.characterize(model, audit=None)['zone_groups']]
        self.assertEqual({True}, set(facts('psz-gas-100oa-perzone')))
        self.assertEqual({False}, set(facts('psz-gas-perzone')))
        # sized as 100% outdoor air but not run on it: the fact stays False
        self.assertEqual({False}, set(facts('doas-elec')))

    def test_no_outdoor_air_and_full_outdoor_air_is_refused_before_the_teardown(self):
        model = _build('bb-elecbb')
        before = len(model.getZoneHVACBaseboardConvectiveElectrics())
        with self.assertRaises(ValueError):
            modeling.build_system(model, 'hv-elec', _zones(model),
                                  config={'all_outdoor_air': True, 'ventilation': False})
        self.assertEqual(before, len(model.getZoneHVACBaseboardConvectiveElectrics()))


@needs_sdk
class TestConfigOnlyRows(unittest.TestCase):
    """Rows 1, 2 and 4 are configurations of existing families."""

    def test_stand_alone_hot_water_ptacs_on_a_boiler_and_no_air_loop(self):
        model = _build('ptac-hwptac-gasboiler')
        self.assertEqual(0, len(model.getAirLoopHVACs()))
        ptacs = model.getZoneHVACPackagedTerminalAirConditioners()
        self.assertEqual(len(_zones(model)), len(ptacs))
        for ptac in ptacs:
            self.assertTrue(ptac.heatingCoil().to_CoilHeatingWater().is_initialized())
        self.assertEqual(1, len(model.getPlantLoops()))
        self.assertTrue(model.getBoilerHotWaters())
        self.assertTrue(all(b.fuelType() == 'NaturalGas' for b in model.getBoilerHotWaters()))

    def test_a_per_zone_heat_pump_with_no_baseboards(self):
        model = _build('psz-ashp-elecsupp-perzone')
        self.assertEqual(len(_zones(model)), len(model.getAirLoopHVACs()))
        self.assertEqual(0, len(model.getZoneHVACBaseboardConvectiveElectrics()))
        for loop in model.getAirLoopHVACs():
            types = _supply_types(loop)
            self.assertIn('OS_Coil_Heating_DX_SingleSpeed', types)
            self.assertIn('OS_Coil_Heating_Electric', types)

    def test_an_electric_heating_and_ventilating_unit_per_zone(self):
        model = _build('hv-elec')
        self.assertEqual(len(_zones(model)), len(model.getAirLoopHVACs()))
        for loop in model.getAirLoopHVACs():
            types = _supply_types(loop)
            self.assertIn('OS_Coil_Heating_Electric', types)
            self.assertFalse([t for t in types if 'Cooling' in t])


if __name__ == '__main__':
    unittest.main()
