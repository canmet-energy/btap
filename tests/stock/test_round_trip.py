"""The writer/reader round trip (#196).

The property that makes the writer trustworthy: build a model with KNOWN
values through the primitives, write a recipe from it, and check the recipe
reports those same values. Without this the writer is a plausible-looking
transformation with nothing to check it against.

This is the half that can be tested today. A full round trip — recipe back to
model, then compare — needs the recipe READER, which does not exist yet; what
is pinned here is that every value the primitives can SET is read back
correctly by the section that claims to read it, which is the completeness
criterion the recipe schema is built on.
"""

from __future__ import annotations

import json
import unittest

from btap.modeling import loads as Loads
from btap.modeling import shw as Shw
from btap.modeling.hvac import efficiency as Efficiency
from btap.modeling.hvac import thermostats as Thermostats
from btap.modeling.hvac import ventilation as Ventilation
from btap.stock import write_recipe
from tests.support import needs_sdk

# What the model is built with, and what the recipe must report back.
KNOWN = {
    'lighting_power_density_w_m2': 11.0,
    'lighting_fraction_radiant': 0.3,
    'plug_power_density_w_m2': 7.5,
    'elec_equipment_fraction_latent': 0.1,
    'infiltration_air_changes_per_hour': 0.35,
    'occupancy_m2_per_person': 10.3,
    'fan_total_eff': 0.62,
    'fan_motor_eff': 0.91,
    'pump_motor_eff': 0.88,
    'shw_thermal_eff': 0.82,
    'shw_off_cycle_ua_w_per_k': 6.0,
    'heating_occupied_c': 21.0,
    'heating_setback_c': 16.0,
    'cooling_constant_c': 24.0,
    'economizer_max_drybulb_c': 24.0,
}


def _build():
    """A model whose every performance value is known by construction."""
    import openstudio

    model = openstudio.model.Model()

    space_type = openstudio.model.SpaceType(model)
    space_type.setName('Known Space Type')
    space = openstudio.model.Space(model)
    space.setName('Known Space')
    space.setSpaceType(space_type)
    pts = openstudio.Point3dVector()
    for x, y in ((0, 0), (10, 0), (10, 10), (0, 10)):
        pts.append(openstudio.Point3d(x, y, 0.0))
    floor = openstudio.model.Surface(pts, model)
    floor.setSpace(space)
    floor.setSurfaceType('Floor')

    Loads.set_lighting(space_type,
                       watts_per_area_si=KNOWN['lighting_power_density_w_m2'],
                       radiant=KNOWN['lighting_fraction_radiant'])
    Loads.set_electric_equipment(
        space_type, watts_per_area_si=KNOWN['plug_power_density_w_m2'],
        latent=KNOWN['elec_equipment_fraction_latent'])
    Loads.set_infiltration(
        space_type,
        air_changes_per_hour=KNOWN['infiltration_air_changes_per_hour'])
    Loads.set_people(space_type,
                     area_per_person_si=KNOWN['occupancy_m2_per_person'])

    Efficiency.set_fan_efficiency(
        openstudio.model.FanConstantVolume(model),
        total_efficiency=KNOWN['fan_total_eff'],
        motor_efficiency=KNOWN['fan_motor_eff'])
    Efficiency.set_pump_efficiency(
        openstudio.model.PumpConstantSpeed(model),
        motor_efficiency=KNOWN['pump_motor_eff'])

    heater = openstudio.model.WaterHeaterMixed(model)
    Shw.set_water_heater_efficiency(
        heater, thermal_efficiency=KNOWN['shw_thermal_eff'])
    Shw.set_water_heater_losses(
        heater, ua_w_per_k=KNOWN['shw_off_cycle_ua_w_per_k'])

    zone = openstudio.model.ThermalZone(model)
    zone.setName('Known Zone')
    space.setThermalZone(zone)
    heating = Thermostats.setback_schedule(
        model, 'Known Heating', occupied_c=KNOWN['heating_occupied_c'],
        setback_c=KNOWN['heating_setback_c'], occupied_from_hour=7,
        occupied_to_hour=18)
    Thermostats.set_zone_thermostat(
        zone, heating=heating, cooling=KNOWN['cooling_constant_c'])

    air_loop = openstudio.model.AirLoopHVAC(model)
    air_loop.setName('Known Loop')
    controller = openstudio.model.ControllerOutdoorAir(model)
    oa = openstudio.model.AirLoopHVACOutdoorAirSystem(model, controller)
    oa.addToNode(air_loop.supplyInletNode())
    Ventilation.set_economizer(
        controller, control_type='DifferentialDryBulb',
        maximum_limit_drybulb_c=KNOWN['economizer_max_drybulb_c'])
    Ventilation.set_demand_controlled_ventilation(air_loop)

    return model


