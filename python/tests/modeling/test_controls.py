"""Economizer and thermostat primitives (#192, cluster 2).

`btap.modeling` had no economizer primitive — only a hardcoded
`setEconomizerControlType('NoEconomizer')` in the DOAS builder — and NO
setpoint setter at all.
"""

from __future__ import annotations

import unittest

from btap._compat import opt
from btap.audit import AuditLog
from btap.modeling import lighting as Lighting
from btap.modeling.hvac import thermostats as Thermostats
from btap.modeling.hvac import ventilation as Ventilation
from tests.support import needs_sdk


def _loop_with_oa():
    import openstudio

    model = openstudio.model.Model()
    air_loop = openstudio.model.AirLoopHVAC(model)
    air_loop.setName('Probe Air Loop')
    controller = openstudio.model.ControllerOutdoorAir(model)
    oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(model, controller)
    oa_system.addToNode(air_loop.supplyInletNode())
    return model, air_loop, controller


@needs_sdk
class TestEconomizer(unittest.TestCase):

    def test_each_IDD_control_type_is_accepted(self):
        for control_type in Ventilation.ECONOMIZER_CONTROL_TYPES:
            with self.subTest(control_type):
                _model, _loop, controller = _loop_with_oa()
                Ventilation.set_economizer(controller,
                                           control_type=control_type)
                self.assertEqual(control_type,
                                 controller.getEconomizerControlType())

    def test_a_MISTYPED_control_type_is_refused_not_silently_dropped(self):
        """The SDK returns False for an unknown key, so a caller who wrote
        `DifferentialDrybulb` would otherwise get a silent NoEconomizer."""
        _model, _loop, controller = _loop_with_oa()
        with self.assertRaises(ValueError) as caught:
            Ventilation.set_economizer(controller,
                                       control_type='DifferentialDrybulb')
        self.assertIn('not an EnergyPlus economizer control type',
                      str(caught.exception))
        self.assertIn('DifferentialDryBulb', str(caught.exception),
                      'and the message names the spelling that works')

    def test_the_limits_land(self):
        _model, _loop, controller = _loop_with_oa()
        Ventilation.set_economizer(
            controller, control_type='FixedDryBulb',
            maximum_limit_drybulb_c=24.0, minimum_limit_drybulb_c=-30.0,
            action_type='MinimumFlowWithBypass')
        self.assertAlmostEqual(
            24.0, opt(controller.getEconomizerMaximumLimitDryBulbTemperature()))
        self.assertAlmostEqual(
            -30.0,
            opt(controller.getEconomizerMinimumLimitDryBulbTemperature()))
        self.assertEqual('MinimumFlowWithBypass',
                         controller.getEconomizerControlActionType())

    def test_a_bad_ACTION_type_is_refused(self):
        _model, _loop, controller = _loop_with_oa()
        with self.assertRaises(ValueError) as caught:
            Ventilation.set_economizer(controller,
                                       control_type='FixedDryBulb',
                                       action_type='Modulate')
        self.assertIn('ACTION type', str(caught.exception))

    def test_disabling_is_AUDITED_as_a_choice(self):
        """NoEconomizer is the IDD default, so omitting it and disabling it
        are the same state but not the same act: one is an assertion that the
        building has none, and it has to reach the trail."""
        _model, _loop, controller = _loop_with_oa()
        audit = AuditLog()
        Ventilation.set_economizer(controller, control_type='NoEconomizer',
                                   audit=audit)
        said = [e for e in audit.entries
                if 'DISABLED' in str(e.get('value') or e.get('action') or '')]
        self.assertEqual(1, len(said))

    def test_a_loop_with_no_outdoor_air_has_no_controller(self):
        import openstudio

        model = openstudio.model.Model()
        air_loop = openstudio.model.AirLoopHVAC(model)
        self.assertIsNone(Ventilation.economizer_controller(air_loop))

    def test_model_wide_skips_loops_without_one(self):
        import openstudio

        model, _loop, controller = _loop_with_oa()
        bare = openstudio.model.AirLoopHVAC(model)
        bare.setName('Recirculating Loop')
        self.assertEqual(
            1, Ventilation.set_economizer_in_model(
                model, control_type='DifferentialDryBulb'))
        self.assertEqual('DifferentialDryBulb',
                         controller.getEconomizerControlType())


