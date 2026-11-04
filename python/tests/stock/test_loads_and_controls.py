"""The recipe writer's loads and controls sections (#196)."""

from __future__ import annotations

import unittest

from btap.audit import AuditLog
from btap.modeling import loads as Loads
from btap.modeling.hvac import thermostats as Thermostats
from btap.modeling.hvac import ventilation as Ventilation
from btap.stock import controls_section, loads_section
from tests.support import needs_sdk


def _space_type_with_area(model, name='Probe', area=100.0):
    """A space type with one space, so area weighting has something to use."""
    import openstudio

    space_type = openstudio.model.SpaceType(model)
    space_type.setName(name)
    space = openstudio.model.Space(model)
    space.setName(f'{name} Space')
    space.setSpaceType(space_type)
    pts = openstudio.Point3dVector()
    side = area ** 0.5
    for x, y in ((0, 0), (side, 0), (side, side), (0, side)):
        pts.append(openstudio.Point3d(x, y, 0.0))
    floor = openstudio.model.Surface(pts, model)
    floor.setSpace(space)
    floor.setSurfaceType('Floor')
    return space_type


@needs_sdk
class TestLoadsSection(unittest.TestCase):

    def test_it_reads_the_densities_and_fractions_it_set(self):
        import openstudio

        model = openstudio.model.Model()
        space_type = _space_type_with_area(model)
        Loads.set_lighting(space_type, watts_per_area_si=11.0, radiant=0.3,
                           visible=0.2, return_air_fraction=0.1)
        Loads.set_electric_equipment(space_type, watts_per_area_si=7.5,
                                     radiant=0.4, latent=0.1, lost=0.05)
        Loads.set_infiltration(space_type, air_changes_per_hour=0.35)
        Loads.set_people(space_type, people_per_area_si=0.08)

        entry = loads_section(model)['by_space_type']['Probe']
        self.assertAlmostEqual(
            11.0, entry['lighting']['lighting_power_density_w_m2']['value'])
        self.assertAlmostEqual(
            0.3, entry['lighting']['lighting_fraction_radiant']['value'])
        self.assertEqual(['Watts/Area'],
                         entry['lighting']['lighting_calculation_method'])
        self.assertAlmostEqual(
            7.5, entry['plugs']['plug_power_density_w_m2']['value'])
        self.assertAlmostEqual(
            0.1, entry['plugs']['elec_equipment_fraction_latent']['value'])
        self.assertAlmostEqual(
            0.35,
            entry['infiltration']['infiltration_air_changes_per_hour']
            ['value'])
        self.assertEqual(
            ['AirChanges/Hour'],
            entry['infiltration']['infiltration_calculation_method'])
        self.assertAlmostEqual(
            0.08, entry['occupancy']['occupancy_people_per_m2']['value'])

    def test_it_reads_whichever_OCCUPANCY_method_is_set(self):
        """A first version read only `peopleperSpaceFloorArea` and reported
        nothing: on `Office_pre-1960` all fifteen definitions use
        `Area/Person`, so the density reader returns None for every one."""
        import openstudio

        for kwarg, value, field, method in (
                ('people_per_area_si', 0.08, 'occupancy_people_per_m2',
                 'People/Area'),
                ('area_per_person_si', 10.3, 'occupancy_m2_per_person',
                 'Area/Person'),
                ('number_of_people', 12.0, 'occupancy_number_of_people',
                 'People')):
            with self.subTest(method):
                model = openstudio.model.Model()
                space_type = _space_type_with_area(model)
                Loads.set_people(space_type, **{kwarg: value})
                occupancy = (loads_section(model)['by_space_type']['Probe']
                             ['occupancy'])
                self.assertAlmostEqual(value, occupancy[field]['value'])
                self.assertEqual([method],
                                 occupancy['occupancy_calculation_method'])

    def test_whichever_INFILTRATION_method_is_set(self):
        import openstudio

        for kwarg, value, field in (
                ('design_flow_rate_si', 0.05,
                 'infiltration_design_flow_rate_m3_per_s'),
                ('per_exterior_area_si', 0.0007,
                 'infiltration_flow_per_exterior_area_m3_per_s_m2'),
                ('air_changes_per_hour', 0.25,
                 'infiltration_air_changes_per_hour')):
            with self.subTest(kwarg):
                model = openstudio.model.Model()
                space_type = _space_type_with_area(model)
                Loads.set_infiltration(space_type, **{kwarg: value})
                entry = (loads_section(model)['by_space_type']['Probe']
                         ['infiltration'])
                self.assertAlmostEqual(value, entry[field]['value'])

    def test_a_SCALING_FACTOR_is_declared_unrecoverable(self):
        """osruby's fields are `lighting_scaling_factor` and
        `elec_equipment_scaling_factor` — ratios against a baseline the model
        does not carry. A recipe claiming 1.0 because it could not find the
        baseline would be inventing the baseline too."""
        import openstudio

        model = openstudio.model.Model()
        section = loads_section(model, audit=AuditLog())
        fields = {row['field'] for row in section['not_recoverable']}
        self.assertEqual(
            {'lighting_scaling_factor', 'elec_equipment_scaling_factor'},
            fields)

    def test_a_space_type_with_NO_loads_is_omitted(self):
        import openstudio

        model = openstudio.model.Model()
        _space_type_with_area(model, name='Empty')
        self.assertEqual({}, loads_section(model)['by_space_type'],
                         'a space type carrying nothing is not a load spec')

    def test_a_WIDE_spread_across_space_types_is_flagged(self):
        import openstudio

        model = openstudio.model.Model()
        space_type = _space_type_with_area(model)
        # Two lighting instances with different densities on one space type.
        Loads.set_lighting(space_type, watts_per_area_si=5.0,
                           name='Probe Lights A')
        second = openstudio.model.LightsDefinition(model)
        second.setName('Probe Lights B Definition')
        second.setWattsperSpaceFloorArea(25.0)
        lights = openstudio.model.Lights(second)
        lights.setName('Probe Lights B')
        lights.setSpaceType(space_type)

        entry = (loads_section(model)['by_space_type']['Probe']['lighting']
                 ['lighting_power_density_w_m2'])
        self.assertIn('spread_warning', entry['from'])
        self.assertAlmostEqual(5.0, entry['from']['min'])
        self.assertAlmostEqual(25.0, entry['from']['max'])


