"""`btap.modeling.loads`: the load primitives lifted out of the NECB appliers.

Issue #183 phase 0. Before the lift, infiltration, plug loads and lighting
fractions existed ONLY inside `btap.codes.necb`, so a model authored through
`btap.modeling` alone could not set them — and for stock and retrofit work on
a pre-1960 building, infiltration is arguably its dominant difference from a
2005 one.

`set_infiltration`, `set_electric_equipment` and `set_gas_equipment` are
witnessed by the NECB appliers that now call them, and by the frozen corpus
staying byte-identical across the lift. `set_lighting` is NOT: it has no
production caller, because neither NECB lighting path fits it — the main path
computes its own LPD through `_single_lights_instance`, and
`_add_additional_lights` deliberately ADDS a second definition where
`single_instance` would collapse to one. So these tests are the only thing
exercising it, which is why it gets the most of them.
"""

from __future__ import annotations

import unittest

from btap._compat import opt
from btap.audit import AuditLog
from btap.modeling import loads as Loads
from tests.support import needs_sdk


def _space_type(name='Probe Space Type'):
    import openstudio

    model = openstudio.model.Model()
    space_type = openstudio.model.SpaceType(model)
    space_type.setName(name)
    return model, space_type


@needs_sdk
class TestInfiltration(unittest.TestCase):

    def test_each_method_lands_on_the_object_ALONE(self):
        """One call, one calculation method. My first version of this test
        passed all three and asserted all three stuck, which the SDK does not
        permit — measured on 3.11, each setter switches
        `designFlowRateCalculationMethod` and CLEARS the other two."""
        cases = (('per_exterior_area_si', 0.0003, 'Flow/ExteriorArea',
                  'flowperExteriorSurfaceArea'),
                 ('per_exterior_wall_area_si', 0.0004, 'Flow/ExteriorWallArea',
                  'flowperExteriorWallArea'),
                 ('air_changes_per_hour', 0.25, 'AirChanges/Hour',
                  'airChangesperHour'))
        for kwarg, value, method, reader in cases:
            with self.subTest(kwarg):
                _model, space_type = _space_type()
                instance = Loads.set_infiltration(
                    space_type, audit=AuditLog(), **{kwarg: value})
                self.assertIsNotNone(instance)
                self.assertEqual(method,
                                 instance.designFlowRateCalculationMethod())
                self.assertAlmostEqual(value, opt(getattr(instance, reader)()))
                self.assertEqual(
                    1, len(space_type.spaceInfiltrationDesignFlowRates()))

    def test_passing_TWO_methods_is_REFUSED(self):
        """Not last-wins. A caller passing two has a misconception, and the
        SDK would silently keep only the second — invisible in a model nobody
        re-reads.

        The NECB applier has the same shape and is correct by DATA, not by
        design: 0 of 308 space-type rows in either edition sets more than one
        infiltration column. This is what keeps that true if one ever does.
        """
        _model, space_type = _space_type()
        with self.assertRaises(ValueError) as caught:
            Loads.set_infiltration(space_type, per_exterior_area_si=0.0003,
                                   air_changes_per_hour=0.25)
        self.assertIn('ONE calculation method', str(caught.exception))
        self.assertEqual([], list(space_type.spaceInfiltrationDesignFlowRates()),
                         'a refused call must write nothing')

    def test_an_all_absent_call_writes_NOTHING(self):
        """The NECB applier returns early for an all-zero record rather than
        writing zeros, and the primitive must preserve that: a space type with
        no infiltration object is different from one carrying zeros."""
        _model, space_type = _space_type()
        self.assertIsNone(Loads.set_infiltration(space_type))
        self.assertEqual([], list(space_type.spaceInfiltrationDesignFlowRates()))

    def test_a_zero_quantity_is_skipped_not_written(self):
        _model, space_type = _space_type()
        instance = Loads.set_infiltration(space_type, per_exterior_area_si=0.0,
                                          air_changes_per_hour=0.5)
        self.assertFalse(instance.flowperExteriorSurfaceArea().is_initialized(),
                         'a zero must leave the field unset, not write 0.0')
        self.assertAlmostEqual(0.5, opt(instance.airChangesperHour()))

    def test_a_second_call_REUSES_the_instance(self):
        _model, space_type = _space_type()
        first = Loads.set_infiltration(space_type, air_changes_per_hour=0.25)
        second = Loads.set_infiltration(space_type, air_changes_per_hour=0.75)
        self.assertEqual(first.handle(), second.handle())
        self.assertEqual(1, len(space_type.spaceInfiltrationDesignFlowRates()))
        self.assertAlmostEqual(0.75, opt(second.airChangesperHour()))

    def test_a_schedule_is_taken_as_an_OBJECT_not_a_name(self):
        """Resolving a name belongs to whoever owns the schedule library —
        `codes.necb.loads.schedules` for NECB, the caller for stock work."""
        import openstudio

        model, space_type = _space_type()
        schedule = openstudio.model.ScheduleConstant(model)
        schedule.setName('Probe Infiltration Schedule')
        instance = Loads.set_infiltration(space_type, air_changes_per_hour=0.3,
                                          schedule=schedule)
        self.assertEqual(schedule.handle(), opt(instance.schedule()).handle())


