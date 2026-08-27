"""P4 gate: the greenfield reference-envelope transform (8.4.4.3/8.4.4.4) —
golden assertions on scaling, absorptance, shading census, lightweight
rebuild, air leakage arithmetic, coverage emission; E2E clean E+ run;
composition smoke with the hvac domain (one clone, one audit).

Port of btap-necb/test/test_envelope_reference_envelope.rb.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.necb.support import DDY, EPW, load_raw_fixture, needs_sdk
from tests.support import needs_engine

HDD = 3890
# 3.2.1.4.(1): hdd <= 4000 -> flat 0.40 (linear piece starts above 4000)
FDWR_LIMIT = 0.40


def proposed_model():
    """A "proposed" model: oversized windows + both kinds of shading.

    NOTE (was STALE): this comment used to claim a "skylight" was built here
    too, but the method below never created one — the SRR/skylight reference
    path (scale_fenestration_to_limits's roof-scaling branch in
    envelope/reference.py) had ZERO test coverage in this suite as a result.
    That path is now covered separately in
    test_envelope_necb_skylight_srr_reference.py, which builds its own
    hostile-SRR fixture; this proposed_model deliberately stays skylight-free
    so the FDWR/shading/absorptance/air-leakage tests below are unaffected."""
    import openstudio

    model = load_raw_fixture()
    walls = [s for s in model.getSurfaces()
             if s.outsideBoundaryCondition() == 'Outdoors' and s.surfaceType() == 'Wall']
    for w in walls:
        w.setWindowToWallRatio(0.6)

    space_shading = openstudio.model.ShadingSurfaceGroup(model)
    space_shading.setShadingSurfaceType('Building')
    space_shading.setName('Overhangs')
    site_shading = openstudio.model.ShadingSurfaceGroup(model)
    site_shading.setShadingSurfaceType('Site')
    site_shading.setName('Neighbour building')
    return model


def reference(model, **kwargs):
    from btap.audit import AuditLog
    from btap.necb import envelope

    audit = AuditLog()
    envelope.reference_envelope(model, vintage='2020', hdd=HDD, audit=audit, **kwargs)
    return audit


def hostile_roof_absorptance(model, value):
    import openstudio

    for s in model.getSurfaces():
        if not (s.surfaceType() == 'RoofCeiling'
                and s.outsideBoundaryCondition() == 'Outdoors'):
            continue
        outer = s.construction().get().to_Construction().get().layers()[0] \
            .to_OpaqueMaterial().get()
        outer.setSolarAbsorptance(openstudio.OptionalDouble(value))


@needs_sdk
class TestReferenceEnvelope(unittest.TestCase):
    def test_fdwr_scaled_proportionally_not_rebuilt(self):
        from btap.modeling.envelope import geometry as Geometry

        model = proposed_model()
        before = Geometry.exposed_walls(model)
        window_count_before = len(model.getSubSurfaces())
        self.assertGreater(before['fdwr'], FDWR_LIMIT, 'fixture starts over the limit')

        audit = reference(model)
        after = Geometry.exposed_walls(model)
        self.assertAlmostEqual(FDWR_LIMIT, after['fdwr'], delta=0.005,
                               msg='scaled down to the limit')
        self.assertEqual(window_count_before, len(model.getSubSurfaces()),
                         '8.4.4.3.(3) scales EXISTING fenestration — no rebuild, '
                         'same window count')
        decision = next(e for e in audit.entries
                        if 'scaled proportionally per orientation' in e['action'])
        self.assertRegex(decision['article'], r'8\.4\.4\.3\.\(3\)')

    def test_shading_rules(self):
        model = proposed_model()
        audit = reference(model)
        types = [g.shadingSurfaceType() for g in model.getShadingSurfaceGroups()]
        self.assertEqual(['Site'], types,
                         'Building/Space shading removed, Site (nearby structures) kept')
        decision = next(e for e in audit.entries
                        if '3.(4)-(5)' in str(e.get('article', '')))
        self.assertEqual(1, decision['inputs']['site_groups_kept'])

    # KEEP branch strengthened + DEFECT reproduction.
    #
    # The original test only ever checked the 'set'
    # (actual_roof_absorptance_used: True) branch, and never asserted anything
    # about 'keep' at all — a classic weak assertion: the KEEP branch could
    # silently misbehave and this test would still pass.
    #
    # Giving 'keep' a HOSTILE pre-set absorptance (0.3, not the fixture's
    # coincidental 0.7 default) exposed a real defect: the earlier
    # apply_lightweight_construction rebuilt EVERY opaque assembly — reached
    # unconditionally, regardless of actual_roof_absorptance_used — into a
    # fresh MasslessOpaqueMaterial without copying solar/thermal/visible
    # absorptance from the original layer. The SDK's own default
    # solarAbsorptance for a new MasslessOpaqueMaterial is 0.7 — IDENTICAL to
    # roof_absorptance_if_actual_used in envelope_rules_2020.json — so the
    # reference roof absorptance ended up at 0.7 EVEN WHEN THE FLAG WAS FALSE,
    # which happened to look correct only because the NECB target and the SDK
    # default coincide. A hostile 0.3 proves it: 8.4.4.3.(2)(a) says the
    # reference "keeps" the proposed value when actual_roof_absorptance_used
    # is False.
    def test_roof_absorptance_only_when_actual_used(self):
        keep = proposed_model()
        hostile_roof_absorptance(keep, 0.3)
        # default: actual_roof_absorptance_used False -> must NOT touch absorptance
        reference(keep)
        keep_roof = next(s for s in keep.getSurfaces()
                         if s.surfaceType() == 'RoofCeiling'
                         and s.outsideBoundaryCondition() == 'Outdoors')
        keep_outer = keep_roof.construction().get().to_Construction().get() \
            .layers()[0].to_OpaqueMaterial().get()
        self.assertAlmostEqual(
            0.3, keep_outer.solarAbsorptance(), delta=1e-6,
            msg='actual_roof_absorptance_used: False must leave the hostile proposed '
                'roof absorptance untouched (8.4.4.3.(2)(a))')

        set_model = proposed_model()
        hostile_roof_absorptance(set_model, 0.3)
        reference(set_model, actual_roof_absorptance_used=True)

        set_roof = next(s for s in set_model.getSurfaces()
                        if s.surfaceType() == 'RoofCeiling'
                        and s.outsideBoundaryCondition() == 'Outdoors')
        outer = set_roof.construction().get().to_Construction().get() \
            .layers()[0].to_OpaqueMaterial().get()
        self.assertAlmostEqual(0.7, outer.solarAbsorptance(), delta=1e-6)

    def test_lightweight_and_air_leakage(self):
        model = proposed_model()
        audit = reference(model)

        wall = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == 'Outdoors'
                    and s.surfaceType() == 'Wall')
        c = wall.construction().get().to_Construction().get()
        self.assertRegex(c.nameString(), r'Lightweight')
        self.assertEqual(1, len(c.layers()))
        # D-35 / Note A-8.4.4.4.(1): "lightweight" = light FRAME, not zero-mass
        # — the note's wood-frame example is 40.8 kg/m2 with 45.5 kJ/(m2.K)
        # heat capacity; the rebuilt layer is calibrated to exactly that.
        m = c.layers()[0].to_StandardOpaqueMaterial()
        self.assertTrue(m.is_initialized(),
                        'light-frame rebuild is a regular (massy) material')
        m = m.get()
        self.assertAlmostEqual(40.8, m.thickness() * m.density(), delta=0.01,
                               msg='Note A wood-frame areal mass')
        self.assertAlmostEqual(45_500.0,
                               m.thickness() * m.density() * m.specificHeat(),
                               delta=50.0, msg='Note A heat capacity')
        # 0.27595 = 1/(1/0.265 - wall films): table U incl. films (default convention)
        self.assertAlmostEqual(0.27595, c.thermalConductance().get(), delta=1e-3,
                               msg='Ut unchanged by the lightweight rebuild')

        infiltration = model.getSpaceInfiltrationDesignFlowRates()
        self.assertEqual(len(model.getSpaces()), len(infiltration))
        decision = next(e for e in audit.entries
                        if e['action'] == 'air-leakage default applied')
        self.assertRegex(decision['value'], r'\(5/75\)\^0\.6 x 1\.5')
        self.assertRegex(decision['article'], r'8\.4\.2\.9\.\(2\)')
        # rate sanity: (5/75)^0.6 = 0.1974; x1.5 = 0.296; xS/A_AGW > 0.296
        rate = infiltration[0].flowperExteriorWallArea().get() * 1000.0
        self.assertGreater(rate, 0.29)
        # D-19: no proposed infiltration -> constant convention (A=1)
        self.assertAlmostEqual(1.0, infiltration[0].constantTermCoefficient(), delta=1e-9)

    # D-19: the reference inherits the PROPOSED's infiltration modulation
    # (E+ modifier coefficients + schedule) — identical design totals with
    # asymmetric conventions change delivered infiltration ~2x. A proposed
    # whose total deviates from the untested 8.4.3.3.(3) default warns.
    def test_air_leakage_inherits_proposed_convention_and_checks_total(self):
        import openstudio

        model = proposed_model()
        sched = model.alwaysOnDiscreteSchedule()
        # fixture defaults would win the donor pick
        for obj in list(model.getSpaceInfiltrationDesignFlowRates()):
            obj.remove()
        for space in model.getSpaces():
            i = openstudio.model.SpaceInfiltrationDesignFlowRate(model)
            i.setFlowperExteriorSurfaceArea(0.00001)  # far below the default -> warn
            i.setConstantTermCoefficient(0.0)
            i.setVelocityTermCoefficient(0.224)  # DOE-2 wind-driven convention
            i.setSchedule(sched)
            i.setSpace(space)
        audit = reference(model)
        i = min(model.getSpaceInfiltrationDesignFlowRates(), key=lambda o: o.nameString())
        self.assertRegex(i.nameString(), r'NECB Ref Infiltration',
                         'proposed objects replaced')
        self.assertAlmostEqual(0.0, i.constantTermCoefficient(), delta=1e-9,
                               msg='wind-driven convention inherited')
        self.assertAlmostEqual(0.224, i.velocityTermCoefficient(), delta=1e-9)
        self.assertEqual(sched.nameString(), i.schedule().get().nameString())
        self.assertTrue(
            any('DEVIATES from the untested 8.4.3.3.(3) default' in w['action']
                for w in audit.warnings),
            'below-default proposed infiltration warns (permissive direction)')

    # D-21 / 3.2.4.2.(1)(c): S is the enclosure of the CONDITIONED volume. A
    # 10x10x3 conditioned box under a 10x10x2 unconditioned attic: S = walls
    # (120) + ground slab (100) + ceiling-to-attic (100) = 320 m2; the attic
    # roof (100) and gables (80) are NOT envelope. A_AGW = 120 (conditioned
    # walls only). Installed total must equal (5/75)^0.6 x 1.5 x S, and the
    # attic must receive NO infiltration object (its exterior walls sit outside
    # A_AGW — giving it flow-per-wall-area would re-inflate the total).
    def test_air_leakage_envelope_area_excludes_attic_per_3_2_4_2(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb.envelope import reference as Reference

        model = openstudio.model.Model()

        def print_at(z):
            pts = openstudio.Point3dVector()
            for x, y in ((0, 0), (0, 10), (10, 10), (10, 0)):
                pts.append(openstudio.Point3d(x, y, z))
            return pts

        cond = openstudio.model.Space.fromFloorPrint(print_at(0.0), 3.0, model).get()
        attic = openstudio.model.Space.fromFloorPrint(print_at(3.0), 2.0, model).get()
        spaces = openstudio.model.SpaceVector()
        for s in (cond, attic):
            spaces.append(s)
        openstudio.model.matchSurfaces(spaces)  # pairs ceiling <-> attic floor
        attic.setPartofTotalFloorArea(False)
        for s in (cond, attic):
            s.setThermalZone(openstudio.model.ThermalZone(model))

        audit = AuditLog()
        Reference.apply_air_leakage_default(model, '8.4.4', audit)

        decision = next(e for e in audit.entries
                        if e['action'] == 'air-leakage default applied')
        self.assertAlmostEqual(320.0, decision['inputs']['envelope_area_m2'], delta=0.5,
                               msg='attic roof/gables excluded; ceiling included')
        self.assertAlmostEqual(120.0, decision['inputs']['ag_wall_area_m2'], delta=0.5,
                               msg='conditioned walls only')

        infiltration = model.getSpaceInfiltrationDesignFlowRates()
        self.assertEqual(1, len(infiltration), 'attic receives NO infiltration object')
        self.assertEqual(cond.handle(), infiltration[0].space().get().handle())
        installed_l_s = (infiltration[0].flowperExteriorWallArea().get()
                         * cond.exteriorWallArea() * 1000.0)
        expected_l_s = ((5.0 / 75.0) ** 0.6) * 1.5 * 320.0
        self.assertAlmostEqual(expected_l_s, installed_l_s, delta=0.2,
                               msg='installed total = code default over the (1)(c) enclosure')

    def test_coverage_emitted_all_17_articles(self):
        audit = reference(proposed_model())
        coverage = [e for e in audit.entries if e['step'] == 'coverage']
        # 14 + 8.4.1.1 (envelope slice) + 8.4.2.9 air leakage + 3.2.4.2 (D-76)
        self.assertEqual(17, len(coverage))
        ref3 = next(e for e in coverage if e.get('article') == '8.4.4.3.')
        self.assertEqual('implemented', ref3['inputs']['status'])
        self.assertGreater(ref3['inputs']['decisions_citing'], 0)
        # Honest gaps still warn — but a FIELD-TEST article is not a modelling
        # gap. 3.2.4.1/3.2.4.2 are established by a whole-building ASTM E3158
        # test, so they carry gap_owner: modeller and render as an info scope
        # note (D-76). A permanent warning nobody can clear is the failure mode
        # D-09 describes.
        for article in ('3.2.4.1.', '3.2.4.2.'):
            entry = next((e for e in coverage if e.get('article') == article), None)
            self.assertIsNotNone(entry, f'{article} must still be declared')
            self.assertEqual('info', entry['level'],
                             f'{article} is field-verified, not a modelling warning')
            self.assertEqual('modeller', entry['inputs']['gap_owner'])
            self.assertEqual('not_implemented', entry['inputs']['status'],
                             'the status stays honest')
        # The softening must not spread. gap_owner is ONLY for requirements no
        # model change can ever satisfy; a rule this package could implement
        # and has not must stay a bare partial/not_implemented and keep warning
        # (D-76 scope limit). Envelope declares no such rule today — its only
        # gaps are the two field tests above — so the guard is that nothing
        # ELSE has been given the flag.
        softened = sorted(e['article'] for e in coverage
                          if e['inputs'].get('gap_owner'))
        self.assertEqual(['3.2.4.1.', '3.2.4.2.'], softened,
                         'only the ASTM E3158 field-test articles may carry gap_owner')
        self.assertGreater(len(json.loads(audit.to_json())), 20)

    # Composition: HVAC + envelope reference on ONE clone with ONE audit.
    def test_composition_with_openstudio_hvac(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog

        # Plain import: M5 delivered this. A guard here would let a
        # regression that removes reference_hvac pass as a green skip.
        from btap.necb import envelope, hvac
        reference_hvac = hvac.reference_hvac

        proposed = proposed_model()
        zones = sorted_by_name(proposed.getThermalZones())
        modeling.build_system(proposed, 'Baseboard gas boiler', zones)
        types = {z.nameString(): 'Office - enclosed' for z in proposed.getThermalZones()}

        audit = AuditLog()
        result = reference_hvac(proposed, vintage='2020',
                                building={'storeys': 1, 'zone_types': types,
                                          'winter_design_temp_c': -20},
                                audit=audit)
        envelope.reference_envelope(result.model, vintage='2020', hdd=HDD, audit=audit)

        steps = list(dict.fromkeys(e['step'] for e in audit.entries))
        for s in ('selection', 'build', 'rules', 'efficiency', 'coverage',
                  'reference', 'prescriptive'):
            self.assertIn(s, steps,
                          'one audit spans HVAC + envelope reference generation')
        self.assertTrue(result.model.getAirLoopHVACs(), 'HVAC reference present')
        wall = next(s for s in result.model.getSurfaces()
                    if s.outsideBoundaryCondition() == 'Outdoors'
                    and s.surfaceType() == 'Wall')
        self.assertRegex(wall.construction().get().nameString(), r'Lightweight',
                         'envelope reference present on the SAME clone')
        self.assertGreater(len(json.loads(audit.to_json())), 50)


@needs_engine
class TestReferenceEnvelopeE2E(unittest.TestCase):
    def test_reference_envelope_runs_in_energyplus(self):
        from btap.simulation import run

        model = proposed_model()
        reference(model)
        for z in model.getThermalZones():
            z.setUseIdealAirLoads(True)
        with tempfile.TemporaryDirectory(prefix='osenv-ref-') as tmp:
            result = run(model, run_dir=str(Path(tmp) / 'ref'),
                         weather={'epw': str(EPW), 'ddy': str(DDY)}, sizing_only=True)
            self.assertTrue(result.is_clean(), 'reference envelope')


if __name__ == '__main__':
    unittest.main()
