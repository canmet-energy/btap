"""The recipe writer's equipment, HVAC and assembly layers (#196)."""

from __future__ import annotations

import unittest

from btap.audit import AuditLog
from btap.modeling.hvac import efficiency as Efficiency
from btap.modeling.recipe import equipment_section, hvac_section, write_recipe
from btap.modeling.recipe.writer import SCHEMA
from tests.support import needs_sdk


@needs_sdk
class TestEquipmentSection(unittest.TestCase):

    def test_fan_efficiencies_are_grouped_BY_CLASS(self):
        """Forty fans are one `fan_total_eff` in a recipe, not forty."""
        import openstudio

        model = openstudio.model.Model()
        for _ in range(3):
            Efficiency.set_fan_efficiency(
                openstudio.model.FanConstantVolume(model),
                total_efficiency=0.6, motor_efficiency=0.9)
        Efficiency.set_fan_efficiency(
            openstudio.model.FanVariableVolume(model), total_efficiency=0.6,
            motor_efficiency=0.9)

        fans = equipment_section(model)['fans']
        self.assertAlmostEqual(0.6, fans['fan_total_eff']['value'])
        self.assertAlmostEqual(0.9, fans['fan_motor_eff']['value'])
        self.assertEqual(4, fans['fan_total_eff']['from']['objects'])
        self.assertEqual({'FanConstantVolume': 3, 'FanVariableVolume': 1},
                         fans['from']['by_class'])

    def test_FanZoneExhaust_contributes_a_total_but_NO_motor(self):
        """It has no motor-efficiency field — measured in #192 cluster 1 — so
        a duck-typed read would report nothing for it."""
        import openstudio

        model = openstudio.model.Model()
        Efficiency.set_fan_efficiency(
            openstudio.model.FanZoneExhaust(model), total_efficiency=0.45)

        fans = equipment_section(model)['fans']
        self.assertEqual(1, fans['fan_total_eff']['from']['objects'])
        self.assertNotIn('fan_motor_eff', fans)

    def test_a_curve_based_fan_is_COUNTED_and_excluded_from_the_value(self):
        import openstudio

        model = openstudio.model.Model()
        Efficiency.set_fan_efficiency(
            openstudio.model.FanConstantVolume(model), total_efficiency=0.6)
        openstudio.model.FanComponentModel(model)

        fans = equipment_section(model)['fans']
        self.assertEqual(1, fans['fan_total_eff']['from']['objects'],
                         'the scalar fan only')
        self.assertEqual(1, fans['from']['by_class']['FanComponentModel'])
        self.assertIn('NOT included', fans['from']['note'])

    def test_a_stratified_tank_is_in_the_efficiency_but_NOT_the_UA(self):
        """It splits flue from skin loss and expresses skin per unit area, so
        its loss is not a mixed-tank W/K UA."""
        import openstudio

        from btap.modeling import shw as Shw

        model = openstudio.model.Model()
        mixed = openstudio.model.WaterHeaterMixed(model)
        Shw.set_water_heater_efficiency(mixed, thermal_efficiency=0.8)
        Shw.set_water_heater_losses(mixed, ua_w_per_k=6.0)
        stratified = openstudio.model.WaterHeaterStratified(model)
        Shw.set_water_heater_efficiency(stratified, thermal_efficiency=0.8)

        heaters = equipment_section(model)['water_heaters']
        self.assertEqual(2, heaters['shw_thermal_eff']['from']['objects'])
        self.assertEqual(1, heaters['shw_off_cycle_ua_w_per_k']['from']
                         ['objects'])
        self.assertIn('NOT in the UA', heaters['from']['note'])

    def test_the_boiler_design_outlet_temperature_is_declared_UNMAPPED(self):
        """`BoilerHotWater` has no such field — it carries
        `waterOutletUpperTemperatureLimit()`, which is a LIMIT. Mapping
        osruby's field to it would label a different quantity with its name."""
        import openstudio

        model = openstudio.model.Model()
        openstudio.model.BoilerHotWater(model)

        boilers = equipment_section(model)['boilers']
        self.assertIn('hw_boiler_water_outlet_upper_temperature_limit',
                      boilers)
        self.assertNotIn('hw_boiler_design_water_outlet_temperature', boilers)
        unmapped = {row['field'] for row in boilers['not_mapped']}
        self.assertIn('hw_boiler_design_water_outlet_temperature', unmapped)

    def test_absent_equipment_omits_its_subsection(self):
        import openstudio

        model = openstudio.model.Model()
        section = equipment_section(model)
        for key in ('fans', 'pumps', 'water_heaters', 'boilers'):
            self.assertNotIn(key, section)
        self.assertIn('sizing', section, 'which every model has')