@needs_sdk
class TestSetbackSchedule(unittest.TestCase):

    @staticmethod
    def _steps(schedule):
        """Read a day schedule as (hour, value) pairs.

        `totalHours()`, NOT `hours()`: measured on 3.11, a `Time(0, 24, 0, 0)`
        reads back as `hours() == 0` because 24:00 rolls into the next day,
        while `totalHours()` gives 24.0. The first version of these tests used
        `hours()` and failed against correct schedules.
        """
        day = schedule.defaultDaySchedule()
        return [(t.totalHours(), v)
                for t, v in zip(day.times(), day.values())]

    def test_the_steps_bracket_the_occupied_period(self):
        import openstudio

        model = openstudio.model.Model()
        schedule = Thermostats.setback_schedule(
            model, 'Heating Setback', occupied_c=21.0, setback_c=16.0,
            occupied_from_hour=7, occupied_to_hour=18)
        self.assertEqual(
            [(7.0, 16.0), (18.0, 21.0), (24.0, 16.0)], self._steps(schedule),
            'a value is "until this time", so the setback leads and trails '
            'the occupied block')

    def test_a_period_touching_either_END_of_the_day(self):
        """Only the steps that can apply are emitted — no leading setback when
        occupancy starts at midnight, no trailing one when it runs to 24."""
        import openstudio

        model = openstudio.model.Model()
        for label, start, end, expected in (
                ('from midnight', 0, 18, [(18.0, 21.0), (24.0, 16.0)]),
                ('to midnight', 7, 24, [(7.0, 16.0), (24.0, 21.0)])):
            with self.subTest(label):
                schedule = Thermostats.setback_schedule(
                    model, f'Setback {label}', occupied_c=21.0,
                    setback_c=16.0, occupied_from_hour=start,
                    occupied_to_hour=end)
                self.assertEqual(expected, self._steps(schedule))

    def test_a_full_day_occupied_is_a_CONSTANT_not_a_two_step(self):
        """There are no unoccupied hours, so emitting a second step whose
        value never applies would be a schedule that lies about itself."""
        import openstudio

        model = openstudio.model.Model()
        schedule = Thermostats.setback_schedule(
            model, 'Always 21', occupied_c=21.0, setback_c=16.0,
            occupied_from_hour=0, occupied_to_hour=24)
        self.assertEqual([(24.0, 21.0)], self._steps(schedule))

    def test_it_is_REUSED_by_name(self):
        """One setback applied to forty zones must produce one schedule."""
        import openstudio

        model = openstudio.model.Model()
        first = Thermostats.setback_schedule(
            model, 'Shared Setback', occupied_c=21.0, setback_c=16.0,
            occupied_from_hour=7, occupied_to_hour=18)
        second = Thermostats.setback_schedule(
            model, 'Shared Setback', occupied_c=21.0, setback_c=16.0,
            occupied_from_hour=7, occupied_to_hour=18)
        self.assertEqual(first.handle(), second.handle())
        self.assertEqual(1, len(model.getScheduleRulesets()))

    def test_a_backwards_period_is_refused(self):
        import openstudio

        model = openstudio.model.Model()
        for bad in ((18, 7), (0, 0), (7, 25), (-1, 8)):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    Thermostats.setback_schedule(
                        model, f'Bad {bad}', occupied_c=21.0, setback_c=16.0,
                        occupied_from_hour=bad[0], occupied_to_hour=bad[1])


@needs_sdk
class TestZoneThermostat(unittest.TestCase):

    @staticmethod
    def _zone(name='Probe Zone'):
        import openstudio

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        zone.setName(name)
        return model, zone

    def test_it_CREATES_the_thermostat_when_the_zone_has_none(self):
        """CLAUDE.md: a model with no thermostat anywhere is a fatal preflight
        gate precisely because it RUNS and produces a numerically valid,
        physically meaningless answer. A stock generator must be able to give
        its zones setpoints."""
        _model, zone = self._zone()
        self.assertIsNone(opt(zone.thermostatSetpointDualSetpoint()))
        thermostat = Thermostats.set_zone_thermostat(zone, heating=21.0,
                                                     cooling=24.0)
        self.assertIsNotNone(thermostat)
        self.assertEqual(
            thermostat.handle(),
            opt(zone.thermostatSetpointDualSetpoint()).handle())

    def test_a_SCALAR_becomes_a_constant_schedule(self):
        _model, zone = self._zone()
        thermostat = Thermostats.set_zone_thermostat(zone, heating=21.0)
        schedule = opt(thermostat.heatingSetpointTemperatureSchedule())
        self.assertIsNotNone(schedule)
        day = opt(schedule.to_ScheduleRuleset()).defaultDaySchedule()
        self.assertEqual([21.0], list(day.values()))

    def test_a_SCHEDULE_is_used_as_given(self):
        """The flexibility phylroy asked for on the load primitives — a value
        or the thing itself — applied to setpoints."""

        model, zone = self._zone()
        given = Thermostats.setback_schedule(
            model, 'Night Setback', occupied_c=21.0, setback_c=16.0,
            occupied_from_hour=7, occupied_to_hour=18)
        thermostat = Thermostats.set_zone_thermostat(zone, heating=given)
        self.assertEqual(
            given.handle(),
            opt(thermostat.heatingSetpointTemperatureSchedule()).handle())

    def test_an_EXISTING_thermostat_is_reused(self):

        model, zone = self._zone()
        first = Thermostats.set_zone_thermostat(zone, heating=21.0)
        second = Thermostats.set_zone_thermostat(zone, cooling=24.0)
        self.assertEqual(first.handle(), second.handle())
        self.assertEqual(1, len(model.getThermostatSetpointDualSetpoints()))
        self.assertIsNotNone(
            opt(second.heatingSetpointTemperatureSchedule()),
            'and the heating setpoint set by the first call survives')

    def test_neither_setpoint_is_a_no_op(self):
        model, zone = self._zone()
        self.assertIsNone(Thermostats.set_zone_thermostat(zone))
        self.assertEqual(0, len(model.getThermostatSetpointDualSetpoints()),
                         'and no thermostat is created')

    def test_model_wide(self):
        import openstudio

        model = openstudio.model.Model()
        zones = []
        for n in range(3):
            zone = openstudio.model.ThermalZone(model)
            zone.setName(f'Zone {n}')
            zones.append(zone)
        self.assertEqual(3, Thermostats.set_thermostats_in_model(
            model, heating=21.0, cooling=24.0))
        for zone in zones:
            self.assertIsNotNone(opt(zone.thermostatSetpointDualSetpoint()))

    def test_model_wide_with_nothing_given_is_a_no_op(self):
        import openstudio

        model = openstudio.model.Model()
        openstudio.model.ThermalZone(model)
        self.assertEqual(0, Thermostats.set_thermostats_in_model(model))


