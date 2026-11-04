"""The recipe reader, and what the round trip does and does not preserve (#198).

The headline measurement, on the real archetypes:

    Office_pre-1960    Wall  U 0.5201 -> 0.5201   spread 1.01x -> 1.0x
                       Floor U 2.0937 -> 2.0937   spread 4.22x -> 1.0x
    Office_1980-2004   Wall  U 0.4468 -> 0.4468   spread 1.9x  -> 1.0x

The MEAN is preserved exactly; the DISTRIBUTION is destroyed. And the exact U
match is not evidence of a lossless round trip — it is evidence that the
aggregation is idempotent. A test asserting only "U matches" would pass while
42 ground floors spanning 4.2:1 were flattened into one value, so these tests
pin both halves.
"""

from __future__ import annotations

import unittest

from btap._compat import opt
from btap.audit import AuditLog
from btap.modeling import loads as Loads
from btap.modeling.hvac import efficiency as Efficiency
from btap.stock import RecipeError, build_from_recipe, envelope_section, write_recipe
from btap.stock.writer import SCHEMA
from tests.support import needs_sdk


def _opaque_construction(model, name, conductivity, thickness=0.1):
    import openstudio

    material = openstudio.model.StandardOpaqueMaterial(model)
    material.setName(f'{name} Material')
    material.setConductivity(conductivity)
    material.setThickness(thickness)
    construction = openstudio.model.Construction(model)
    construction.setName(name)
    construction.setLayers([material])
    return construction


def _wall(model, space, construction, offset=0.0, width=4.0, height=3.0):
    import openstudio

    pts = openstudio.Point3dVector()
    for x, z in ((offset, 0), (offset + width, 0),
                 (offset + width, height), (offset, height)):
        pts.append(openstudio.Point3d(x, 0.0, z))
    surface = openstudio.model.Surface(pts, model)
    surface.setSpace(space)
    surface.setSurfaceType('Wall')
    surface.setOutsideBoundaryCondition('Outdoors')
    surface.setConstruction(construction)
    return surface


def _model_with_two_wall_assemblies():
    """Geometry whose walls genuinely DIFFER, so the flattening is visible."""
    import openstudio

    model = openstudio.model.Model()
    space_type = openstudio.model.SpaceType(model)
    space_type.setName('Probe')
    space = openstudio.model.Space(model)
    space.setSpaceType(space_type)
    _wall(model, space, _opaque_construction(model, 'Tight', 0.03), offset=0.0)
    _wall(model, space, _opaque_construction(model, 'Leaky', 0.12), offset=5.0)
    return model, space_type


