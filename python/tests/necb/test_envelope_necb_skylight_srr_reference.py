"""P4 gate: the reference-envelope SKYLIGHT/SRR path (8.4.4.3.(3) via
3.2.1.4.(2)) — HAS NEVER EXECUTED anywhere in this suite before this file. The
shared 5-zone fixture has no skylights, and test_envelope_reference_envelope's
``proposed_model`` helper (despite a now-fixed stale comment claiming
otherwise) never created one either, so ``scale_fenestration_to_limits``'s
roof-scaling branch in envelope/reference.py had zero test coverage.

Method mirrors test_fdwr_scaled_proportionally_not_rebuilt: build a hostile
proposed SRR, run the reference transform, assert MODEL VALUES (skylight
area/SRR), never audit text.

Port of btap-necb/test/test_envelope_necb_skylight_srr_reference.rb.
"""

from __future__ import annotations

import unittest

from tests.necb.support import load_raw_fixture, needs_sdk

HDD = 3890
SRR_LIMIT = 0.02  # 3.2.1.4.(2): total skylight area < 2% of gross roof area


def model_with_skylights(srr):
    """Add one skylight per exposed conditioned roof at the given SRR, via the
    SAME centroid-scaled-subsurface geometry the PRESCRIPTIVE path uses
    (Fenestration.apply_srr). This is a FIXTURE BUILDER call, not the code
    under test: the reference transform under test
    (scale_fenestration_to_limits) shrinks EXISTING subsurfaces via
    Geometry.scale_subsurfaces — it never calls apply_srr, which only the
    prescriptive path uses to ADD skylights."""
    import openstudio

    from btap.necb.envelope import fenestration as Fenestration

    model = load_raw_fixture()
    glazing = openstudio.model.SimpleGlazing(model)
    glazing.setUFactor(3.0)
    glazing.setSolarHeatGainCoefficient(0.5)
    glazing.setVisibleTransmittance(0.6)
    construction = openstudio.model.Construction(model)
    construction.setName('Proposed Skylight Construction')
    construction.setLayers([glazing])
    ok = Fenestration.apply_srr(model, srr, construction)
    if not ok:
        raise RuntimeError('fixture builder failed to add skylights')

    return model


def reference(model):
    from btap.audit import AuditLog
    from btap.necb import envelope

    audit = AuditLog()
    envelope.reference_envelope(model, vintage='2020', hdd=HDD, audit=audit)
    return audit


@needs_sdk
class TestNECBSkylightSRRReference(unittest.TestCase):
    # Positive control + the reproduction in one call: the proposed model
    # actually HAS a skylight (unlike every other fixture in this repo), its
    # SRR is 5x the 2% cap, and the reference transform's roof-scaling branch
    # fires for the first time in any test.
    def test_reference_shrinks_hostile_skylight_to_the_srr_limit(self):
        from btap.modeling.envelope import geometry as Geometry

        model = model_with_skylights(0.10)
        before_roofs = Geometry.exposed_roofs(model)
        before_sub_area = before_roofs['subsurface_area_m2']
        before_walls = Geometry.exposed_walls(model)
        before_window_area = before_walls['subsurface_area_m2']
        before_window_count = sum(1 for s in model.getSubSurfaces()
                                  if s.subSurfaceType() != 'Skylight')
        self.assertGreater(before_roofs['srr'], SRR_LIMIT,
                           'fixture precondition: proposed SRR exceeds the limit')

        reference(model)

        after_roofs = Geometry.exposed_roofs(model)
        ratio = SRR_LIMIT / before_roofs['srr']
        self.assertAlmostEqual(
            before_sub_area * ratio, after_roofs['subsurface_area_m2'], delta=1e-3,
            msg='skylight area must shrink by exactly limit/proposed_srr (8.4.4.3.(3))')
        self.assertAlmostEqual(SRR_LIMIT, after_roofs['srr'], delta=1e-4,
                               msg='resulting SRR must land at the 2% cap')
        self.assertLessEqual(after_roofs['srr'], SRR_LIMIT + 1e-6)

        after_walls = Geometry.exposed_walls(model)
        self.assertAlmostEqual(
            before_window_area, after_walls['subsurface_area_m2'], delta=1e-6,
            msg='wall windows must be untouched by the roof-only SRR scaling')
        self.assertEqual(before_window_count,
                         sum(1 for s in model.getSubSurfaces()
                             if s.subSurfaceType() != 'Skylight'),
                         'wall window count untouched')

    # Negative case: SRR already within the limit -> the roof-scaling branch
    # must not fire at all (reference.py: `if not (roofs["srr"] is not None and
    # roofs["srr"] > srr_limit): return`) — skylight geometry byte-identical,
    # not merely "close".
    def test_reference_leaves_compliant_skylight_byte_identical(self):
        model = model_with_skylights(0.01)  # half the cap
        before = {r.nameString(): [ss.grossArea() for ss in r.subSurfaces()]
                  for r in model.getSurfaces() if r.surfaceType() == 'RoofCeiling'}
        self.assertTrue(any(a > 0 for areas in before.values() for a in areas),
                        'fixture precondition: skylights actually present')

        reference(model)

        after = {r.nameString(): [ss.grossArea() for ss in r.subSurfaces()]
                 for r in model.getSurfaces() if r.surfaceType() == 'RoofCeiling'}
        self.assertEqual(before, after,
                         'SRR under the limit: skylight areas must be byte-identical, '
                         'not scaled')


if __name__ == '__main__':
    unittest.main()
