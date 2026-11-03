"""Fan and pump efficiency primitives (#192, cluster 1).

`canmet-energy/campus` carries three measures here and `btap.modeling` had no
setter for either quantity, while `btap.codes.necb` set both in five places.
"""

from __future__ import annotations

import unittest

from btap.audit import AuditLog
from btap.modeling.hvac import efficiency as Efficiency
from tests.support import needs_sdk


@needs_sdk
class TestTheClassSURFACE(unittest.TestCase):
    """The measured premise the primitive is built on. If 3.11 ever changes
    these, the primitive's branches are wrong and this test says so first."""

    def test_every_scalar_fan_takes_the_NEW_name(self):
        import openstudio

        model = openstudio.model.Model()
        for name in ('FanConstantVolume', 'FanVariableVolume', 'FanOnOff',
                     'FanSystemModel', 'FanZoneExhaust'):
            with self.subTest(name):
                fan = getattr(openstudio.model, name)(model)
                self.assertTrue(
                    hasattr(fan, 'setFanTotalEfficiency'),
                    'so the hasattr guard that fell back to the deprecated '
                    'setFanEfficiency was dead for this class')

    def test_FanComponentModel_has_NEITHER(self):
        """Which is what made the retired guard an AttributeError rather than
        a fallback: it was the only class to reach the else branch."""
        import openstudio

        model = openstudio.model.Model()
        fan = openstudio.model.FanComponentModel(model)
        self.assertFalse(hasattr(fan, 'setFanTotalEfficiency'))
        self.assertFalse(hasattr(fan, 'setFanEfficiency'))

    def test_FanZoneExhaust_has_no_MOTOR_efficiency(self):
        import openstudio

        model = openstudio.model.Model()
        fan = openstudio.model.FanZoneExhaust(model)
        self.assertTrue(hasattr(fan, 'setFanTotalEfficiency'))
        self.assertFalse(hasattr(fan, 'setMotorEfficiency'))


@needs_sdk
class TestSetFanEfficiency(unittest.TestCase):

    def test_both_fields_on_each_fan_that_has_them(self):
        import openstudio

        model = openstudio.model.Model()
        for name in ('FanConstantVolume', 'FanVariableVolume', 'FanOnOff',
                     'FanSystemModel'):
            with self.subTest(name):
                fan = getattr(openstudio.model, name)(model)
                fan.setName(f'{name} probe')
                self.assertEqual(
                    2, Efficiency.set_fan_efficiency(
                        fan, total_efficiency=0.55, motor_efficiency=0.82))
                self.assertAlmostEqual(0.55, fan.fanTotalEfficiency())
                self.assertAlmostEqual(0.82, fan.motorEfficiency())

    def test_a_curve_based_fan_is_REFUSED_with_its_own_surface_named(self):
        import openstudio

        model = openstudio.model.Model()
        fan = openstudio.model.FanComponentModel(model)
        with self.assertRaises(ValueError) as caught:
            Efficiency.set_fan_efficiency(fan, total_efficiency=0.6)
        message = str(caught.exception)
        self.assertIn('setMaximumMotorEfficiencyCurve', message)
        self.assertIn('FanComponentModel', message)

    def test_a_motor_efficiency_on_FanZoneExhaust_is_REFUSED(self):
        """Refused, not silently skipped: the caller asked for a field the
        object does not have, and quietly dropping it would report an upgrade
        that did not happen."""
        import openstudio

        model = openstudio.model.Model()
        fan = openstudio.model.FanZoneExhaust(model)
        with self.assertRaises(ValueError) as caught:
            Efficiency.set_fan_efficiency(fan, motor_efficiency=0.9)
        self.assertIn('no motor-efficiency field', str(caught.exception))
        self.assertEqual(
            1, Efficiency.set_fan_efficiency(fan, total_efficiency=0.6),
            'its total efficiency still works')

    def test_an_OUT_OF_RANGE_value_raises(self):
        import openstudio

        model = openstudio.model.Model()
        fan = openstudio.model.FanConstantVolume(model)
        with self.assertRaises(ValueError) as caught:
            Efficiency.set_fan_efficiency(fan, total_efficiency=1.4)
        self.assertIn('refused', str(caught.exception))

    def test_nothing_given_writes_nothing(self):
        import openstudio

        model = openstudio.model.Model()
        fan = openstudio.model.FanConstantVolume(model)
        before = fan.fanTotalEfficiency()
        self.assertEqual(0, Efficiency.set_fan_efficiency(fan))
        self.assertAlmostEqual(before, fan.fanTotalEfficiency())


