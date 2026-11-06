"""Issue #202 — fan design pressure rise is captured and applied.

Before this, a recipe carried fan EFFICIENCY but not pressure, so a rebuilt
fan took the builder's default instead of the building's own value. Measured
on `gagetown_coldlake_Office_pre-1960.osm`: CV supply fans 500 Pa -> 250 Pa
and unit-heater fans 250 Pa -> 49.82 Pa, with flow and operating hours
unchanged — directly a fan-power difference, and the largest remaining honest
gap in a recipe round trip once #200's source-model defect is accounted for.
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk


@needs_sdk
class TestFanPressureRiseAccessors(unittest.TestCase):
    """The per-class accessor table, which a duck-typed getattr would break."""

    def setUp(self):
        import openstudio

        self.os = openstudio
        self.model = openstudio.model.Model()
        self.sched = openstudio.model.ScheduleConstant(self.model)
        self.sched.setValue(1.0)

    def test_FanSystemModel_uses_a_DIFFERENT_accessor_and_is_still_read(self):
        """`FanSystemModel` spells it `designPressureRise`.

        A `getattr(fan, 'pressureRise')` would return nothing for it and skip
        the fan SILENTLY — which is the failure this table exists to prevent,
        and the same shape as the motor-efficiency trap already documented in
        `btap.stock.equipment._fans`.
        """
        from btap.modeling.hvac.efficiency import fan_pressure_rise

        fan = self.os.model.FanSystemModel(self.model)
        fan.setDesignPressureRise(612.5)

        self.assertFalse(hasattr(fan, 'pressureRise'),
                         'if this gains a pressureRise alias, the accessor '
                         'table can be simplified')
        self.assertAlmostEqual(612.5, fan_pressure_rise(fan), places=4)

    def test_the_scalar_classes_are_all_read(self):
        from btap.modeling.hvac.efficiency import fan_pressure_rise

        cases = (
            (self.os.model.FanConstantVolume(self.model, self.sched), 500.0),
            (self.os.model.FanVariableVolume(self.model, self.sched), 1000.0),
            (self.os.model.FanOnOff(self.model, self.sched), 300.0),
            (self.os.model.FanZoneExhaust(self.model), 125.0),
        )
        for fan, value in cases:
            with self.subTest(fan=type(fan).__name__):
                self.assertTrue(fan.setPressureRise(value))
                self.assertAlmostEqual(value, fan_pressure_rise(fan),
                                       places=4)

    def test_a_curve_based_fan_reads_as_None_rather_than_raising(self):
        """`FanComponentModel` carries pressure in curves. None is the honest
        answer; raising would make one detailed fan break a whole recipe."""
        from btap.modeling.hvac.efficiency import fan_pressure_rise

        fan = self.os.model.FanComponentModel(self.model)
        self.assertIsNone(fan_pressure_rise(fan))

    def test_setting_it_on_a_curve_based_fan_is_REFUSED(self):
        from btap.modeling.hvac.efficiency import set_fan_pressure_rise

        fan = self.os.model.FanComponentModel(self.model)
        with self.assertRaises(ValueError) as caught:
            set_fan_pressure_rise(fan, 500.0)
        self.assertIn('curves', str(caught.exception))

    def test_the_model_wide_applier_writes_every_scalar_fan(self):
        from btap.modeling.hvac.efficiency import fan_pressure_rise, set_fan_pressure_rise_in_model

        made = [self.os.model.FanConstantVolume(self.model, self.sched),
                self.os.model.FanOnOff(self.model, self.sched),
                self.os.model.FanZoneExhaust(self.model)]
        for fan in made:
            fan.setPressureRise(111.0)

        written = set_fan_pressure_rise_in_model(self.model, 450.0)

        self.assertEqual(len(made), written)
        for fan in made:
            with self.subTest(fan=fan.nameString()):
                self.assertAlmostEqual(450.0, fan_pressure_rise(fan),
                                       places=4)


@needs_sdk
class TestTheRecipeCarriesPressureRise(unittest.TestCase):

    def _model_with_mixed_fans(self):
        import openstudio

        model = openstudio.model.Model()
        sched = openstudio.model.ScheduleConstant(model)
        sched.setValue(1.0)
        for value in (500.0, 500.0, 100.0):
            openstudio.model.FanConstantVolume(model, sched).setPressureRise(
                value)
        return model

    def test_the_writer_captures_the_aggregate_and_its_spread(self):
        from btap.stock.equipment import equipment_section

        section = equipment_section(self._model_with_mixed_fans())
        pressure = section['fans']['fan_pressure_rise_pa']

        self.assertAlmostEqual(366.666667, pressure['value'], places=4)
        self.assertEqual(3, pressure['from']['objects'])
        self.assertAlmostEqual(100.0, pressure['from']['min'], places=4)
        self.assertAlmostEqual(500.0, pressure['from']['max'], places=4)

    def test_the_reader_APPLIES_it_rather_than_leaving_builder_defaults(self):
        from btap.audit import AuditLog
        from btap.modeling.hvac.efficiency import fan_pressure_rise
        from btap.stock.reader import _apply_equipment

        model = self._model_with_mixed_fans()
        recipe_fans = {'fans': {'fan_pressure_rise_pa': {'value': 275.0}}}
        applied, skipped = [], []
        _apply_equipment(model, recipe_fans, applied, skipped, AuditLog())

        for fan in model.getFanConstantVolumes():
            with self.subTest(fan=fan.nameString()):
                self.assertAlmostEqual(275.0, fan_pressure_rise(fan),
                                       places=4)
        self.assertTrue(any('pressure rise' in a for a in applied), applied)