@needs_sdk
class TestEquipment(unittest.TestCase):

    def test_electric_density_and_fractions(self):
        _model, space_type = _space_type()
        equip = Loads.set_electric_equipment(
            space_type, watts_per_area_si=10.5, latent=0.1, radiant=0.3,
            lost=0.2, audit=AuditLog())
        definition = equip.electricEquipmentDefinition()
        self.assertAlmostEqual(10.5,
                               opt(definition.wattsperSpaceFloorArea()))
        self.assertAlmostEqual(0.1, definition.fractionLatent())
        self.assertAlmostEqual(0.3, definition.fractionRadiant())
        self.assertAlmostEqual(0.2, definition.fractionLost())

    def test_gas_density(self):
        _model, space_type = _space_type()
        equip = Loads.set_gas_equipment(space_type, watts_per_area_si=4.25)
        self.assertAlmostEqual(
            4.25, opt(equip.gasEquipmentDefinition().wattsperSpaceFloorArea()))

    def test_a_zero_density_writes_nothing(self):
        _model, space_type = _space_type()
        self.assertIsNone(
            Loads.set_electric_equipment(space_type, watts_per_area_si=0.0))
        self.assertEqual([], list(space_type.electricEquipment()))

    def test_a_zero_FRACTION_leaves_the_SDK_default(self):
        """The distinction `_set_fractions` carried and a mechanical lift would
        have lost: a zero in the NECB table means "leave the SDK default", not
        "set zero", and the SDK's defaults are not all zero."""
        _model, space_type = _space_type()
        bare = Loads.set_electric_equipment(space_type, watts_per_area_si=5.0)
        default_radiant = bare.electricEquipmentDefinition().fractionRadiant()

        _model2, other = _space_type('Other')
        zeroed = Loads.set_electric_equipment(other, watts_per_area_si=5.0,
                                              radiant=0.0)
        self.assertAlmostEqual(
            default_radiant,
            zeroed.electricEquipmentDefinition().fractionRadiant(),
            'a zero fraction must not overwrite the SDK default')


@needs_sdk
class TestLighting(unittest.TestCase):
    """The primitive with NO production caller — see the module docstring."""

    def test_density_and_fractions(self):
        _model, space_type = _space_type()
        lights = Loads.set_lighting(
            space_type, watts_per_area_si=8.0, return_air_fraction=0.2,
            radiant=0.4, visible=0.15, audit=AuditLog())
        definition = lights.lightsDefinition()
        self.assertEqual('Watts/Area', definition.designLevelCalculationMethod())
        self.assertAlmostEqual(8.0, opt(definition.wattsperSpaceFloorArea()))
        self.assertAlmostEqual(0.2, definition.returnAirFraction())
        self.assertAlmostEqual(0.4, definition.fractionRadiant())
        self.assertAlmostEqual(0.15, definition.fractionVisible())

    def test_watts_per_person_is_its_own_method(self):
        _model, space_type = _space_type()
        lights = Loads.set_lighting(space_type, watts_per_person=60.0)
        definition = lights.lightsDefinition()
        self.assertEqual('Watts/Person',
                         definition.designLevelCalculationMethod())
        self.assertAlmostEqual(60.0, opt(definition.wattsperPerson()))

    def test_area_and_person_together_are_REFUSED(self):
        """Exclusive by the same measurement: `setWattsperPerson` switches
        `designLevelCalculationMethod` and clears the area value."""
        _model, space_type = _space_type()
        with self.assertRaises(ValueError) as caught:
            Loads.set_lighting(space_type, watts_per_area_si=8.0,
                               watts_per_person=60.0)
        self.assertIn('exclusive', str(caught.exception))

    def test_it_attaches_to_the_space_type(self):
        _model, space_type = _space_type()
        lights = Loads.set_lighting(space_type, watts_per_area_si=8.0)
        self.assertEqual(1, len(space_type.lights()))
        self.assertEqual(space_type.handle(),
                         opt(lights.spaceType()).handle())

    def test_given_nothing_it_writes_nothing(self):
        _model, space_type = _space_type()
        self.assertIsNone(Loads.set_lighting(space_type))
        self.assertEqual([], list(space_type.lights()))

    def test_a_second_call_reuses_the_instance(self):
        _model, space_type = _space_type()
        first = Loads.set_lighting(space_type, watts_per_area_si=8.0)
        second = Loads.set_lighting(space_type, watts_per_area_si=12.0)
        self.assertEqual(first.handle(), second.handle())
        self.assertEqual(1, len(space_type.lights()))

    def test_the_name_is_overridable(self):
        _model, space_type = _space_type()
        lights = Loads.set_lighting(space_type, watts_per_area_si=8.0,
                                    name='Task Lighting')
        self.assertEqual('Task Lighting', lights.nameString())