@needs_sdk
class TestDaylightingControl(unittest.TestCase):
    """`btap.modeling` had zero hits for DaylightingControl."""

    @staticmethod
    def _space_in_zone(zoned=True):
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        space.setName('Perimeter Space')
        if zoned:
            zone = openstudio.model.ThermalZone(model)
            zone.setName('Perimeter Zone')
            space.setThermalZone(zone)
            return model, space, zone
        return model, space, None

    def test_it_wires_BOTH_halves(self):
        """A control with no zone pointer changes nothing in the simulation,
        which is the quiet failure worth preventing: the control is a
        SpaceItem, but the fraction of the zone it governs lives on the
        ThermalZone."""
        _model, space, zone = self._space_in_zone()
        control = Lighting.add_daylighting_control(
            space, illuminance_setpoint_lux=500.0, position=(2.0, 3.0, 0.8),
            fraction_of_zone=0.6)

        self.assertEqual(space.handle(), opt(control.space()).handle())
        self.assertEqual(
            control.handle(),
            opt(zone.primaryDaylightingControl()).handle(),
            'the zone must point back at it')
        # A plain double, NOT an optional — the header says
        # `double fractionofZoneControlledbyPrimaryDaylightingControl() const`,
        # so wrapping it in opt() raises. D-79's guard is for optionals only.
        self.assertAlmostEqual(
            0.6, zone.fractionofZoneControlledbyPrimaryDaylightingControl())
        self.assertAlmostEqual(500.0, control.illuminanceSetpoint())
        self.assertAlmostEqual(2.0, control.positionXCoordinate())
        self.assertAlmostEqual(0.8, control.positionZCoordinate())

    def test_a_space_in_NO_zone_is_refused(self):
        _model, space, _zone = self._space_in_zone(zoned=False)
        with self.assertRaises(ValueError) as caught:
            Lighting.add_daylighting_control(
                space, illuminance_setpoint_lux=500.0, position=(0, 0, 0.8))
        self.assertIn('no thermal zone', str(caught.exception))

    def test_each_IDD_control_type(self):
        for control_type in Lighting.lighting_control_types():
            with self.subTest(control_type):
                _model, space, _zone = self._space_in_zone()
                control = Lighting.add_daylighting_control(
                    space, illuminance_setpoint_lux=400.0,
                    position=(1.0, 1.0, 0.8), control_type=control_type,
                    steps=3 if control_type == 'Stepped' else None)
                self.assertEqual(control_type,
                                 control.lightingControlType())

    def test_a_mistyped_control_type_is_refused(self):
        _model, space, _zone = self._space_in_zone()
        with self.assertRaises(ValueError) as caught:
            Lighting.add_daylighting_control(
                space, illuminance_setpoint_lux=400.0, position=(0, 0, 0.8),
                control_type='ContinuousOff')
        message = str(caught.exception)
        self.assertIn('Continuous/Off', message,
                      'the E+ IDD spelling is REFUSED by OpenStudio, and the '
                      'message has to name the slash form that works')

    def test_steps_on_a_NON_stepped_control_is_refused(self):
        """EnergyPlus would ignore it, so passing it is a mistake worth
        surfacing rather than dropping."""
        _model, space, _zone = self._space_in_zone()
        with self.assertRaises(ValueError) as caught:
            Lighting.add_daylighting_control(
                space, illuminance_setpoint_lux=400.0, position=(0, 0, 0.8),
                control_type='Continuous', steps=3)
        self.assertIn('only meaningful for Stepped', str(caught.exception))

    def test_an_out_of_range_fraction_is_refused(self):
        _model, space, _zone = self._space_in_zone()
        for bad in (-0.1, 1.5):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    Lighting.add_daylighting_control(
                        space, illuminance_setpoint_lux=400.0,
                        position=(0, 0, 0.8), fraction_of_zone=bad)

    def test_the_position_is_REQUIRED(self):
        """A sensor's reading is a function of where it sits, so a guessed
        position produces a number that looks measured and is invented."""
        _model, space, _zone = self._space_in_zone()
        with self.assertRaises(TypeError):
            Lighting.add_daylighting_control(space,
                                             illuminance_setpoint_lux=400.0)


if __name__ == '__main__':
    unittest.main()
