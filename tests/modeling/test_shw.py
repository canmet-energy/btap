"""Service-water primitives (#192, cluster 3).

`btap.modeling` had nothing: `hvac/classify.py:299` reads
`to_WaterHeaterMixed()` for fuel classification only. `btap.codes.necb` set
all three quantities in `shw/efficiency.py`, so the plant half is a lift.
"""

from __future__ import annotations

import unittest

from btap._compat import opt
from btap.audit import AuditLog
from btap.modeling import loads as Loads
from btap.modeling import shw as Shw
from tests.support import needs_sdk


@needs_sdk
class TestTheTwoHeaterClassesDIFFER(unittest.TestCase):
    """Measured premise. The campus measure reaches for the mixed setters with
    `getattr(heater, name, None)` and skips a stratified heater silently; this
    records WHY that is not a missing field but a different loss model."""

    def test_both_carry_thermal_efficiency(self):
        import openstudio

        model = openstudio.model.Model()
        for name in ('WaterHeaterMixed', 'WaterHeaterStratified'):
            with self.subTest(name):
                heater = getattr(openstudio.model, name)(model)
                self.assertTrue(hasattr(heater, 'setHeaterThermalEfficiency'))

    def test_only_MIXED_carries_the_UA_pair(self):
        import openstudio

        model = openstudio.model.Model()
        mixed = openstudio.model.WaterHeaterMixed(model)
        strat = openstudio.model.WaterHeaterStratified(model)
        for setter in ('setOffCycleLossCoefficienttoAmbientTemperature',
                       'setOnCycleLossCoefficienttoAmbientTemperature'):
            self.assertTrue(hasattr(mixed, setter))
            self.assertFalse(hasattr(strat, setter), setter)

    def test_stratified_parameterises_loss_PER_UNIT_AREA(self):
        """Which is why a mixed-tank UA in W/K is not the same quantity."""
        import openstudio

        model = openstudio.model.Model()
        strat = openstudio.model.WaterHeaterStratified(model)
        self.assertTrue(hasattr(
            strat, 'setUniformSkinLossCoefficientperUnitAreatoAmbient'
                   'Temperature'))
        self.assertTrue(hasattr(
            strat, 'setOffCycleFlueLossCoefficienttoAmbientTemperature'))


@needs_sdk
class TestWaterHeaterEfficiency(unittest.TestCase):

    def test_it_sets_both_classes(self):
        import openstudio

        model = openstudio.model.Model()
        for name in ('WaterHeaterMixed', 'WaterHeaterStratified'):
            with self.subTest(name):
                heater = getattr(openstudio.model, name)(model)
                self.assertEqual(1, Shw.set_water_heater_efficiency(
                    heater, thermal_efficiency=0.82))
                self.assertAlmostEqual(0.82, heater.heaterThermalEfficiency()
                                       if name == 'WaterHeaterStratified'
                                       else opt(
                                           heater.heaterThermalEfficiency()))

    def test_nothing_given_writes_nothing(self):
        import openstudio

        model = openstudio.model.Model()
        heater = openstudio.model.WaterHeaterMixed(model)
        self.assertEqual(0, Shw.set_water_heater_efficiency(heater))

    def test_the_SDK_bound_is_greater_than_zero_not_zero_to_one(self):
        """Measured on 3.11, and my first version of this test assumed
        otherwise: `setHeaterThermalEfficiency` ACCEPTS 1.6 and refuses 0.0
        and negatives."""
        import openstudio

        model = openstudio.model.Model()
        heater = openstudio.model.WaterHeaterMixed(model)
        self.assertTrue(heater.setHeaterThermalEfficiency(1.6))
        self.assertFalse(heater.setHeaterThermalEfficiency(0.0))
        self.assertFalse(heater.setHeaterThermalEfficiency(-0.1))

        with self.assertRaises(ValueError) as caught:
            Shw.set_water_heater_efficiency(heater, thermal_efficiency=0.0)
        self.assertIn('greater than zero', str(caught.exception))

    def test_a_PERCENTAGE_mistake_is_warned_not_refused(self):
        """82 instead of 0.82 is accepted by the SDK, so it has to be
        surfaced — but a bound the SDK does not enforce is not this
        primitive's to invent."""
        import openstudio

        model = openstudio.model.Model()
        heater = openstudio.model.WaterHeaterMixed(model)
        audit = AuditLog()
        self.assertEqual(1, Shw.set_water_heater_efficiency(
            heater, thermal_efficiency=82.0, audit=audit))
        warnings = [e for e in audit.entries if e.get('level') == 'warning']
        self.assertEqual(1, len(warnings))
        self.assertIn('percentage', str(warnings[0].get('value')
                                        or warnings[0].get('action') or ''))

    def test_no_warning_for_a_normal_efficiency(self):
        import openstudio

        model = openstudio.model.Model()
        heater = openstudio.model.WaterHeaterMixed(model)
        audit = AuditLog()
        Shw.set_water_heater_efficiency(heater, thermal_efficiency=0.82,
                                        audit=audit)
        self.assertEqual([], [e for e in audit.entries
                              if e.get('level') == 'warning'])


