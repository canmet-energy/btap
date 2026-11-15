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

    def _model_with_two_classes(self):
        """CV fans at 500 Pa and an exhaust fan at 100 Pa.

        A GLOBAL average would give both 366.7 Pa — wrong for each. This is
        the shape that cost 138 GJ/yr before the per-class split.
        """
        import openstudio

        model = openstudio.model.Model()
        sched = openstudio.model.ScheduleConstant(model)
        sched.setValue(1.0)
        for _ in range(2):
            openstudio.model.FanConstantVolume(model, sched).setPressureRise(
                500.0)
        openstudio.model.FanZoneExhaust(model).setPressureRise(100.0)
        return model

    def test_the_writer_captures_pressure_PER_CLASS(self):
        from btap.stock.equipment import equipment_section

        section = equipment_section(self._model_with_two_classes())
        by_class = section['fans']['fan_pressure_rise_pa_by_class']

        self.assertAlmostEqual(
            500.0, by_class['FanConstantVolume']['value'], places=4)
        self.assertAlmostEqual(
            100.0, by_class['FanZoneExhaust']['value'], places=4)
        self.assertNotIn(
            'fan_pressure_rise_pa', section['fans'],
            'the global scalar is replaced, not emitted alongside — two '
            'sources of truth would let a reader apply the wrong one')

    def test_a_GLOBAL_average_would_be_wrong_for_BOTH_classes(self):
        """The measurement behind #202's reopening, in miniature.

        Fan power is flow-weighted, so averaging 500 and 100 to 366.7 drops
        the fans that move the air and raises the ones that do not.
        """
        from btap.stock.equipment import equipment_section

        by_class = (equipment_section(self._model_with_two_classes())
                    ['fans']['fan_pressure_rise_pa_by_class'])
        global_mean = (500.0 + 500.0 + 100.0) / 3

        for name, expected in (('FanConstantVolume', 500.0),
                               ('FanZoneExhaust', 100.0)):
            with self.subTest(fan_class=name):
                self.assertAlmostEqual(expected, by_class[name]['value'],
                                       places=4)
                self.assertNotAlmostEqual(global_mean,
                                          by_class[name]['value'], places=1)

    def test_the_reader_applies_each_class_its_own_value(self):
        from btap.audit import AuditLog
        from btap.modeling.hvac.efficiency import fan_pressure_rise
        from btap.stock.reader import _apply_equipment

        model = self._model_with_two_classes()
        recipe = {'fans': {'fan_pressure_rise_pa_by_class': {
            'FanConstantVolume': {'value': 480.0},
            'FanZoneExhaust': {'value': 120.0}}}}
        applied, skipped = [], []
        _apply_equipment(model, recipe, applied, skipped, AuditLog())

        for fan in model.getFanConstantVolumes():
            self.assertAlmostEqual(480.0, fan_pressure_rise(fan), places=4)
        for fan in model.getFanZoneExhausts():
            self.assertAlmostEqual(120.0, fan_pressure_rise(fan), places=4)
        self.assertTrue(any('per class' in a for a in applied), applied)

    def test_a_class_the_recipe_does_NOT_mention_is_left_alone(self):
        """Absence is not an instruction. Defaulting it would be the silent
        widening the split exists to avoid."""
        from btap.audit import AuditLog
        from btap.modeling.hvac.efficiency import fan_pressure_rise
        from btap.stock.reader import _apply_equipment

        model = self._model_with_two_classes()
        before = [fan_pressure_rise(f) for f in model.getFanZoneExhausts()]
        recipe = {'fans': {'fan_pressure_rise_pa_by_class': {
            'FanConstantVolume': {'value': 480.0}}}}
        _apply_equipment(model, recipe, [], [], AuditLog())

        after = [fan_pressure_rise(f) for f in model.getFanZoneExhausts()]
        self.assertEqual(before, after)

    def test_an_OLD_recipe_with_one_scalar_still_builds_and_WARNS(self):
        """A pre-#202-split recipe must not break — but must say it is lossy."""
        from btap.audit import AuditLog
        from btap.modeling.hvac.efficiency import fan_pressure_rise
        from btap.stock.reader import _apply_equipment

        model = self._model_with_two_classes()
        audit = AuditLog()
        _apply_equipment(model, {'fans': {'fan_pressure_rise_pa':
                                          {'value': 275.0}}},
                         [], [], audit)

        for fan in model.getFanConstantVolumes():
            self.assertAlmostEqual(275.0, fan_pressure_rise(fan), places=4)
        self.assertTrue(
            any('pre-#202 shape' in e['action'] for e in audit.warnings),
            [e['action'] for e in audit.warnings])

    def test_an_unknown_fan_class_is_REFUSED(self):
        from btap.modeling.hvac.efficiency import set_fan_pressure_rise_by_class_in_model

        with self.assertRaises(ValueError) as caught:
            set_fan_pressure_rise_by_class_in_model(
                self._model_with_two_classes(), {'FanTurboEncabulator': 400.0})
        self.assertIn('FanTurboEncabulator', str(caught.exception))
