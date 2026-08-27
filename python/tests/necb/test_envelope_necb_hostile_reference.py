"""Hostile-outcome gate for the reference ENVELOPE air-leakage transform
(NECB 8.4.4.3.(6) via 8.4.3.3.(3) + 8.4.2.9.(2)).

Method: give the PROPOSED deliberately non-compliant infiltration, build the
reference, then assert the reference carries the NECB default and ONLY the
NECB default.

The subtlety this guards: OpenStudio models infiltration with three unrelated
object types — SpaceInfiltrationDesignFlowRate, ...EffectiveLeakageArea, and
...FlowCoefficient. A transform that clears one and adds its own leaves the
others in place, so the space ends up with the NECB default PLUS whatever the
proposed had. Object counts, not just the flow value, are the assertion that
catches it.

Port of btap-necb/test/test_envelope_necb_hostile_reference.rb.
"""

from __future__ import annotations

import unittest

from tests.necb.support import load_raw_fixture, needs_sdk

HDD = 3890  # Toronto Pearson
HOSTILE_FLOW_PER_AREA = 0.05  # m3/s.m2 — ~50x the NECB default
HOSTILE_ELA_CM2 = 5000.0


def build_reference(model):
    from btap.audit import AuditLog
    from btap.necb import envelope

    envelope.reference_envelope(model, vintage='2020', hdd=HDD, audit=AuditLog())
    return model


def hostile_design_flow_rate(space):
    import openstudio

    infiltration = openstudio.model.SpaceInfiltrationDesignFlowRate(space.model())
    infiltration.setName(f'{space.nameString()} HOSTILE DesignFlowRate')
    infiltration.setFlowperExteriorWallArea(HOSTILE_FLOW_PER_AREA)
    infiltration.setSpace(space)
    return infiltration


def hostile_effective_leakage_area(space):
    import openstudio

    ela = openstudio.model.SpaceInfiltrationEffectiveLeakageArea(space.model())
    ela.setName(f'{space.nameString()} HOSTILE EffectiveLeakageArea')
    ela.setEffectiveAirLeakageArea(HOSTILE_ELA_CM2)
    ela.setSpace(space)
    return ela


@needs_sdk
class TestNECBHostileReferenceEnvelope(unittest.TestCase):
    # Positive control: the transform demonstrably fires and replaces a hostile
    # DesignFlowRate. If this fails the harness is broken and the negative case
    # below proves nothing.
    def test_reference_replaces_hostile_design_flow_rate(self):
        model = load_raw_fixture()
        for space in model.getSpaces():
            hostile_design_flow_rate(space)
        build_reference(model)

        rates = model.getSpaceInfiltrationDesignFlowRates()
        self.assertTrue(rates, 'reference must define infiltration')
        self.assertFalse(any('HOSTILE' in r.nameString() for r in rates),
                         'the proposed infiltration objects must be replaced, not kept')

        for rate in rates:
            flow = rate.flowperExteriorWallArea()
            if not flow.is_initialized():
                continue

            self.assertNotAlmostEqual(
                HOSTILE_FLOW_PER_AREA, flow.get(), delta=1e-9,
                msg='reference retained the hostile proposed infiltration rate')

    # DEFECT #3 — reproduction.
    #
    # The earlier apply_air_leakage_default removed only
    # getSpaceInfiltrationDesignFlowRates. A proposed model expressing
    # infiltration as EffectiveLeakageArea kept that object AND gained the NECB
    # default, so the reference building leaked roughly twice — inflating
    # reference energy and making the proposed easier to pass.
    def test_reference_does_not_double_count_effective_leakage_area(self):
        model = load_raw_fixture()
        for space in model.getSpaces():
            hostile_effective_leakage_area(space)
        survivors_before = len(model.getSpaceInfiltrationEffectiveLeakageAreas())
        self.assertGreater(survivors_before, 0,
                           'precondition: the proposed has ELA infiltration')

        build_reference(model)

        self.assertEqual(
            [], list(model.getSpaceInfiltrationEffectiveLeakageAreas()),
            'DOUBLE-COUNTED INFILTRATION: the reference kept the proposed '
            f'SpaceInfiltrationEffectiveLeakageArea object(s) ({survivors_before} of '
            'them) AND added the NECB default DesignFlowRate on top. The reference '
            'building therefore leaks about twice, which inflates reference energy and '
            'makes the proposed easier to pass.')

    # Same defect, other representation. Kept separate so a partial fix that
    # handles only ELA still reports the remaining hole.
    def test_reference_does_not_double_count_flow_coefficient(self):
        import openstudio

        model = load_raw_fixture()
        for space in model.getSpaces():
            coefficient = openstudio.model.SpaceInfiltrationFlowCoefficient(space.model())
            coefficient.setName(f'{space.nameString()} HOSTILE FlowCoefficient')
            coefficient.setFlowCoefficient(0.1)
            coefficient.setSpace(space)

        build_reference(model)

        self.assertEqual(
            [], list(model.getSpaceInfiltrationFlowCoefficients()),
            'DOUBLE-COUNTED INFILTRATION: the reference kept the proposed '
            'SpaceInfiltrationFlowCoefficient object(s) and added the NECB default '
            'on top.')

    # Pin the formula itself so a fix to the object-clearing above cannot
    # quietly change the resulting rate. I_AGW = (5/75)^0.6 x I75 x S / A_AGW.
    def test_reference_infiltration_matches_the_i_agw_formula(self):
        from btap.necb.envelope import prescriptive as Prescriptive

        model = load_raw_fixture()
        build_reference(model)

        envelope_area = 0.0
        wall_area = 0.0
        for surface in model.getSurfaces():
            boundary = Prescriptive.boundary_of(surface)
            if boundary is None:
                continue

            envelope_area += surface.grossArea()
            if surface.surfaceType() == 'Wall' and boundary == 'outdoors':
                wall_area += surface.grossArea()
        expected = ((5.0 / 75.0) ** 0.60) * 1.50 * envelope_area / wall_area / 1000.0

        rates = model.getSpaceInfiltrationDesignFlowRates()
        self.assertTrue(rates)
        for rate in rates:
            self.assertTrue(rate.flowperExteriorWallArea().is_initialized(),
                            'reference infiltration must be set as flow per exterior '
                            'wall area')
            self.assertAlmostEqual(
                expected, rate.flowperExteriorWallArea().get(), delta=1e-9,
                msg='8.4.2.9.(2): I_AGW = (5/75)^0.6 x 1.50 x S / A_AGW')


if __name__ == '__main__':
    unittest.main()