@needs_sdk
class TestScaling(unittest.TestCase):
    """SETTING and SCALING are separate operations, not one function with a
    mode flag: a write versus a read-modify-write, and a single entry point
    taking both an absolute value and a factor must decide what it means when
    given both. osruby made the same split —
    `ScaleLoads::scale_electrical_loads` beside the absolute setters, driven by
    its `elec_equipment_scaling_factor` and `lighting_scaling_factor` columns.

    Scaling is what stock work usually wants: "this wing carries 1.3x the
    baseline plug load" is a claim about a RATIO, and it survives a later
    change to the baseline where a hard-coded W/m^2 would not.
    """

    def test_electric_equipment_scales(self):
        _model, space_type = _space_type()
        Loads.set_electric_equipment(space_type, watts_per_area_si=10.0)
        self.assertEqual(1, Loads.scale_electric_equipment(space_type,
                                                           factor=1.3))
        definition = next(iter(space_type.electricEquipment())) \
            .electricEquipmentDefinition()
        self.assertAlmostEqual(13.0, opt(definition.wattsperSpaceFloorArea()))

    def test_lighting_scales(self):
        _model, space_type = _space_type()
        Loads.set_lighting(space_type, watts_per_area_si=8.0)
        self.assertEqual(1, Loads.scale_lighting(space_type, factor=0.5))
        definition = next(iter(space_type.lights())).lightsDefinition()
        self.assertAlmostEqual(4.0, opt(definition.wattsperSpaceFloorArea()))

    def test_scaling_COMPOUNDS_which_is_the_point_and_the_hazard(self):
        """Two calls multiply. That is correct for a read-modify-write and is
        worth pinning, because a caller who treats it as idempotent gets a
        quietly wrong model rather than an error."""
        _model, space_type = _space_type()
        Loads.set_electric_equipment(space_type, watts_per_area_si=10.0)
        Loads.scale_electric_equipment(space_type, factor=2.0)
        Loads.scale_electric_equipment(space_type, factor=2.0)
        definition = next(iter(space_type.electricEquipment())) \
            .electricEquipmentDefinition()
        self.assertAlmostEqual(40.0, opt(definition.wattsperSpaceFloorArea()))

    def test_a_non_watts_per_area_density_is_REPORTED_not_converted(self):
        """A `Watts/Person` definition is left alone. Converting it to
        Watts/Area would silently change the method the caller chose, and
        scaling nothing without saying so would be worse."""
        _model, space_type = _space_type()
        Loads.set_lighting(space_type, watts_per_person=60.0)
        audit = AuditLog()
        self.assertEqual(0, Loads.scale_lighting(space_type, factor=2.0,
                                                 audit=audit))
        definition = next(iter(space_type.lights())).lightsDefinition()
        self.assertEqual('Watts/Person',
                         definition.designLevelCalculationMethod())
        self.assertAlmostEqual(60.0, opt(definition.wattsperPerson()),
                               msg='an unscalable density must be untouched')
        self.assertTrue(
            any('not scaled' in str(e.get('value') or e.get('action') or '')
                for e in audit.entries),
            'the skip must be reported, not silent')

    def test_scaling_an_empty_space_type_is_zero_not_an_error(self):
        _model, space_type = _space_type()
        self.assertEqual(0, Loads.scale_lighting(space_type, factor=2.0))
        self.assertEqual(0, Loads.scale_electric_equipment(space_type,
                                                           factor=2.0))


@needs_sdk
class TestASharedDefinitionIsScaledONCE(unittest.TestCase):
    """Several load instances can SHARE one definition, and a per-instance
    loop then applies the factor once per sharer.

    Measured before the fix: two `Lights` on one `LightsDefinition` at
    10 W/m^2, scaled x2 by a naive per-instance loop, came out at 40 W/m^2.
    The hand-built campus archetypes do not share today — 9 Lights and 9
    definitions in each Office-Small vintage, 0 shared — so this was latent
    there, and stops being latent the moment anything scales model-wide,
    because sharing ACROSS space types is how a library construction set or a
    copied space type ends up wired (phylroy raised it, 2026-11-03).
    """

    @staticmethod
    def _two_lights_one_definition(model=None, watts=10.0):
        import openstudio

        model = model or openstudio.model.Model()
        definition = openstudio.model.LightsDefinition(model)
        definition.setName('Shared Lighting Definition')
        definition.setWattsperSpaceFloorArea(watts)
        types = []
        for n in range(2):
            space_type = openstudio.model.SpaceType(model)
            space_type.setName(f'Type {n}')
            lights = openstudio.model.Lights(definition)
            lights.setName(f'Lights {n}')
            lights.setSpaceType(space_type)
            types.append(space_type)
        return model, definition, types

    def test_model_wide_scaling_applies_the_factor_ONCE(self):
        model, definition, _types = self._two_lights_one_definition()
        self.assertEqual(2, len(model.getLightss()))
        self.assertEqual(1, len(model.getLightsDefinitions()))

        scaled = Loads.scale_lighting_in_model(model, factor=2.0)
        self.assertEqual(1, scaled, 'one DEFINITION, not two instances')
        self.assertAlmostEqual(
            20.0, opt(definition.wattsperSpaceFloorArea()),
            msg='a shared definition scaled per instance would read 40.0')

    def test_per_space_type_scaling_also_dedupes(self):
        """The same hazard reaches the per-space-type form when two Lights in
        ONE space type share a definition."""
        import openstudio

        model = openstudio.model.Model()
        space_type = openstudio.model.SpaceType(model)
        space_type.setName('One Type')
        definition = openstudio.model.LightsDefinition(model)
        definition.setWattsperSpaceFloorArea(10.0)
        for n in range(2):
            lights = openstudio.model.Lights(definition)
            lights.setName(f'Lights {n}')
            lights.setSpaceType(space_type)

        self.assertEqual(1, Loads.scale_lighting(space_type, factor=2.0))
        self.assertAlmostEqual(20.0, opt(definition.wattsperSpaceFloorArea()))

    def test_model_wide_scaling_reaches_SPACE_attached_lights(self):
        """`Lights` can hang off a `Space` rather than a `SpaceType`, and
        "every space that has lighting" has to mean both."""
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        space.setName('Directly Lit Space')
        definition = openstudio.model.LightsDefinition(model)
        definition.setWattsperSpaceFloorArea(6.0)
        lights = openstudio.model.Lights(definition)
        lights.setSpace(space)

        self.assertEqual(1, Loads.scale_lighting_in_model(model, factor=0.5))
        self.assertAlmostEqual(3.0, opt(definition.wattsperSpaceFloorArea()))

    def test_it_does_NOT_create_lighting_where_there_is_none(self):
        """"All spaces that HAD lighting" is the question. A space with no
        Lights is left alone rather than given a density it never had."""
        import openstudio

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        space.setName('Unlit Space')
        self.assertEqual(0, Loads.scale_lighting_in_model(model, factor=2.0))
        self.assertEqual([], list(model.getLightss()))

    def test_equipment_model_wide_too(self):
        import openstudio

        model = openstudio.model.Model()
        definition = openstudio.model.ElectricEquipmentDefinition(model)
        definition.setWattsperSpaceFloorArea(8.0)
        for n in range(2):
            space_type = openstudio.model.SpaceType(model)
            space_type.setName(f'Equip Type {n}')
            equip = openstudio.model.ElectricEquipment(definition)
            equip.setSpaceType(space_type)
        self.assertEqual(
            1, Loads.scale_electric_equipment_in_model(model, factor=1.5))
        self.assertAlmostEqual(12.0, opt(definition.wattsperSpaceFloorArea()))


