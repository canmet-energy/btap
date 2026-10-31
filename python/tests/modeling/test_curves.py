"""The defrost-EIR curve lookup must survive a foreign curve of the same name.

`defrost_eir_ft` used to find its curve by NAME and then cast the result,
which is an unguarded `.get()` on the Optional family that SEGFAULTS rather
than raising (see tests/test_sdk_invariants.py). A proposed model carrying a
curve called `DEFROST-EIR-FT` that is not a CurveBiquadratic killed the
interpreter. The tool accepts any OSM from any source, so that name belongs to
the input as much as to us.

Both halves are pinned here, because fixing only the crash leaks: filtering the
name lookup by type stops the segfault, and then the SDK's rename-on-collision
means the next call cannot find what the previous call built, so every call
adds another curve. The lookup is keyed on the BUILT_BY stamp for that reason.
"""

import unittest

from tests.support import needs_sdk


@needs_sdk
class TestDefrostCurveLookup(unittest.TestCase):

    @staticmethod
    def _model(*, collide):
        import openstudio
        model = openstudio.model.Model()
        foreign = None
        if collide:
            foreign = openstudio.model.CurveCubic(model)
            foreign.setName('DEFROST-EIR-FT')
        return model, foreign

    def test_a_foreign_curve_of_the_same_name_does_not_crash(self):
        """The regression itself. Before the fix this test KILLED the worker.

        Not "raised" — the process died with SIGSEGV, which is why it is worth
        a test of its own: a crash takes the whole xdist worker with it and
        reports as a lost node rather than a failure.
        """
        from btap.modeling.hvac.components import curves
        model, foreign = self._model(collide=True)
        self.assertFalse(
            foreign.to_CurveBiquadratic().is_initialized(),
            'precondition: the planted curve must NOT be a biquadratic, or '
            'this test cannot exercise the bad cast at all')

        curve = curves.defrost_eir_ft(model)
        self.assertTrue(curve.to_CurveBiquadratic().is_initialized())
        self.assertEqual('DEFROST-EIR-FT', foreign.nameString(),
                         'the foreign curve must be left alone')

    def test_the_lookup_is_idempotent_even_after_a_rename(self):
        """Keyed on the stamp, not the name — the name may not be ours.

        With a foreign holder of the name, the SDK renames ours on creation.
        A name-keyed lookup then misses it and builds another curve on every
        call, so this asserts the COUNT, not just that a curve comes back.
        """
        from btap.modeling.hvac.components import curves
        for collide in (False, True):
            with self.subTest(collide=collide):
                model, _ = self._model(collide=collide)
                handles = {curves.defrost_eir_ft(model).handle()
                           for _ in range(3)}
                self.assertEqual(
                    1, len(handles),
                    'three calls must return the SAME curve object')
                biquadratics = [c for c in model.getCurves()
                                if c.to_CurveBiquadratic().is_initialized()]
                self.assertEqual(
                    1, len(biquadratics),
                    'three calls built more than one curve — the lookup is '
                    'not finding what it previously created')

    def test_the_curve_it_builds_is_the_flat_one(self):
        """Guards the fix against a lookup that returns the wrong curve.

        The point of the curve is that defrost EIR is NOT modified by
        temperature: c1 = 1 and every other coefficient 0. A stamp-keyed
        lookup that matched the wrong stamped curve would still satisfy the
        two tests above.
        """
        from btap.modeling.hvac.components import curves
        model, _ = self._model(collide=True)
        curve = curves.defrost_eir_ft(model).to_CurveBiquadratic().get()
        self.assertEqual(1.0, curve.coefficient1Constant())
        for value in (curve.coefficient2x(), curve.coefficient3xPOW2(),
                      curve.coefficient4y(), curve.coefficient5yPOW2(),
                      curve.coefficient6xTIMESY()):
            self.assertEqual(0.0, value)


if __name__ == '__main__':
    unittest.main()
