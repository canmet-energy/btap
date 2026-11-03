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


if __name__ == '__main__':
    unittest.main()