@needs_sdk
class TestAllFiveInfiltrationMethods(unittest.TestCase):
    """The first draft offered three of the SDK's five. osruby's
    `ecm_infiltration` names `infiltration_design_flow_rate` and
    `infiltration_flow_per_space` too, so a stock author needs all five."""

    def test_every_method_is_reachable(self):
        cases = (('design_flow_rate_si', 0.05, 'Flow/Space', 'designFlowRate'),
                 ('per_floor_area_si', 0.0002, 'Flow/Area',
                  'flowperSpaceFloorArea'),
                 ('per_exterior_area_si', 0.0003, 'Flow/ExteriorArea',
                  'flowperExteriorSurfaceArea'),
                 ('per_exterior_wall_area_si', 0.0004,
                  'Flow/ExteriorWallArea', 'flowperExteriorWallArea'),
                 ('air_changes_per_hour', 0.25, 'AirChanges/Hour',
                  'airChangesperHour'))
        self.assertEqual(
            5, len(cases),
            'the SDK enum has five members: '
            "('Flow/Space', 'Flow/Area', 'Flow/ExteriorArea', "
            "'Flow/ExteriorWallArea', 'AirChanges/Hour')")
        for kwarg, value, method, reader in cases:
            with self.subTest(kwarg):
                _model, space_type = _space_type()
                instance = Loads.set_infiltration(space_type,
                                                  **{kwarg: value})
                self.assertEqual(method,
                                 instance.designFlowRateCalculationMethod())
                self.assertAlmostEqual(value, opt(getattr(instance, reader)()))