@needs_sdk
class TestHvacSection(unittest.TestCase):

    def test_an_unrecognised_system_is_UNRESOLVED_not_named(self):
        """The rule the whole section exists for: a recipe naming a catalogue
        system the model is not would build something that silently differs
        from the original."""
        import openstudio

        model = openstudio.model.Model()
        air_loop = openstudio.model.AirLoopHVAC(model)
        air_loop.setName('Hand Built Rooftop Thing')
        zone = openstudio.model.ThermalZone(model)
        zone.setName('Z1')
        air_loop.addBranchForZone(zone)

        audit = AuditLog()
        section = hvac_section(model, audit=audit)
        self.assertEqual(0, section['from']['resolved'])
        for entry in section['zone_groups']:
            self.assertFalse(entry['resolved'])
            self.assertNotIn('system', entry,
                             'no name is synthesised for it')
            self.assertIn('descriptive', entry)
            self.assertIn('GUESS', entry['note'])
        self.assertTrue(any(e.get('level') == 'warning'
                            for e in audit.entries))

    def test_family_guess_stays_under_DESCRIPTIVE(self):
        """It is explicitly a guess in `classify.py`, so it must not be
        promoted to the `system` field."""
        import openstudio

        model = openstudio.model.Model()
        air_loop = openstudio.model.AirLoopHVAC(model)
        zone = openstudio.model.ThermalZone(model)
        air_loop.addBranchForZone(zone)

        for entry in hvac_section(model)['zone_groups']:
            self.assertNotIn('family_guess', entry)
            self.assertIn('family_guess', entry.get('descriptive', {}))

    def test_identical_groups_COLLAPSE_to_one_description(self):
        """phylroy's generic constraint: on `Office_pre-1960` 47 zone groups
        reduce to 10 distinct descriptions, so emitting all 47 repeats the
        same dictionary and describes nothing extra."""
        import openstudio

        model = openstudio.model.Model()
        for n in range(4):
            air_loop = openstudio.model.AirLoopHVAC(model)
            air_loop.setName(f'Identical Loop {n}')
            zone = openstudio.model.ThermalZone(model)
            zone.setName(f'Zone {n}')
            air_loop.addBranchForZone(zone)

        section = hvac_section(model)
        self.assertEqual(4, section['from']['zone_groups'])
        self.assertEqual(
            1, section['from']['distinct_descriptions'],
            'four identical systems are ONE description')
        entry = section['zone_groups'][0]
        self.assertEqual(4, entry['zone_groups'])
        self.assertEqual(4, len(entry['zones']))
        self.assertEqual(4, len(entry['air_loops']))


@needs_sdk
class TestWriteRecipe(unittest.TestCase):

    def test_it_assembles_every_section(self):
        import openstudio

        model = openstudio.model.Model()
        recipe = write_recipe(model, building_type='Office',
                              vintage='pre-1960', source='probe.osm')
        self.assertEqual(SCHEMA, recipe['schema'])
        for key in ('envelope', 'loads', 'controls', 'equipment', 'hvac'):
            self.assertIn(key, recipe)

    def test_the_building_type_and_vintage_are_CARRIED_not_inferred(self):
        """A model does not record what building type its author meant, so
        guessing one would put an invented label on real values."""
        import openstudio

        model = openstudio.model.Model()
        recipe = write_recipe(model)
        self.assertIsNone(recipe['building_type'])
        self.assertIsNone(recipe['vintage'])
        self.assertIsNone(recipe['source'])

    def test_it_is_JSON_serialisable(self):
        """A recipe that cannot round-trip through JSON is not a recipe."""
        import json

        import openstudio

        model = openstudio.model.Model()
        recipe = write_recipe(model, building_type='Office')
        restored = json.loads(json.dumps(recipe, sort_keys=True))
        self.assertEqual(recipe['schema'], restored['schema'])
        self.assertEqual('Office', restored['building_type'])


if __name__ == '__main__':
    unittest.main()
