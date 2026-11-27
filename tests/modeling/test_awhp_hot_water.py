"""An air-to-water heat-pump hot-water plant for ANY hydronic system.

phylroy (2026-11-26): hydronic systems could only take a boiler or district
plant; the heat-pump plant existed only inside the ECM fan-coil family. The
shared plant now takes ``hw_source: 'awhp'`` with a gas or electric backup
boiler (``boiler_fuel``) and ``hw_supply``: ``low_temperature`` (default,
60 C loop, boiler backs up to the same setpoint) or ``boiler_lift`` (82 C
loop, heat pump preheats to its 60 C limit, boiler lifts).
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk


def _loops_with_heat_pump(model):
    import openstudio
    hp_type = openstudio.model.HeatPumpPlantLoopEIRHeating.iddObjectType()
    return [pl for pl in model.getPlantLoops() if pl.supplyComponents(hp_type)]


@needs_sdk
class TestTheHeatPumpPlant(unittest.TestCase):

    def build(self, system, config, zones=None, model=None):
        from btap import modeling
        from btap._compat import sorted_by_name
        from tests.support import load_fixture
        model = model or load_fixture()
        all_zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, system, zones or all_zones, config=config)
        return model

    def test_low_temperature_is_the_default(self):
        model = self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp'})
        loops = _loops_with_heat_pump(model)
        self.assertEqual(1, len(loops))
        loop = loops[0]
        self.assertEqual(60.0, loop.sizingPlant().designLoopExitTemperature())
        boilers = model.getBoilerHotWaters()
        self.assertEqual(['NaturalGas'], [b.fuelType() for b in boilers],
                         'one backup boiler, gas by default')
        self.assertEqual(1, len(model.getHeatPumpPlantLoopEIRHeatings()))
        hp = model.getHeatPumpPlantLoopEIRHeatings()[0]
        self.assertEqual('AirSource', hp.condenserType())
        self.assertEqual('HeatingCapacity', hp.heatPumpSizingMethod())
        # the boiler sits DOWNSTREAM of the heat pump on one branch: in series
        hp_out = hp.supplyOutletModelObject().get()
        self.assertEqual(boilers[0].handle(), hp_out.to_Node().get().outletModelObject().get().handle())
        # The backup boiler is SETPOINT-controlled on its own outlet. Load-
        # dispatched in series, it was handed almost nothing and the loop ran
        # 4-12 K under setpoint, tripling unmet heating hours (measured,
        # 2026-11-27: 153.5 h against the boiler-only control's 56.5; 56.75
        # once controlled).
        self.assertEqual('LeavingSetpointModulated', boilers[0].boilerFlowMode())
        boiler_out = boilers[0].outletModelObject().get().to_Node().get()
        self.assertEqual(1, len(boiler_out.setpointManagers()))
        # ...with a 1 K deadband below the heat pump, so it does not chase the
        # fraction of a kelvin the heat pump runs short while defrosting
        # (Fable, PR #243: with equal setpoints 67% of boiler heat came while
        # the heat pump had capacity).
        boiler_spm = boiler_out.setpointManagers()[0].to_SetpointManagerOutdoorAirReset().get()
        hp_spm = hp_out.to_Node().get().setpointManagers()[0].to_SetpointManagerOutdoorAirReset().get()
        for getter in ('setpointatOutdoorLowTemperature', 'setpointatOutdoorHighTemperature'):
            self.assertAlmostEqual(getattr(hp_spm, getter)() - 1.0, getattr(boiler_spm, getter)())
        # every baseboard hangs on the heat-pump loop, none on a boiler loop
        for bb in model.getZoneHVACBaseboardConvectiveWaters():
            coil = bb.heatingCoil().to_CoilHeatingWaterBaseboard().get()
            self.assertEqual(loop.handle(), coil.plantLoop().get().handle())

    def test_electric_backup(self):
        model = self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp', 'boiler_fuel': 'Electricity'})
        self.assertEqual(['Electricity'], [b.fuelType() for b in model.getBoilerHotWaters()])

    def test_boiler_lift_keeps_the_conventional_loop(self):
        model = self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp', 'hw_supply': 'boiler_lift'})
        loop = _loops_with_heat_pump(model)[0]
        self.assertEqual(82.0, loop.sizingPlant().designLoopExitTemperature())
        hp = model.getHeatPumpPlantLoopEIRHeatings()[0]
        spms = hp.supplyOutletModelObject().get().to_Node().get().setpointManagers()
        self.assertEqual(['OS_SetpointManager_Scheduled'],
                         [s.iddObjectType().valueName() for s in spms],
                         'the heat pump is held at its 60 C limit')

    def test_two_heat_pump_systems_share_one_plant_and_a_boiler_system_never_adopts_it(self):
        from btap._compat import sorted_by_name
        from tests.support import load_fixture
        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp'}, zones[:2], model)
        self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp'}, zones[2:4], model)
        self.assertEqual(1, len(_loops_with_heat_pump(model)), 'same source and supply: shared')
        self.build('bb-hwbb-gasboiler', None, zones[4:], model)
        self.assertEqual(1, len(_loops_with_heat_pump(model)))
        plain = [pl for pl in model.getPlantLoops() if pl not in _loops_with_heat_pump(model)]
        self.assertEqual(1, len(plain), 'the ordinary boiler system built its own boiler plant')
        self.assertEqual(2, len(plain[0].supplyComponents(
            __import__('openstudio').model.BoilerHotWater.iddObjectType())))

    def test_different_supply_or_backup_never_share(self):
        from btap._compat import sorted_by_name
        from tests.support import load_fixture
        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp'}, zones[:1], model)
        self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp', 'hw_supply': 'boiler_lift'}, zones[1:2], model)
        self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp', 'boiler_fuel': 'Electricity'}, zones[2:3], model)
        self.assertEqual(3, len(_loops_with_heat_pump(model)))

    def test_bad_options_are_refused(self):
        from btap.modeling.hvac.systems import plant_loops
        for bad in ({'hw_source': 'awhp', 'hw_supply': 'tepid'},
                    {'hw_source': 'boiler', 'hw_supply': 'boiler_lift'},
                    {'hw_source': 'awhp', 'boiler_fuel': 'FuelOilNo2'}):
            with self.subTest(config=bad):
                with self.assertRaises(ValueError):
                    plant_loops.validate_plant_config(bad)

    def test_a_bad_combination_is_refused_BEFORE_the_old_system_is_torn_down(self):
        from btap import modeling
        model = self.build('bb-hwbb-gasboiler', None)
        before = len(model.getZoneHVACBaseboardConvectiveWaters())
        zones = list(model.getThermalZones())
        profile = {'name': 'low', 'design_exit_temperature': 60.0, 'design_temperature_difference': 10.0,
                   'setpoint_temperature': 60.0}
        with self.assertRaises(ValueError):
            modeling.build_system(model, 'bb-hwbb-gasboiler', zones, remove_existing=True,
                                  config={'hw_source': 'awhp', 'hot_water_profile': profile})
        self.assertEqual(before, len(model.getZoneHVACBaseboardConvectiveWaters()),
                         'the existing system must survive a refused rebuild')

    def test_a_composite_passes_the_option_to_its_hot_water_part(self):
        model = self.build('doas-fc4-elec-gasboiler-scrollchiller', {'hw_source': 'awhp'})
        self.assertEqual(1, len(_loops_with_heat_pump(model)))
        self.assertEqual(1, len(model.getBoilerHotWaters()), 'the one backup boiler')

    def test_a_bad_value_on_a_composite_is_refused(self):
        with self.assertRaises(ValueError):
            self.build('doas-fc4-elec-gasboiler-scrollchiller',
                       {'hw_source': 'awhp', 'hw_supply': 'tepid'})

    def test_a_row_with_no_hot_water_plant_refuses_the_option(self):
        for system in ('psz-gas-elecbb', 'wshp-gasboiler', 'doas-fc4-hw-chw-awhp-elecboiler'):
            with self.subTest(system=system):
                with self.assertRaises(ValueError):
                    self.build(system, {'hw_source': 'awhp'})

    def test_any_hydronic_family_takes_it(self):
        for system in ('vav-hw-hwbb-gasboiler-scrollchiller', 'mau-fc4-gas-chw-gasboiler-scrollchiller',
                       'uh-hw-gasboiler', 'psz-hw-hwbb-gasboiler'):
            with self.subTest(system=system):
                model = self.build(system, {'hw_source': 'awhp'})
                self.assertEqual(1, len(_loops_with_heat_pump(model)))
                for coil in model.getCoilHeatingWaters():
                    self.assertTrue(coil.plantLoop().is_initialized())
                    self.assertIn(coil.plantLoop().get().handle(),
                                  [pl.handle() for pl in _loops_with_heat_pump(model)])


def _reset(node):
    """(cold setpoint, mild setpoint, cold outdoor, mild outdoor) of a node's
    outdoor-air reset, or ('constant', value) of a scheduled setpoint."""
    spm = node.setpointManagers()[0]
    oa = spm.to_SetpointManagerOutdoorAirReset()
    if oa.is_initialized():
        oa = oa.get()
        return (oa.setpointatOutdoorLowTemperature(), oa.setpointatOutdoorHighTemperature(),
                oa.outdoorLowTemperature(), oa.outdoorHighTemperature())
    schedule = spm.to_SetpointManagerScheduled().get().schedule().to_ScheduleConstant().get()
    return ('constant', schedule.value())


def _plant_resets(model, loop):
    hp = model.getHeatPumpPlantLoopEIRHeatings()[0]
    boiler = model.getBoilerHotWaters()[0]
    return {'heat pump': _reset(hp.supplyOutletModelObject().get().to_Node().get()),
            'boiler': _reset(boiler.outletModelObject().get().to_Node().get()),
            'loop': _reset(loop.supplyOutletNode()),
            'design exit': loop.sizingPlant().designLoopExitTemperature()}


class TestTheControlsResolve(unittest.TestCase):
    """#244 Stream C: the reset, the heat pump's ceiling and the backup
    deadband are authored defaults a caller may override (`hw_controls`)."""

    def test_the_defaults_are_the_plant_as_first_built(self):
        from btap.modeling.hvac.systems.plant_loops import heat_pump_controls
        self.assertEqual({'outdoor_reset_c': (-16.0, 0.0), 'loop_reset_c': (60.0, 45.0),
                          'heat_pump_max_c': 60.0, 'backup_deadband_k': 1.0},
                         heat_pump_controls('low_temperature'))
        self.assertEqual((82.0, 60.0), heat_pump_controls('boiler_lift')['loop_reset_c'])

    def test_bad_controls_are_refused(self):
        from btap.modeling.hvac.systems.plant_loops import heat_pump_controls
        for supply, bad in (
                ('low_temperature', {'sizing_factor': 0.5}),            # unknown key
                ('low_temperature', {'backup_deadband_k': True}),       # a bool is not a number
                ('low_temperature', {'backup_deadband_k': float('nan')}),
                ('low_temperature', {'backup_deadband_k': 9.0}),
                ('low_temperature', {'loop_reset_c': [60.0]}),          # not a pair
                ('low_temperature', {'loop_reset_c': [45.0, 60.0]}),    # hotter when mild
                ('low_temperature', {'outdoor_reset_c': [0.0, -16.0]}),
                ('low_temperature', {'loop_reset_c': [70.0, 50.0]}),    # beyond the heat pump: that is boiler lift
                ('boiler_lift', {'loop_reset_c': [58.0, 45.0]}),        # within reach: that is low temperature
                ('low_temperature', {'loop_reset_c': [60.0, 10.0]}),
                ('low_temperature', {'heat_pump_max_c': 120.0}),
                ('low_temperature', [1, 2])):
            with self.subTest(supply=supply, controls=bad):
                with self.assertRaises(ValueError):
                    heat_pump_controls(supply, bad)

    def test_validate_plant_config_checks_them_and_their_source(self):
        from btap.modeling.hvac.systems import plant_loops
        for bad in ({'hw_source': 'boiler', 'hw_controls': {}},
                    {'hw_source': 'awhp', 'hw_controls': {'backup_deadband_k': -1}},
                    {'hw_source': 'awhp', 'hw_supply': 'boiler_lift',
                     'hw_controls': {'loop_reset_c': [55.0, 45.0]}}):
            with self.subTest(config=bad):
                with self.assertRaises(ValueError):
                    plant_loops.validate_plant_config(bad)
        plant_loops.validate_plant_config({'hw_source': 'awhp', 'hw_controls': {'backup_deadband_k': 2}})


@needs_sdk
class TestTheControlsAreBuilt(unittest.TestCase):

    build = TestTheHeatPumpPlant.build

    def test_the_default_controls_build_the_plant_as_first_built(self):
        model = self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp'})
        self.assertEqual({'heat pump': (60.0, 45.0, -16.0, 0.0), 'boiler': (59.0, 44.0, -16.0, 0.0),
                          'loop': (60.0, 45.0, -16.0, 0.0), 'design exit': 60.0},
                         _plant_resets(model, _loops_with_heat_pump(model)[0]))
        model = self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp', 'hw_supply': 'boiler_lift'})
        self.assertEqual({'heat pump': ('constant', 60.0), 'boiler': (82.0, 59.0, -16.0, 0.0),
                          'loop': (82.0, 60.0, -16.0, 0.0), 'design exit': 82.0},
                         _plant_resets(model, _loops_with_heat_pump(model)[0]))

    def test_low_temperature_controls(self):
        model = self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp', 'hw_controls': {
            'loop_reset_c': [55, 40], 'outdoor_reset_c': [-20, 5], 'backup_deadband_k': 2}})
        self.assertEqual({'heat pump': (55.0, 40.0, -20.0, 5.0), 'boiler': (53.0, 38.0, -20.0, 5.0),
                          'loop': (55.0, 40.0, -20.0, 5.0), 'design exit': 55.0},
                         _plant_resets(model, _loops_with_heat_pump(model)[0]))

    def test_boiler_lift_controls(self):
        # The boiler holds the deadband below the loop only where the heat
        # pump can reach the loop setpoint: at the cold end only the boiler
        # reaches 80 C, so it holds the loop setpoint there.
        model = self.build('bb-hwbb-gasboiler', {
            'hw_source': 'awhp', 'hw_supply': 'boiler_lift',
            'hw_controls': {'heat_pump_max_c': 55, 'loop_reset_c': [80, 55], 'backup_deadband_k': 0.5}})
        self.assertEqual({'heat pump': ('constant', 55.0), 'boiler': (80.0, 54.5, -16.0, 0.0),
                          'loop': (80.0, 55.0, -16.0, 0.0), 'design exit': 80.0},
                         _plant_resets(model, _loops_with_heat_pump(model)[0]))

    def test_plants_share_only_when_their_controls_match(self):
        from btap._compat import sorted_by_name
        from tests.support import load_fixture
        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp'}, zones[:1], model)
        # restating the defaults is the same plant
        self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp', 'hw_controls': {'backup_deadband_k': 1.0}},
                   zones[1:2], model)
        self.assertEqual(1, len(_loops_with_heat_pump(model)))
        self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp', 'hw_controls': {'backup_deadband_k': 2.0}},
                   zones[2:3], model)
        self.assertEqual(2, len(_loops_with_heat_pump(model)), 'different controls: its own plant')
        self.build('bb-hwbb-gasboiler', {'hw_source': 'awhp', 'hw_controls': {'backup_deadband_k': 2}},
                   zones[3:4], model)
        self.assertEqual(2, len(_loops_with_heat_pump(model)), 'the same controls again: shared')

    def test_refused_BEFORE_the_old_system_is_torn_down(self):
        from btap import modeling
        model = self.build('bb-hwbb-gasboiler', None)
        before = len(model.getZoneHVACBaseboardConvectiveWaters())
        zones = list(model.getThermalZones())
        for config in ({'hw_source': 'awhp', 'hw_controls': {'loop_reset_c': [70, 50]}},
                       {'hw_controls': {'backup_deadband_k': 2}}):
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    modeling.build_system(model, 'bb-hwbb-gasboiler', zones,
                                          remove_existing=True, config=config)
                self.assertEqual(before, len(model.getZoneHVACBaseboardConvectiveWaters()))

    def test_a_row_with_no_hot_water_plant_refuses_them(self):
        with self.assertRaises(ValueError):
            self.build('psz-gas-elecbb', {'hw_controls': {'backup_deadband_k': 2}})

    def test_a_composite_routes_them_to_its_hot_water_part(self):
        model = self.build('doas-fc4-elec-gasboiler-scrollchiller',
                           {'hw_source': 'awhp', 'hw_controls': {'backup_deadband_k': 2}})
        resets = _plant_resets(model, _loops_with_heat_pump(model)[0])
        self.assertEqual((58.0, 43.0, -16.0, 0.0), resets['boiler'])


if __name__ == "__main__":
    unittest.main()