@needs_sdk
class TestTheSplitOnWrite(unittest.TestCase):
    """#186: setting a value on a SHARED definition changed every instance
    using it, and the caller named one space type explicitly.

    Already in the corpus: 4 of the 28 campus archetypes share a definition,
    and all three `Hangar` vintages share a `LightsDefinition`, an
    `ElectricEquipmentDefinition` AND a `PeopleDefinition` between
    `Shop-Machinery` and `Shop-Machinery-Hangar`.
    """

    @staticmethod
    def _shared(model=None, watts=10.0, count=2):
        import openstudio

        model = model or openstudio.model.Model()
        definition = openstudio.model.LightsDefinition(model)
        definition.setName('Shared Lighting Definition')
        definition.setWattsperSpaceFloorArea(watts)
        types = []
        for n in range(count):
            space_type = openstudio.model.SpaceType(model)
            space_type.setName(f'Type {n}')
            lights = openstudio.model.Lights(definition)
            lights.setName(f'Lights {n}')
            lights.setSpaceType(space_type)
            types.append(space_type)
        return model, definition, types

    def test_setting_one_space_type_no_longer_changes_the_other(self):
        model, original, types = self._shared()
        Loads.set_lighting(types[0], watts_per_area_si=25.0, audit=AuditLog())

        self.assertAlmostEqual(
            25.0,
            opt(next(iter(types[0].lights())).lightsDefinition()
                .wattsperSpaceFloorArea()),
            msg='the space type that was asked for')
        self.assertAlmostEqual(
            10.0,
            opt(next(iter(types[1].lights())).lightsDefinition()
                .wattsperSpaceFloorArea()),
            msg='the space type that was NOT asked for must be untouched — '
                'before the fix it read 25.0')
        self.assertEqual(2, len(model.getLightsDefinitions()))
        self.assertAlmostEqual(10.0, opt(original.wattsperSpaceFloorArea()))

    def test_the_split_is_audited(self):
        _model, _original, types = self._shared()
        audit = AuditLog()
        Loads.set_lighting(types[0], watts_per_area_si=25.0, audit=audit)
        splits = [e for e in audit.entries
                  if 'split' in str(e.get('value') or e.get('action') or '')]
        self.assertEqual(
            1, len(splits),
            'a changed object graph must be in the trail; got '
            f'{[e.get("action") for e in audit.entries]}')
        self.assertEqual(2, splits[0]['inputs']['sharers_before'])

    def test_each_writer_gets_its_OWN_definition(self):
        """No reuse-by-name: see `unshared_definition`. Six sharers written
        give six definitions — the original, kept by whichever instance wrote
        last and so found itself alone, plus five clones."""
        model, _original, types = self._shared(count=6)
        for n, space_type in enumerate(types):
            Loads.set_lighting(space_type, watts_per_area_si=10.0 + n)
        self.assertEqual(6, len(model.getLightsDefinitions()))
        for n, space_type in enumerate(types):
            self.assertAlmostEqual(
                10.0 + n,
                opt(next(iter(space_type.lights())).lightsDefinition()
                    .wattsperSpaceFloorArea()),
                msg='every space type keeps its OWN value')

    def test_distinct_FRACTIONS_survive_an_identical_density(self):
        """Fable's finding, and the reason reuse-by-name is gone.

        Three sharers, one density, three radiant fractions. The value-keyed
        reuse found a 'matching' definition that other instances were already
        using and wrote the unmatched fraction into it, so the FIRST space
        type ended up with the LAST one's radiant fraction.

        Three sharers, not two: with two, the second writer is by then the only
        instance left on the original, takes the last-sharer branch, and never
        reaches the reuse path at all — which is why the first version of this
        suite could not see any of it.
        """
        _model, _original, types = self._shared(count=3)
        for space_type, radiant in zip(types, (0.3, 0.7, 0.1)):
            Loads.set_lighting(space_type, watts_per_area_si=25.0,
                               radiant=radiant)
        for space_type, radiant in zip(types, (0.3, 0.7, 0.1)):
            definition = next(iter(space_type.lights())).lightsDefinition()
            self.assertAlmostEqual(25.0,
                                   opt(definition.wattsperSpaceFloorArea()))
            self.assertAlmostEqual(
                radiant, definition.fractionRadiant(),
                msg=f'{space_type.nameString()} asked for {radiant}')

    def test_a_calculation_METHOD_cannot_bleed_between_sharers(self):
        """Fable's second case: the two densities are numerically equal, so a
        value-keyed name matched, and adopting that definition switched the
        method and left the first space type's watts-per-area reading None."""
        _model, _original, types = self._shared(count=3)
        Loads.set_lighting(types[0], watts_per_area_si=10.0)
        Loads.set_lighting(types[1], watts_per_person=10.0)
        first = next(iter(types[0].lights())).lightsDefinition()
        second = next(iter(types[1].lights())).lightsDefinition()
        self.assertEqual('Watts/Area', first.designLevelCalculationMethod())
        self.assertAlmostEqual(10.0, opt(first.wattsperSpaceFloorArea()))
        self.assertEqual('Watts/Person', second.designLevelCalculationMethod())
        self.assertAlmostEqual(10.0, opt(second.wattsperPerson()))

    def test_two_originals_whose_names_differ_late_stay_separate(self):
        """Fable's third case: the key truncated at the last colon, so
        `Bldg:Core` and `Bldg:Perim` both became `Bldg:W-25.0` — one object,
        and the second space type read the first's fractions."""
        import openstudio

        model = openstudio.model.Model()
        kept = []
        for suffix, radiant in (('Core', 0.1), ('Perim', 0.9)):
            definition = openstudio.model.LightsDefinition(model)
            definition.setName(f'Bldg:{suffix}')
            definition.setWattsperSpaceFloorArea(5.0)
            for n in range(2):
                space_type = openstudio.model.SpaceType(model)
                space_type.setName(f'{suffix} {n}')
                lights = openstudio.model.Lights(definition)
                lights.setName(f'{suffix} Lights {n}')
                lights.setSpaceType(space_type)
                if n == 0:
                    kept.append((space_type, radiant))
        for space_type, radiant in kept:
            Loads.set_lighting(space_type, watts_per_area_si=25.0,
                               radiant=radiant)
        handles = {str(next(iter(space_type.lights())).lightsDefinition()
                       .handle()) for space_type, _ in kept}
        self.assertEqual(2, len(handles),
                         'two different originals must not collapse into one')
        for space_type, radiant in kept:
            self.assertAlmostEqual(
                radiant,
                next(iter(space_type.lights())).lightsDefinition()
                .fractionRadiant())

    def test_gas_equipment_and_internal_mass_split_too(self):
        """Both bypassed `unshared_definition` under Fable's mutations with
        the suite staying green: nothing tested their sharing."""
        import openstudio

        model = openstudio.model.Model()
        for kind, definition_cls, instance_cls, setter, kwargs, reader in (
                ('gas', openstudio.model.GasEquipmentDefinition,
                 openstudio.model.GasEquipment, Loads.set_gas_equipment,
                 {'watts_per_area_si': 30.0}, 'wattsperSpaceFloorArea'),
                ('mass', openstudio.model.InternalMassDefinition,
                 openstudio.model.InternalMass, Loads.set_internal_mass,
                 {'per_floor_area_si': 2.5},
                 'surfaceAreaperSpaceFloorArea')):
            with self.subTest(kind):
                shared = definition_cls(model)
                shared.setName(f'Shared {kind}')
                types = []
                for n in range(3):
                    space_type = openstudio.model.SpaceType(model)
                    space_type.setName(f'{kind} Type {n}')
                    inst = instance_cls(shared)
                    inst.setName(f'{kind} Inst {n}')
                    inst.setSpaceType(space_type)
                    types.append(space_type)
                self.assertEqual(3, len(shared.instances()))
                setter(types[0], **kwargs)
                self.assertEqual(
                    2, len(shared.instances()),
                    'the written-to instance must have left the shared '
                    'definition')
                self.assertIsNone(
                    opt(getattr(shared, reader)()),
                    'and the shared definition must be UNCHANGED — before '
                    'the fix the value landed on it')

    def test_lighting_refuses_BEFORE_touching_the_model(self):
        """It raised after `single_instance` and `unshared_definition` had
        run, so a refused call left a new instance, a split definition and an
        audit entry behind. `set_people` and `set_internal_mass` raised
        cleanly; lighting now does too."""
        model, _original, types = self._shared(count=3)
        definitions_before = len(model.getLightsDefinitions())
        lights_before = len(model.getLightss())
        audit = AuditLog()
        with self.assertRaises(ValueError):
            Loads.set_lighting(types[0], watts_per_area_si=10.0,
                               watts_per_person=5.0, audit=audit)
        self.assertEqual(definitions_before,
                         len(model.getLightsDefinitions()),
                         'a refused call must not have split anything')
        self.assertEqual(lights_before, len(model.getLightss()))
        self.assertEqual([], audit.entries,
                         'nor left a trail of work it did not do')

    def test_an_UNSHARED_definition_is_not_renamed(self):
        """The NECB appliers call these setters, their definitions are already
        unique and carefully named, and renaming them would move every frozen
        baseline for no behavioural reason."""
        _model, space_type = _space_type()
        lights = Loads.set_lighting(space_type, watts_per_area_si=8.0)
        name = lights.lightsDefinition().nameString()
        Loads.set_lighting(space_type, watts_per_area_si=12.0)
        self.assertEqual(
            name, lights.lightsDefinition().nameString(),
            'an unshared definition keeps its name across a re-set')
        self.assertNotIn(':W-', name,
                         'the value-encoding name is for CLONES only')

    def test_equipment_and_people_split_too(self):
        import openstudio

        model = openstudio.model.Model()
        for kind, definition_cls, instance_cls, setter, kwargs in (
                ('equip', openstudio.model.ElectricEquipmentDefinition,
                 openstudio.model.ElectricEquipment,
                 Loads.set_electric_equipment, {'watts_per_area_si': 20.0}),
                ('people', openstudio.model.PeopleDefinition,
                 openstudio.model.People, Loads.set_people,
                 {'people_per_area_si': 0.1})):
            with self.subTest(kind):
                definition = definition_cls(model)
                definition.setName(f'Shared {kind}')
                types = []
                for n in range(2):
                    space_type = openstudio.model.SpaceType(model)
                    space_type.setName(f'{kind} Type {n}')
                    inst = instance_cls(definition)
                    inst.setSpaceType(space_type)
                    types.append(space_type)
                self.assertEqual(2, len(definition.instances()))
                setter(types[0], **kwargs)
                self.assertEqual(
                    1, len(definition.instances()),
                    'the written-to instance must have left the shared '
                    'definition')