@needs_sdk
class TestSetPumpEfficiency(unittest.TestCase):

    def test_each_pump_class(self):
        import openstudio

        model = openstudio.model.Model()
        for name in ('PumpConstantSpeed', 'PumpVariableSpeed',
                     'HeaderedPumpsConstantSpeed',
                     'HeaderedPumpsVariableSpeed'):
            with self.subTest(name):
                pump = getattr(openstudio.model, name)(model)
                self.assertEqual(
                    1, Efficiency.set_pump_efficiency(pump,
                                                      motor_efficiency=0.88))
                self.assertAlmostEqual(0.88, pump.motorEfficiency())


@needs_sdk
class TestModelWide(unittest.TestCase):
    """The retrofit shape: "every fan in this building is now a
    premium-efficiency motor"."""

    def test_it_reaches_every_scalar_fan(self):
        import openstudio

        model = openstudio.model.Model()
        fans = [openstudio.model.FanConstantVolume(model),
                openstudio.model.FanVariableVolume(model),
                openstudio.model.FanOnOff(model)]
        written = Efficiency.set_fan_efficiency_in_model(
            model, total_efficiency=0.6, motor_efficiency=0.9)
        self.assertEqual(6, written, 'two fields on each of three fans')
        for fan in fans:
            self.assertAlmostEqual(0.6, fan.fanTotalEfficiency())
            self.assertAlmostEqual(0.9, fan.motorEfficiency())

    def test_a_curve_based_fan_is_SKIPPED_and_warned_not_refused(self):
        """One detailed fan must not stop an upgrade to the other forty — but
        the trail has to say its performance did not change."""
        import openstudio

        model = openstudio.model.Model()
        plain = openstudio.model.FanConstantVolume(model)
        plain.setName('Plain Fan')
        detailed = openstudio.model.FanComponentModel(model)
        detailed.setName('Detailed Fan')
        audit = AuditLog()
        written = Efficiency.set_fan_efficiency_in_model(
            model, total_efficiency=0.6, audit=audit)
        self.assertEqual(1, written)
        self.assertAlmostEqual(0.6, plain.fanTotalEfficiency())
        warnings = [e for e in audit.entries if e.get('level') == 'warning']
        self.assertEqual(1, len(warnings))
        self.assertIn('Detailed Fan', warnings[0]['inputs']['skipped'])

    def test_FanZoneExhaust_takes_the_total_and_skips_the_motor(self):
        """Model-wide must not raise on a class that lacks the field, while a
        caller naming that fan explicitly still gets the refusal."""
        import openstudio

        model = openstudio.model.Model()
        fan = openstudio.model.FanZoneExhaust(model)
        written = Efficiency.set_fan_efficiency_in_model(
            model, total_efficiency=0.6, motor_efficiency=0.9)
        self.assertEqual(1, written, 'the total only')
        self.assertAlmostEqual(0.6, fan.fanTotalEfficiency())

    def test_pumps_model_wide(self):
        import openstudio

        model = openstudio.model.Model()
        pumps = [openstudio.model.PumpConstantSpeed(model),
                 openstudio.model.PumpVariableSpeed(model)]
        self.assertEqual(2, Efficiency.set_pump_efficiency_in_model(
            model, motor_efficiency=0.91))
        for pump in pumps:
            self.assertAlmostEqual(0.91, pump.motorEfficiency())

    def test_no_factor_given_is_a_no_op(self):
        import openstudio

        model = openstudio.model.Model()
        openstudio.model.PumpConstantSpeed(model)
        self.assertEqual(0, Efficiency.set_pump_efficiency_in_model(model))


if __name__ == '__main__':
    unittest.main()
