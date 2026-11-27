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


if __name__ == "__main__":
    unittest.main()