@needs_sdk
class TestPeopleAndInternalMass(unittest.TestCase):
    """Lifted for #186 (People was already implicated by the Hangar) and at
    phylroy's request (InternalMass)."""

    def test_people_by_each_method(self):
        for kwarg, value, method, reader in (
                ('people_per_area_si', 0.1, 'People/Area',
                 'peopleperSpaceFloorArea'),
                ('number_of_people', 12.0, 'People', 'numberofPeople'),
                ('area_per_person_si', 9.3, 'Area/Person',
                 'spaceFloorAreaperPerson')):
            with self.subTest(kwarg):
                _model, space_type = _space_type()
                people = Loads.set_people(space_type, fraction_radiant=0.3,
                                          **{kwarg: value})
                definition = people.peopleDefinition()
                self.assertEqual(
                    method, definition.numberofPeopleCalculationMethod())
                self.assertAlmostEqual(value,
                                       opt(getattr(definition, reader)()))
                self.assertAlmostEqual(0.3, definition.fractionRadiant())

    def test_people_refuses_two_methods(self):
        _model, space_type = _space_type()
        with self.assertRaises(ValueError) as caught:
            Loads.set_people(space_type, people_per_area_si=0.1,
                             number_of_people=12.0)
        self.assertIn('ONE numberofPeopleCalculationMethod',
                      str(caught.exception))

    def test_internal_mass_by_each_method(self):
        for kwarg, value, reader in (
                ('surface_area_si', 40.0, 'surfaceArea'),
                ('per_floor_area_si', 2.5, 'surfaceAreaperSpaceFloorArea'),
                ('per_person_si', 3.5, 'surfaceAreaperPerson')):
            with self.subTest(kwarg):
                _model, space_type = _space_type()
                mass = Loads.set_internal_mass(space_type, **{kwarg: value})
                self.assertAlmostEqual(
                    value, opt(getattr(mass.internalMassDefinition(),
                                       reader)()))

    def test_internal_mass_takes_a_construction_OBJECT(self):
        """Building or choosing a construction belongs to
        `btap.modeling.envelope`, which already does it."""
        import openstudio

        model, space_type = _space_type()
        construction = openstudio.model.Construction(model)
        construction.setName('Mass Construction')
        mass = Loads.set_internal_mass(space_type, per_floor_area_si=2.0,
                                       construction=construction)
        self.assertEqual(
            construction.handle(),
            opt(mass.internalMassDefinition().construction()).handle())

    def test_internal_mass_refuses_two_methods(self):
        _model, space_type = _space_type()
        with self.assertRaises(ValueError):
            Loads.set_internal_mass(space_type, surface_area_si=40.0,
                                    per_floor_area_si=2.5)


@needs_sdk
class TestSingleInstance(unittest.TestCase):

    def test_a_duplicate_is_REMOVED_and_audited(self):
        """A space type carrying two infiltration objects is a model defect
        either way, and silently using one would make the applied value depend
        on object order."""
        import openstudio

        model, space_type = _space_type()
        for n in range(2):
            extra = openstudio.model.SpaceInfiltrationDesignFlowRate(model)
            extra.setName(f'Duplicate {n}')
            extra.setSpaceType(space_type)
        self.assertEqual(2, len(space_type.spaceInfiltrationDesignFlowRates()))

        audit = AuditLog()
        Loads.set_infiltration(space_type, air_changes_per_hour=0.4,
                               audit=audit)
        self.assertEqual(1, len(space_type.spaceInfiltrationDesignFlowRates()))
        self.assertTrue(
            any('removed duplicate load instance' in str(e.get('value') or
                                                         e.get('action') or '')
                for e in audit.entries),
            f'the removal must be audited; got {[e.get("action") for e in audit.entries]}')