@needs_sdk
class TestWhatTheRoundTripPreserves(unittest.TestCase):

    def test_the_MEAN_survives_and_the_SPREAD_does_not(self):
        """Both halves, because the first alone would hide the second."""
        model, _space_type = _model_with_two_wall_assemblies()
        before = envelope_section(model)['opaque']['Wall:Outdoors']
        self.assertGreater(
            before['from']['u_spread_ratio'], 1.5,
            'the fixture must genuinely vary, or this test proves nothing')

        recipe = write_recipe(model, building_type='Probe')
        build_from_recipe(recipe, model)
        after = envelope_section(model)['opaque']['Wall:Outdoors']

        self.assertAlmostEqual(
            before['u_si'], after['u_si'], places=3,
            msg='the area-weighted mean is preserved exactly')
        self.assertAlmostEqual(
            1.0, after['from']['u_spread_ratio'], places=3,
            msg='and the variation is GONE — every wall now carries the mean')
        self.assertIn(
            'spread_warning', before['from'],
            'which the recipe warned about before it was applied')

    def test_a_lossy_aggregate_RE_WARNS_when_applied(self):
        """Averaging 76 walls into one number does not become safe because
        the number is now being written."""
        model, _space_type = _model_with_two_wall_assemblies()
        recipe = write_recipe(model, building_type='Probe')
        audit = AuditLog()
        build_from_recipe(recipe, model, audit=audit)
        lossy = [e for e in audit.entries
                 if e.get('level') == 'warning'
                 and 'flags as lossy' in str(e.get('value')
                                             or e.get('action') or '')]
        self.assertTrue(lossy, 'the warning must survive into the apply')

    def test_loads_and_equipment_round_trip_exactly(self):
        import openstudio

        model = openstudio.model.Model()
        space_type = openstudio.model.SpaceType(model)
        space_type.setName('Probe')
        space = openstudio.model.Space(model)
        space.setSpaceType(space_type)
        pts = openstudio.Point3dVector()
        for x, y in ((0, 0), (10, 0), (10, 10), (0, 10)):
            pts.append(openstudio.Point3d(x, y, 0.0))
        floor = openstudio.model.Surface(pts, model)
        floor.setSpace(space)
        floor.setSurfaceType('Floor')
        Loads.set_lighting(space_type, watts_per_area_si=11.0, radiant=0.3)
        Loads.set_electric_equipment(space_type, watts_per_area_si=7.5)
        Loads.set_infiltration(space_type, air_changes_per_hour=0.35)
        Efficiency.set_fan_efficiency(
            openstudio.model.FanConstantVolume(model),
            total_efficiency=0.62, motor_efficiency=0.91)

        recipe = write_recipe(model, building_type='Probe')
        target = openstudio.model.Model()
        target_type = openstudio.model.SpaceType(target)
        target_type.setName('Probe')
        openstudio.model.FanConstantVolume(target)
        build_from_recipe(recipe, target)

        again = write_recipe(target, building_type='Probe')
        lighting = (again['loads']['by_space_type']['Probe']['lighting'])
        self.assertAlmostEqual(
            11.0, lighting['lighting_power_density_w_m2']['value'])
        self.assertAlmostEqual(
            0.3, lighting['lighting_fraction_radiant']['value'])
        self.assertAlmostEqual(
            0.62, again['equipment']['fans']['fan_total_eff']['value'])
        self.assertAlmostEqual(
            0.91, again['equipment']['fans']['fan_motor_eff']['value'])


@needs_sdk
class TestWhatItRefuses(unittest.TestCase):

    def test_an_UNRESOLVED_hvac_group_is_refused_by_name(self):
        """The rule the writer exists to protect, and the reader is where it
        would be broken: building from `family_guess` would produce a system
        the source model is not."""
        import openstudio

        model = openstudio.model.Model()
        air_loop = openstudio.model.AirLoopHVAC(model)
        air_loop.setName('Hand Built Thing')
        zone = openstudio.model.ThermalZone(model)
        zone.setName('Z1')
        air_loop.addBranchForZone(zone)

        recipe = write_recipe(model, building_type='Probe')
        result = build_from_recipe(recipe, model)
        self.assertTrue(result['refused'])
        self.assertTrue(any('family_guess is a guess' in row
                            for row in result['refused']))
        self.assertTrue(any('Z1' in row for row in result['refused']))

    def test_an_unknown_SCHEMA_is_refused(self):
        import openstudio

        with self.assertRaises(RecipeError) as caught:
            build_from_recipe({'schema': SCHEMA + 99},
                              openstudio.model.Model())
        self.assertIn('refusing rather than guessing', str(caught.exception))

    def test_a_space_type_MISSING_from_the_geometry_is_skipped_not_created(self):
        """Geometry is an input. A recipe naming a space type the geometry
        does not have is a mismatch to report, not one to paper over by
        inventing the space type."""
        import openstudio

        model = openstudio.model.Model()
        space_type = openstudio.model.SpaceType(model)
        space_type.setName('Present')
        space = openstudio.model.Space(model)
        space.setSpaceType(space_type)
        Loads.set_lighting(space_type, watts_per_area_si=9.0)
        recipe = write_recipe(model, building_type='Probe')
        recipe['loads']['by_space_type']['Absent'] = (
            recipe['loads']['by_space_type'].pop('Present'))

        target = openstudio.model.Model()
        result = build_from_recipe(recipe, target)
        self.assertTrue(any('no such space type' in row
                            for row in result['skipped']))
        self.assertEqual(0, len(target.getSpaceTypes()))

    def test_an_IMPOSSIBLE_u_value_is_skipped_with_the_reason(self):
        """A U higher than the air films alone cannot be built by any
        assembly, so the reader says so rather than writing a negative
        conductance."""
        model, _space_type = _model_with_two_wall_assemblies()
        recipe = write_recipe(model, building_type='Probe')
        recipe['envelope']['opaque']['Wall:Outdoors']['u_si'] = 99.0

        result = build_from_recipe(recipe, model)
        self.assertTrue(any('higher than the film resistance' in row
                            for row in result['skipped']))

    def test_daylighting_is_NOT_transferred(self):
        """A sensor position is specific to the geometry it was read from."""
        import openstudio

        from btap.modeling import lighting as Lighting

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        space = openstudio.model.Space(model)
        space.setThermalZone(zone)
        Lighting.add_daylighting_control(
            space, illuminance_setpoint_lux=500.0, position=(1.0, 1.0, 0.8))
        recipe = write_recipe(model, building_type='Probe')

        target = openstudio.model.Model()
        result = build_from_recipe(recipe, target)
        self.assertTrue(any('not transferable' in row
                            for row in result['skipped']))
        self.assertEqual(0, len(target.getDaylightingControls()))