@needs_sdk
class TestEverySetValueIsReadBack(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.recipe = write_recipe(_build(), building_type='Probe',
                                  vintage_name='known', source='built-in-test')

    def _loads(self, section, field):
        return (self.recipe['loads']['by_space_type']['Known Space Type']
                [section][field]['value'])

    def test_the_loads_come_back(self):
        for section, field in (
                ('lighting', 'lighting_power_density_w_m2'),
                ('lighting', 'lighting_fraction_radiant'),
                ('plugs', 'plug_power_density_w_m2'),
                ('plugs', 'elec_equipment_fraction_latent'),
                ('infiltration', 'infiltration_air_changes_per_hour'),
                ('occupancy', 'occupancy_m2_per_person')):
            with self.subTest(field):
                self.assertAlmostEqual(KNOWN[field],
                                       self._loads(section, field), places=5)

    def test_the_equipment_comes_back(self):
        equipment = self.recipe['equipment']
        for group, field in (('fans', 'fan_total_eff'),
                             ('fans', 'fan_motor_eff'),
                             ('pumps', 'pump_motor_eff'),
                             ('water_heaters', 'shw_thermal_eff'),
                             ('water_heaters', 'shw_off_cycle_ua_w_per_k')):
            with self.subTest(field):
                self.assertAlmostEqual(KNOWN[field],
                                       equipment[group][field]['value'],
                                       places=5)

    def test_the_setback_profile_comes_back(self):
        heating = self.recipe['controls']['thermostats']['heating_setpoint']
        self.assertTrue(heating['has_setback'])
        self.assertAlmostEqual(KNOWN['heating_occupied_c'],
                               heating['occupied_c'])
        self.assertAlmostEqual(KNOWN['heating_setback_c'],
                               heating['setback_c'])

    def test_the_constant_cooling_setpoint_comes_back(self):
        cooling = self.recipe['controls']['thermostats']['cooling_setpoint']
        self.assertFalse(cooling['has_setback'])
        self.assertAlmostEqual(KNOWN['cooling_constant_c'],
                               cooling['constant_c'])

    def test_the_economizer_and_dcv_come_back(self):
        row = self.recipe['controls']['economizers']['by_air_loop'][0]
        self.assertEqual('DifferentialDryBulb',
                         row['economizer_control_type'])
        self.assertAlmostEqual(
            KNOWN['economizer_max_drybulb_c'],
            row['economizer_maximum_limit_dry_bulb_temperature'])
        self.assertTrue(row['dcv_enabled'])

    def test_NOTHING_is_reported_that_was_not_set(self):
        """The other half of the round trip, and the easier one to get wrong:
        a section must not invent a value for equipment the model lacks."""
        equipment = self.recipe['equipment']
        self.assertNotIn('boilers', equipment,
                         'no boiler was built, so none may be reported')
        self.assertEqual(
            0, self.recipe['controls']['daylighting']['from']['count'])

        # The fixture's floor is built with no construction assigned, so the
        # envelope section LISTS it rather than inventing a U-value for it.
        # Asserting an empty list here was my own error: the writer was right
        # and the expectation was wrong. Naming the surface is the stronger
        # assertion anyway, because it pins the "absent, never defaulted"
        # behaviour inside the round trip instead of merely nearby.
        unreadable = self.recipe['envelope']['unreadable']
        self.assertEqual(1, len(unreadable))
        self.assertIn('no layered construction', unreadable[0]['why'])
        self.assertEqual(
            {}, self.recipe['envelope']['opaque'],
            'and no aggregate is emitted from a surface it could not read')

    def test_the_whole_recipe_survives_JSON(self):
        restored = json.loads(json.dumps(self.recipe, sort_keys=True))
        self.assertEqual(self.recipe['schema'], restored['schema'])
        self.assertAlmostEqual(
            KNOWN['fan_total_eff'],
            restored['equipment']['fans']['fan_total_eff']['value'])


if __name__ == '__main__':
    unittest.main()