@needs_sdk
class TestDeduplicateDefinitions(unittest.TestCase):
    """phylroy's design (2026-11-03): copy on write, then find the
    duplicates, keep the uniques and reassign. The companion to the split,
    and what makes splitting affordable."""

    @staticmethod
    def _shared_lights(model, count, watts=10.0):
        import openstudio

        definition = openstudio.model.LightsDefinition(model)
        definition.setName('Shared')
        definition.setWattsperSpaceFloorArea(watts)
        types = []
        for n in range(count):
            space_type = openstudio.model.SpaceType(model)
            space_type.setName(f'Type {n}')
            lights = openstudio.model.Lights(definition)
            lights.setName(f'Lights {n}')
            lights.setSpaceType(space_type)
            types.append(space_type)
        return types

    def test_the_round_trip_collapses_the_split(self):
        """Six sharers written to one value: six definitions on the way
        through, one on the way out, and every space type still reading the
        value it asked for."""
        import openstudio

        model = openstudio.model.Model()
        types = self._shared_lights(model, 6)
        for space_type in types:
            Loads.set_lighting(space_type, watts_per_area_si=25.0)
        self.assertEqual(6, len(model.getLightsDefinitions()),
                         'the split ran')

        removed = Loads.deduplicate_definitions(model)
        self.assertEqual(5, removed)
        self.assertEqual(1, len(model.getLightsDefinitions()))
        for space_type in types:
            self.assertAlmostEqual(
                25.0,
                opt(next(iter(space_type.lights())).lightsDefinition()
                    .wattsperSpaceFloorArea()),
                msg='and every space type still reads its value')

    def test_definitions_that_DIFFER_are_never_merged(self):
        """The property reuse-by-name could not hold: a field outside the
        dedupe key kept its own value. Here the densities agree and the
        radiant fractions do not."""
        model = __import__('openstudio').model.Model()
        types = self._shared_lights(model, 3)
        for space_type, radiant in zip(types, (0.3, 0.7, 0.1)):
            Loads.set_lighting(space_type, watts_per_area_si=25.0,
                               radiant=radiant)
        Loads.deduplicate_definitions(model)
        self.assertEqual(
            3, len(model.getLightsDefinitions()),
            'three distinct fraction sets are three distinct definitions')
        for space_type, radiant in zip(types, (0.3, 0.7, 0.1)):
            self.assertAlmostEqual(
                radiant,
                next(iter(space_type.lights())).lightsDefinition()
                .fractionRadiant())

    def test_a_differing_CALCULATION_METHOD_is_not_merged(self):
        model = __import__('openstudio').model.Model()
        types = self._shared_lights(model, 2)
        Loads.set_lighting(types[0], watts_per_area_si=10.0)
        Loads.set_lighting(types[1], watts_per_person=10.0)
        Loads.deduplicate_definitions(model)
        self.assertEqual(2, len(model.getLightsDefinitions()))

    def test_a_differing_CONSTRUCTION_is_not_merged(self):
        """Object references compare by handle, so two internal masses on
        different constructions stay apart even at the same area."""
        import openstudio

        model = openstudio.model.Model()
        kept = []
        for n in range(2):
            space_type = openstudio.model.SpaceType(model)
            space_type.setName(f'Mass Type {n}')
            construction = openstudio.model.Construction(model)
            construction.setName(f'Con {n}')
            Loads.set_internal_mass(space_type, per_floor_area_si=2.0,
                                    construction=construction)
            kept.append(space_type)
        Loads.deduplicate_definitions(model)
        self.assertEqual(2, len(model.getInternalMassDefinitions()))

    def test_it_merges_every_load_type_it_claims_to(self):
        import openstudio

        model = openstudio.model.Model()
        for setter, kwargs, getter in (
                (Loads.set_electric_equipment, {'watts_per_area_si': 8.0},
                 'getElectricEquipmentDefinitions'),
                (Loads.set_gas_equipment, {'watts_per_area_si': 9.0},
                 'getGasEquipmentDefinitions'),
                (Loads.set_people, {'people_per_area_si': 0.1},
                 'getPeopleDefinitions'),
                (Loads.set_internal_mass, {'per_floor_area_si': 2.0},
                 'getInternalMassDefinitions')):
            with self.subTest(getter):
                types = []
                for n in range(3):
                    space_type = openstudio.model.SpaceType(model)
                    space_type.setName(f'{getter} {n}')
                    types.append(space_type)
                    setter(space_type, **kwargs)
                before = len(getattr(model, getter)())
                self.assertEqual(3, before, 'one definition per space type')
                Loads.deduplicate_definitions(model)
                remaining = getattr(model, getter)()
                self.assertEqual(
                    1, len(remaining),
                    f'three identical {getter} definitions must become one')
                self.assertEqual(
                    3, len(remaining[0].instances()),
                    'and all three instances must point at the keeper')
                handles = {str(inst.definition().handle())
                           for inst in remaining[0].instances()}
                self.assertEqual(1, len(handles))
                del types

    def test_an_ORPHAN_definition_is_left_alone(self):
        """An orphan is not this function's business, and removing objects a
        caller may still hold is not a deduplication."""
        import openstudio

        model = openstudio.model.Model()
        for n in range(2):
            orphan = openstudio.model.LightsDefinition(model)
            orphan.setName(f'Orphan {n}')
            orphan.setWattsperSpaceFloorArea(12.0)
        self.assertEqual(0, Loads.deduplicate_definitions(model))
        self.assertEqual(2, len(model.getLightsDefinitions()))

    def test_the_merge_is_audited(self):
        model = __import__('openstudio').model.Model()
        types = self._shared_lights(model, 4)
        for space_type in types:
            Loads.set_lighting(space_type, watts_per_area_si=25.0)
        audit = AuditLog()
        Loads.deduplicate_definitions(model, audit=audit)
        merges = [e for e in audit.entries
                  if 'merged' in str(e.get('value') or e.get('action') or '')]
        self.assertEqual(1, len(merges))
        self.assertEqual(3, merges[0]['inputs']['removed'])
        self.assertEqual(3, merges[0]['inputs']['instances_reassigned'])