@needs_sdk
class TestControlsSection(unittest.TestCase):

    @staticmethod
    def _zone(model, name='Zone'):
        import openstudio

        zone = openstudio.model.ThermalZone(model)
        zone.setName(name)
        return zone

    def test_a_CONSTANT_setpoint_reports_no_setback(self):
        import openstudio

        model = openstudio.model.Model()
        zone = self._zone(model)
        Thermostats.set_zone_thermostat(zone, heating=21.0, cooling=24.0)

        thermostats = controls_section(model)['thermostats']
        self.assertEqual({'constant_c': 21.0, 'has_setback': False},
                         thermostats['heating_setpoint'])
        self.assertEqual({'constant_c': 24.0, 'has_setback': False},
                         thermostats['cooling_setpoint'])

    def test_a_SETBACK_profile_is_read_back_as_its_two_values(self):
        import openstudio

        model = openstudio.model.Model()
        zone = self._zone(model)
        schedule = Thermostats.setback_schedule(
            model, 'Heat Setback', occupied_c=21.0, setback_c=16.0,
            occupied_from_hour=7, occupied_to_hour=18)
        Thermostats.set_zone_thermostat(zone, heating=schedule)

        profile = controls_section(model)['thermostats']['heating_setpoint']
        self.assertTrue(profile['has_setback'])
        self.assertAlmostEqual(21.0, profile['occupied_c'])
        self.assertAlmostEqual(16.0, profile['setback_c'])
        self.assertAlmostEqual(18.0, profile['occupied_until_hour'],
                               msg='read through totalHours(), since 24:00 '
                                   'reads back as hours()==0')

    def test_DISTINCT_profiles_across_zones_are_flagged(self):
        import openstudio

        model = openstudio.model.Model()
        Thermostats.set_zone_thermostat(self._zone(model, 'A'), heating=21.0)
        Thermostats.set_zone_thermostat(self._zone(model, 'B'), heating=18.0)

        frm = controls_section(model)['thermostats']['heating_setpoint_from']
        self.assertEqual(2, frm['zones'])
        self.assertEqual(2, frm['distinct_profiles'])
        self.assertIn('spread_warning', frm)

    def test_an_unreadable_schedule_is_LISTED_not_approximated(self):
        """A setpoint profile the writer cannot see is not one it may guess."""
        import openstudio

        model = openstudio.model.Model()
        zone = self._zone(model)
        thermostat = openstudio.model.ThermostatSetpointDualSetpoint(model)
        constant = openstudio.model.ScheduleConstant(model)
        constant.setName('Opaque Constant Schedule')
        constant.setValue(21.0)
        thermostat.setHeatingSetpointTemperatureSchedule(constant)
        zone.setThermostatSetpointDualSetpoint(thermostat)

        thermostats = controls_section(model)['thermostats']
        self.assertIn('unreadable', thermostats)
        self.assertEqual('Opaque Constant Schedule',
                         thermostats['unreadable'][0]['schedule'])
        self.assertNotIn('heating_setpoint', thermostats,
                         'and nothing is reported for it')

    def test_the_economizer_and_DCV_state_is_read(self):
        import openstudio

        model = openstudio.model.Model()
        air_loop = openstudio.model.AirLoopHVAC(model)
        air_loop.setName('Loop A')
        controller = openstudio.model.ControllerOutdoorAir(model)
        oa = openstudio.model.AirLoopHVACOutdoorAirSystem(model, controller)
        oa.addToNode(air_loop.supplyInletNode())
        Ventilation.set_economizer(controller, control_type='FixedDryBulb',
                                   maximum_limit_drybulb_c=24.0)
        Ventilation.set_demand_controlled_ventilation(air_loop)

        economizers = controls_section(model)['economizers']
        row = economizers['by_air_loop'][0]
        self.assertEqual('FixedDryBulb', row['economizer_control_type'])
        self.assertAlmostEqual(
            24.0, row['economizer_maximum_limit_dry_bulb_temperature'])
        self.assertTrue(row['dcv_enabled'])
        self.assertTrue(economizers['from']['any_economizer'])
        self.assertTrue(economizers['from']['any_dcv'])

    def test_NoEconomizer_is_distinguished_from_not_having_looked(self):
        """'NoEconomizer' is the IDD default, so `any_economizer: False` is a
        measurement and an omitted key would not be."""
        import openstudio

        model = openstudio.model.Model()
        air_loop = openstudio.model.AirLoopHVAC(model)
        controller = openstudio.model.ControllerOutdoorAir(model)
        oa = openstudio.model.AirLoopHVACOutdoorAirSystem(model, controller)
        oa.addToNode(air_loop.supplyInletNode())
        Ventilation.set_economizer(controller, control_type='NoEconomizer')

        economizers = controls_section(model)['economizers']
        self.assertFalse(economizers['from']['any_economizer'])
        self.assertEqual(['NoEconomizer'],
                         economizers['from']['distinct_control_types'])

    def test_NO_daylighting_is_RECORDED_rather_than_omitted(self):
        """"This building has no daylighting control" is a vintage fact and a
        different claim from silence."""
        import openstudio

        model = openstudio.model.Model()
        daylighting = controls_section(model)['daylighting']
        self.assertEqual(0, daylighting['from']['count'])
        self.assertIn('no daylighting control', daylighting['from']['note'])

    def test_a_daylighting_control_is_read_with_its_position(self):
        import openstudio

        from btap.modeling import lighting as Lighting

        model = openstudio.model.Model()
        zone = self._zone(model, 'Perimeter')
        space = openstudio.model.Space(model)
        space.setName('Perimeter Space')
        space.setThermalZone(zone)
        Lighting.add_daylighting_control(
            space, illuminance_setpoint_lux=500.0, position=(2.0, 3.0, 0.8))

        row = controls_section(model)['daylighting']['controls'][0]
        self.assertEqual('Perimeter Space', row['space'])
        self.assertAlmostEqual(500.0, row['illuminance_setpoint_lux'])
        self.assertEqual([2.0, 3.0, 0.8], row['position'])
        self.assertEqual('Continuous', row['control_type'])


if __name__ == '__main__':
    unittest.main()