@needs_sdk
class TestTheAccount(unittest.TestCase):

    def test_every_application_is_reported(self):
        """A caller has to be able to see which half of a recipe reached the
        model."""
        import openstudio

        model = openstudio.model.Model()
        space_type = openstudio.model.SpaceType(model)
        space_type.setName('Probe')
        space = openstudio.model.Space(model)
        space.setSpaceType(space_type)
        Loads.set_lighting(space_type, watts_per_area_si=11.0)
        recipe = write_recipe(model, building_type='Probe')

        result = build_from_recipe(recipe, model, audit=AuditLog())
        self.assertEqual({'applied', 'skipped', 'refused'}, set(result))
        self.assertTrue(any('lighting' in row for row in result['applied']))

    def test_UNTAGGED_space_types_are_re_warned_on_apply(self):
        """A caller should learn that a model will fail the NECB space-type
        gate here, not from a refused compliance run."""
        import openstudio

        model = openstudio.model.Model()
        space_type = openstudio.model.SpaceType(model)
        space_type.setName('Untagged')
        space = openstudio.model.Space(model)
        space.setSpaceType(space_type)
        pts = openstudio.Point3dVector()
        for x, y in ((0, 0), (5, 0), (5, 5), (0, 5)):
            pts.append(openstudio.Point3d(x, y, 0.0))
        floor = openstudio.model.Surface(pts, model)
        floor.setSpace(space)
        floor.setSurfaceType('Floor')
        recipe = write_recipe(model, building_type='Probe')

        audit = AuditLog()
        build_from_recipe(recipe, model, audit=audit)
        self.assertTrue(any('preflight' in str(e.get('value')
                                               or e.get('action') or '')
                            for e in audit.entries))

    def test_a_bare_number_is_accepted_as_well_as_an_aggregate(self):
        """So a hand-authored recipe does not have to carry fake
        provenance."""
        import openstudio

        model = openstudio.model.Model()
        space_type = openstudio.model.SpaceType(model)
        space_type.setName('Probe')
        space = openstudio.model.Space(model)
        space.setSpaceType(space_type)
        recipe = {'schema': SCHEMA,
                  'loads': {'by_space_type': {'Probe': {
                      'lighting': {'lighting_power_density_w_m2': 12.5}}}}}

        build_from_recipe(recipe, model)
        lights = next(iter(space_type.lights()))
        self.assertAlmostEqual(
            12.5, opt(lights.lightsDefinition().wattsperSpaceFloorArea()))


if __name__ == '__main__':
    unittest.main()
