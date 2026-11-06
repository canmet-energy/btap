"""The economizer's LIMITS have to survive the round trip, not just its type.

#219. `controls.py::_economizers` has always recorded six fields per air loop —
the control type, the action type and four limits — and `reader.py` passed only
the control type to a primitive that already accepted the rest. Measured on
`Office_pre-1960`:

    MaximumLimitDryBulbTemperature    source 19.0 C   regenerated 28.0 C
    MaximumLimitDewpointTemperature   source  0.0 C   regenerated unset

A dry-bulb economizer whose high-limit shutoff moves from 19 C to 28 C gives
the regenerated building free cooling across a 9 K band of outdoor
temperature that the real building does not have, displacing mechanical
cooling.

**`tests/stock/test_round_trip.py::test_the_economizer_and_dcv_come_back`
passed throughout.** It asserts on `self.recipe`, so it pins the WRITER, which
was always correct. Its class is `TestEverySetValueIsReadBack` and "read back"
there means model -> recipe. Nothing asserted on what the READER put into a
model, which is the direction this file covers.
"""
import unittest

from btap._compat import opt
from btap.stock import build_from_recipe, write_recipe
from tests.stock.test_round_trip import KNOWN, _build
from tests.support import needs_sdk


@needs_sdk
class TestTheLimitsReachTheRebuiltModel(unittest.TestCase):
    """Through `build_from_recipe`, the public entry point, not the helper.

    Three guards shipped in this session that nothing invoked, because each was
    verified by calling it directly. The economizer block sits inside
    `_apply_controls`; exercising it from `build_from_recipe` is what proves a
    real caller reaches it.
    """

    @classmethod
    def setUpClass(cls):
        import openstudio

        cls.recipe = write_recipe(_build())
        cls.model = openstudio.model.Model()
        loop = openstudio.model.AirLoopHVAC(cls.model)
        oa = openstudio.model.AirLoopHVACOutdoorAirSystem(
            cls.model, openstudio.model.ControllerOutdoorAir(cls.model))
        oa.addToNode(loop.supplyInletNode())
        cls.result = build_from_recipe(cls.recipe, cls.model)
        cls.controller = oa.getControllerOutdoorAir()

    def test_the_control_type_comes_back(self):
        self.assertEqual('DifferentialDryBulb',
                         self.controller.getEconomizerControlType())

    def test_the_high_limit_drybulb_comes_back(self):
        """The field whose loss was measured at 9 K."""
        self.assertAlmostEqual(
            KNOWN['economizer_max_drybulb_c'],
            opt(self.controller
                .getEconomizerMaximumLimitDryBulbTemperature()))

    def test_the_applied_line_REPORTS_the_limits(self):
        lines = [line for line in self.result['applied']
                 if 'economizer' in line]
        self.assertTrue(lines, 'nothing reported an economizer')
        self.assertIn('limit', lines[0],
                      f'the audit line hides the limits: {lines[0]!r}')


@needs_sdk
class TestAnAbsentLimitStaysAbsent(unittest.TestCase):
    """A limit the source never set must not be applied as a number.

    The writer records an unset limit through `opt()`, so it reaches the recipe
    as null. Coercing that to 0.0 would be worse than dropping it: a 0 C
    high-limit dewpoint shuts the economizer off in most weather, which is a
    silent control change rather than a missing one.
    """

    def test_a_null_limit_is_not_applied(self):
        import openstudio

        recipe = write_recipe(_build())
        row = recipe['controls']['economizers']['by_air_loop'][0]
        row['economizer_maximum_limit_dewpoint_temperature'] = None

        model = openstudio.model.Model()
        loop = openstudio.model.AirLoopHVAC(model)
        oa = openstudio.model.AirLoopHVACOutdoorAirSystem(
            model, openstudio.model.ControllerOutdoorAir(model))
        oa.addToNode(loop.supplyInletNode())
        build_from_recipe(recipe, model)

        controller = oa.getControllerOutdoorAir()
        self.assertFalse(
            controller.getEconomizerMaximumLimitDewpointTemperature(
                ).is_initialized(),
            'a null limit was applied as a number')

    def test_a_present_limit_is_still_applied_alongside_a_null_one(self):
        """The control for the test above: proving the null was skipped is only
        meaningful if the others still land."""
        import openstudio

        recipe = write_recipe(_build())
        row = recipe['controls']['economizers']['by_air_loop'][0]
        row['economizer_maximum_limit_dewpoint_temperature'] = None

        model = openstudio.model.Model()
        loop = openstudio.model.AirLoopHVAC(model)
        oa = openstudio.model.AirLoopHVACOutdoorAirSystem(
            model, openstudio.model.ControllerOutdoorAir(model))
        oa.addToNode(loop.supplyInletNode())
        build_from_recipe(recipe, model)

        self.assertAlmostEqual(
            KNOWN['economizer_max_drybulb_c'],
            opt(oa.getControllerOutdoorAir()
                .getEconomizerMaximumLimitDryBulbTemperature()))


@needs_sdk
class TestAPopulatedTargetIsNotLeftAlone(unittest.TestCase):
    """The case the first version of these tests could not see.

    Astra's review: "If the target already carries a limit, an observed unset
    source limit leaves that target value in place. The new tests start with an
    unset target, so they do not establish the claim on a populated target.
    This requires distinguishing **unset this field** from **do not touch this
    field**."

    It was right. Skipping a None preserves absence only when the target had
    nothing there; rebuilding onto a populated model left the target's own
    limit standing as though the source had declared it. A recipe is a
    reconstruction, so `reader.py` now passes `reset_omitted=True`.
    """

    def _target_with_limits(self):
        import openstudio

        model = openstudio.model.Model()
        loop = openstudio.model.AirLoopHVAC(model)
        controller = openstudio.model.ControllerOutdoorAir(model)
        # a target carrying limits of its OWN, which the source does not have
        controller.setEconomizerMaximumLimitDewpointTemperature(11.0)
        controller.setEconomizerMaximumLimitEnthalpy(51000.0)
        oa = openstudio.model.AirLoopHVACOutdoorAirSystem(model, controller)
        oa.addToNode(loop.supplyInletNode())
        return model, oa

    def test_a_limit_the_SOURCE_lacks_is_cleared_from_the_target(self):
        recipe = write_recipe(_build())
        row = recipe['controls']['economizers']['by_air_loop'][0]
        row['economizer_maximum_limit_dewpoint_temperature'] = None

        model, oa = self._target_with_limits()
        controller = oa.getControllerOutdoorAir()
        self.assertTrue(
            controller.getEconomizerMaximumLimitDewpointTemperature(
                ).is_initialized(),
            'fixture should start POPULATED or it proves nothing')

        build_from_recipe(recipe, model)

        self.assertFalse(
            oa.getControllerOutdoorAir()
            .getEconomizerMaximumLimitDewpointTemperature().is_initialized(),
            "the target kept its own limit, so the rebuilt model claims a "
            'limit the source building does not have')

    def test_a_limit_the_source_HAS_still_overwrites_the_target(self):
        """The control. Clearing omitted limits must not stop declared ones
        landing on a target that already had a different value."""
        recipe = write_recipe(_build())
        model, oa = self._target_with_limits()
        build_from_recipe(recipe, model)
        self.assertAlmostEqual(
            KNOWN['economizer_max_drybulb_c'],
            opt(oa.getControllerOutdoorAir()
                .getEconomizerMaximumLimitDryBulbTemperature()))


if __name__ == '__main__':
    unittest.main()