@needs_sdk
class TestNameOrderedSingleInstance(unittest.TestCase):
    """`single_instance` orders BY NAME. Both it and the NECB applier it came
    from used a plain `sorted()`, which is not name order on 3.11, so which
    duplicate survived depended on something other than the name."""

    def test_the_SURVIVOR_is_the_first_by_NAME(self):
        import openstudio

        model, space_type = _space_type()
        for name in ('Zebra Lights', 'Alpha Lights', 'Middle Lights'):
            definition = openstudio.model.LightsDefinition(model)
            definition.setName(name + ' Def')
            definition.setWattsperSpaceFloorArea(5.0)
            lights = openstudio.model.Lights(definition)
            lights.setName(name)
            lights.setSpaceType(space_type)
        self.assertEqual(3, len(space_type.lights()))

        Loads.set_lighting(space_type, watts_per_area_si=11.0)
        survivors = [light.nameString() for light in space_type.lights()]
        self.assertEqual(
            ['Alpha Lights'], survivors,
            'the first BY NAME survives; a plain sorted() kept Alpha here too '
            'but ordered the rest Zebra/Middle, so the survivor was not a '
            'property of the name')


@needs_sdk
class TestExteriorLights(unittest.TestCase):
    """A DIFFERENT class family: ExteriorLightsDefinition descends from
    ExteriorLoadDefinition, not SpaceLoadDefinition, so it has no space type
    and no `instances()`."""

    def test_it_creates_the_pair_with_daylight_control(self):
        import openstudio

        model = openstudio.model.Model()
        lights = Loads.set_exterior_lights(model, 1500.0, name='Yard Lights')
        self.assertEqual('Yard Lights', lights.nameString())
        self.assertEqual('AstronomicalClock', lights.controlOption())
        definition = lights.exteriorLightsDefinition()
        self.assertEqual('Yard Lights Definition', definition.nameString())
        self.assertAlmostEqual(1500.0, definition.designLevel())

    def test_the_default_control_is_NOT_the_SDK_default(self):
        """The SDK's own default is ScheduleNameOnly, so a lift that passed
        nothing would have turned the daylight control off."""
        import openstudio

        model = openstudio.model.Model()
        bare = openstudio.model.ExteriorLights(
            openstudio.model.ExteriorLightsDefinition(model))
        self.assertEqual('ScheduleNameOnly', bare.controlOption())
        self.assertEqual(
            'AstronomicalClock',
            Loads.set_exterior_lights(model, 10.0).controlOption())


@needs_sdk
class TestDemandControlledVentilation(unittest.TestCase):
    """Phase 0's fourth primitive, `ecm_dcv`, which had never been lifted."""

    @staticmethod
    def _loop_with_oa():
        import openstudio

        model = openstudio.model.Model()
        air_loop = openstudio.model.AirLoopHVAC(model)
        air_loop.setName('Probe Air Loop')
        controller = openstudio.model.ControllerOutdoorAir(model)
        oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(
            model, controller)
        oa_system.addToNode(air_loop.supplyInletNode())
        return model, air_loop

    def test_it_turns_dcv_on_and_sets_the_method(self):
        from btap.modeling.hvac import ventilation as Ventilation

        _model, air_loop = self._loop_with_oa()
        mech = Ventilation.set_demand_controlled_ventilation(
            air_loop, system_outdoor_air_method='ZoneSum')
        self.assertIsNotNone(mech)
        self.assertTrue(mech.demandControlledVentilation())
        self.assertEqual('ZoneSum', mech.systemOutdoorAirMethod())

    def test_the_method_is_LEFT_ALONE_when_not_given(self):
        from btap.modeling.hvac import ventilation as Ventilation

        _model, air_loop = self._loop_with_oa()
        before = Ventilation.set_demand_controlled_ventilation(
            air_loop, system_outdoor_air_method='ZoneSum'
        ).systemOutdoorAirMethod()
        after = Ventilation.set_demand_controlled_ventilation(
            air_loop).systemOutdoorAirMethod()
        self.assertEqual(before, after,
                         'choosing an outdoor-air method is a code question, '
                         'so the primitive must not pick one')

    def test_enabled_False_CLEARS_it(self):
        from btap.modeling.hvac import ventilation as Ventilation

        _model, air_loop = self._loop_with_oa()
        Ventilation.set_demand_controlled_ventilation(air_loop)
        mech = Ventilation.set_demand_controlled_ventilation(
            air_loop, enabled=False)
        self.assertFalse(mech.demandControlledVentilation())

    def test_a_loop_with_NO_outdoor_air_system_returns_None(self):
        """A recirculating loop has nowhere to carry the setting. That is not
        an error — DCV is meaningless on one — so it must not raise."""
        import openstudio

        from btap.modeling.hvac import ventilation as Ventilation

        model = openstudio.model.Model()
        air_loop = openstudio.model.AirLoopHVAC(model)
        air_loop.setName('No OA Loop')
        audit = AuditLog()
        self.assertIsNone(Ventilation.set_demand_controlled_ventilation(
            air_loop, audit=audit))
        self.assertTrue(
            any('not applicable' in str(e.get('value') or e.get('action') or '')
                for e in audit.entries),
            'and it says so in the trail')


if __name__ == '__main__':
    unittest.main()