@needs_sdk
class TestWaterHeaterLosses(unittest.TestCase):

    def test_one_UA_lands_on_both_coefficients(self):
        """One value for both, which is what a standby-loss standard gives:
        it measures the tank at rest and does not distinguish the two."""
        import openstudio

        model = openstudio.model.Model()
        heater = openstudio.model.WaterHeaterMixed(model)
        self.assertEqual(2, Shw.set_water_heater_losses(heater,
                                                        ua_w_per_k=1.8))
        self.assertAlmostEqual(
            1.8, opt(heater.offCycleLossCoefficienttoAmbientTemperature()))
        self.assertAlmostEqual(
            1.8, opt(heater.onCycleLossCoefficienttoAmbientTemperature()))

    def test_a_STRATIFIED_tank_is_refused_with_its_own_fields_named(self):
        import openstudio

        model = openstudio.model.Model()
        strat = openstudio.model.WaterHeaterStratified(model)
        with self.assertRaises(ValueError) as caught:
            Shw.set_water_heater_losses(strat, ua_w_per_k=1.8)
        message = str(caught.exception)
        self.assertIn('per unit area', message)
        self.assertIn('setUniformSkinLossCoefficientperUnitArea', message)

    def test_scaling_leaves_an_UNSPECIFIED_coefficient_alone(self):
        """Scaling an absent value would write a 0.0 that reads as a
        perfectly insulated tank."""
        import openstudio

        model = openstudio.model.Model()
        heater = openstudio.model.WaterHeaterMixed(model)
        heater.resetOffCycleLossCoefficienttoAmbientTemperature()
        heater.setOnCycleLossCoefficienttoAmbientTemperature(2.0)
        audit = AuditLog()
        self.assertEqual(
            1, Shw.scale_water_heater_losses(heater, factor=0.7, audit=audit))
        self.assertIsNone(
            opt(heater.offCycleLossCoefficienttoAmbientTemperature()),
            'still unspecified, NOT a scaled zero')
        self.assertAlmostEqual(
            1.4, opt(heater.onCycleLossCoefficienttoAmbientTemperature()))
        self.assertTrue(any(e.get('level') == 'warning'
                            for e in audit.entries))

    def test_scaling_both(self):
        import openstudio

        model = openstudio.model.Model()
        heater = openstudio.model.WaterHeaterMixed(model)
        Shw.set_water_heater_losses(heater, ua_w_per_k=2.0)
        self.assertEqual(2, Shw.scale_water_heater_losses(heater, factor=0.5))
        self.assertAlmostEqual(
            1.0, opt(heater.offCycleLossCoefficienttoAmbientTemperature()))


@needs_sdk
class TestLowFlowFixtures(unittest.TestCase):
    """`install_low_flow_fixtures`. Its own description names #186's hazard:
    it scales each definition ONCE even when several equipment objects share
    it."""

    @staticmethod
    def _fixtures(model, count, flow=0.0001, shared=True):
        """Attached to a SPACE, not a space type.

        `SpaceType` exposes eleven load accessors and `waterUseEquipment` is
        NOT among them, while `Space` has it — an SDK asymmetry. The first
        version of this fixture used a space type by analogy with the lighting
        tests and failed with `'SpaceType' object has no attribute
        'waterUseEquipment'`.
        """
        import openstudio

        space = openstudio.model.Space(model)
        space.setName('Washroom')
        definition = None
        for n in range(count):
            if definition is None or not shared:
                definition = openstudio.model.WaterUseEquipmentDefinition(
                    model)
                definition.setName(f'Lavatory Def {n}')
                definition.setPeakFlowRate(flow)
            equip = openstudio.model.WaterUseEquipment(definition)
            equip.setName(f'Lavatory {n}')
            equip.setSpace(space)
        return space

    def test_a_shared_definition_is_scaled_ONCE(self):
        import openstudio

        model = openstudio.model.Model()
        space = self._fixtures(model, 3)
        self.assertEqual(1, Loads.scale_water_use(space, factor=0.7))
        definition = next(iter(space.waterUseEquipment())) \
            .waterUseEquipmentDefinition()
        self.assertAlmostEqual(0.00007, definition.peakFlowRate(), places=7,
                               msg='0.7x once, not 0.343x')

    def test_the_name_FILTER_targets_one_family(self):
        """How the measure upgrades lavatories but not showers."""
        import openstudio

        model = openstudio.model.Model()
        self._fixtures(model, 1)
        shower_def = openstudio.model.WaterUseEquipmentDefinition(model)
        shower_def.setName('Shower Def')
        shower_def.setPeakFlowRate(0.0002)
        shower = openstudio.model.WaterUseEquipment(shower_def)
        shower.setName('Shower 0')

        self.assertEqual(1, Loads.scale_water_use_in_model(
            model, factor=0.5, name_contains='Lavatory'))
        self.assertAlmostEqual(0.0002, shower_def.peakFlowRate(), places=7,
                               msg='the shower was not asked to change')

    def test_no_match_is_reported_not_silent(self):
        import openstudio

        model = openstudio.model.Model()
        self._fixtures(model, 1)
        audit = AuditLog()
        self.assertEqual(0, Loads.scale_water_use_in_model(
            model, factor=0.5, name_contains='Bidet', audit=audit))
        self.assertTrue(any('no water-use equipment matched'
                            in str(e.get('value') or e.get('action') or '')
                            for e in audit.entries))


if __name__ == '__main__':
    unittest.main()
