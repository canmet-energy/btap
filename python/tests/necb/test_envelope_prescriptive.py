"""P3 gate (standalone half): prescriptive application sets every envelope
surface to its NECB maximum U; FDWR/SRR mutators hit their limits; audit
narrates everything.

Port of btap-necb/test/test_envelope_prescriptive.rb.
"""

from __future__ import annotations

import unittest

from tests.necb.support import load_raw_fixture, needs_sdk

HDD = 3890  # Toronto (Table C-1)


def print_at(z):
    import openstudio
    pts = openstudio.Point3dVector()
    for x, y in ((0, 0), (0, 10), (10, 10), (10, 0)):
        pts.append(openstudio.Point3d(x, y, z))
    return pts


@needs_sdk
class TestPrescriptive(unittest.TestCase):
    @property
    def n(self):
        from btap.necb import envelope
        return envelope

    def applied_model(self, **kwargs):
        model = load_raw_fixture()
        audit = self.n.apply_prescriptive(model, vintage='2020', hdd=HDD, **kwargs)
        return model, audit

    def test_walls_and_roofs_hit_table_values(self):
        model, audit = self.applied_model()
        # HDD 3890 -> zone 5 bin (hdd < 4000): table wall 0.265, roof 0.156 as
        # OVERALL U incl. films (1.4.1.2 definition; default include_films: True)
        # -> construction-only conductance 1/(1/U - R_films): wall 0.2759, roof
        # 0.1594 — the same values the legacy OSut path (TBD.genConstruction)
        # produces on NECB2020 archetypes.
        for surface in model.getSurfaces():
            if surface.outsideBoundaryCondition() != 'Outdoors':
                continue

            c = surface.construction().get().to_Construction().get()
            if surface.surfaceType() == 'Wall':
                self.assertAlmostEqual(0.27595, c.thermalConductance().get(),
                                       delta=1e-4, msg=surface.nameString())
            elif surface.surfaceType() == 'RoofCeiling':
                self.assertAlmostEqual(0.15942, c.thermalConductance().get(),
                                       delta=1e-4, msg=surface.nameString())
        # Table 3.2.3.1 floors row below zone 8 prescribes only a 1.2 m
        # perimeter strip (3.2.3.3.(3)) — the slab field carries NO maximum
        # (D-32). The fixture's plain-Ground floors can't carry a Kiva strip:
        # constructions stay untouched and the gap is warned.
        ground = [s for s in model.getSurfaces()
                  if s.isGroundSurface() and s.surfaceType() == 'Floor']
        self.assertTrue(ground)
        # PORT NOTE: the pristine model MUST be held in a local — the SWIG
        # wrappers keep no reference to the owning Model, so iterating the
        # surfaces of a temporary (Ruby's `load_raw_fixture.getSurfaces`)
        # segfaults the moment CPython collects it mid-comprehension.
        pristine = load_raw_fixture()
        before = {s.nameString(): s.construction().get().nameString()
                  for s in pristine.getSurfaces()
                  if s.isGroundSurface() and s.surfaceType() == 'Floor'}
        for surface in ground:
            self.assertEqual(before[surface.nameString()],
                             surface.construction().get().nameString(),
                             f'{surface.nameString()}: strip-zone slab field left as modeled')
        self.assertTrue(
            any('3.2.3.3' in str(w.get('article', '')) for w in audit.warnings),
            'no-Kiva strip zone warns that the strip is not representable')
        self.assertTrue(any(e['step'] == 'prescriptive'
                            and '3.2.2.2' in str(e.get('article', ''))
                            for e in audit.entries))
        self.assertTrue(any('3.2.3.1' in str(e.get('article', ''))
                            for e in audit.entries))

    # D-32: Table 3.2.3.1 floors row is zone-conditional — zones 4-7B keep the
    # slab field and get a 1.2 m Kiva perimeter strip sized to the 0.757
    # target; zone 8 retargets the full area to 0.379 (both as overall U incl.
    # film).
    def test_ground_floor_strip_vs_full_area(self):
        import openstudio

        from btap.modeling.envelope import constructions as Constructions

        def build():
            model = openstudio.model.Model()
            space = openstudio.model.Space.fromFloorPrint(print_at(0.0), 3.0, model).get()
            slab_mat = openstudio.model.StandardOpaqueMaterial(
                model, 'MediumRough', 0.1, 1.8, 2300, 900)
            slab = openstudio.model.Construction(model)
            slab.setLayers([slab_mat])
            seed_mat = openstudio.model.StandardOpaqueMaterial(
                model, 'MediumSmooth', 0.05, 0.05, 100, 1000)
            seed = openstudio.model.Construction(model)
            seed.setLayers([seed_mat])
            kiva = openstudio.model.FoundationKiva(model)
            floor = None
            for s in space.surfaces():
                if s.surfaceType() == 'Floor':
                    s.setConstruction(slab)
                    s.setAdjacentFoundation(kiva)
                    floor = s
                else:
                    s.setConstruction(seed)
            return model, kiva, floor

        model, kiva, floor = build()
        slab_before = floor.construction().get().nameString()
        audit = self.n.apply_prescriptive(model, vintage='2020', hdd=HDD)  # zone 5 -> strip
        self.assertEqual(slab_before, floor.construction().get().nameString(),
                         'strip zone: slab field construction untouched')
        ins = kiva.interiorHorizontalInsulationMaterial()
        self.assertTrue(ins.is_initialized(),
                        'strip zone: Kiva interior horizontal insulation set')
        self.assertAlmostEqual(1.2, kiva.interiorHorizontalInsulationWidth().get(),
                               delta=1e-9)
        mat = ins.get().to_StandardOpaqueMaterial().get()
        strip_target = 1.0 / ((1.0 / 0.757) - Constructions.film_r('floor', 'ground'))
        expected_r = (1.0 / strip_target) - (0.1 / 1.8)
        self.assertAlmostEqual(expected_r, mat.thickness() / mat.thermalConductivity(),
                               delta=1e-3,
                               msg='strip insulation R brings the strip assembly to the table U')
        self.assertTrue(any('3.2.3.3' in str(e.get('article', '')) for e in audit.entries))

        model8, kiva8, floor8 = build()
        self.n.apply_prescriptive(model8, vintage='2020', hdd=8170)  # zone 8 -> full area
        full_target = 1.0 / ((1.0 / 0.379) - Constructions.film_r('floor', 'ground'))
        self.assertAlmostEqual(
            full_target,
            floor8.construction().get().to_Construction().get().thermalConductance().get(),
            delta=1e-4, msg='zone 8: slab retargeted full-area to the 0.379 overall U')
        self.assertFalse(kiva8.interiorHorizontalInsulationMaterial().is_initialized(),
                         'zone 8: no strip — full-area requirement instead')

    def test_legacy_naming_and_reuse_conventions(self):
        model, _ = self.applied_model()
        walls = [s for s in model.getSurfaces()
                 if s.outsideBoundaryCondition() == 'Outdoors' and s.surfaceType() == 'Wall']
        names = list(dict.fromkeys(s.construction().get().nameString() for s in walls))
        self.assertEqual(1, len(names),
                         'identical base constructions share ONE customized copy')
        self.assertRegex(names[0], r':U-0\.27',
                         'legacy BTAP naming convention (costing keys on it)')

    def test_fdwr_and_srr_mutators(self):
        from btap.modeling.envelope import geometry as Geometry

        model, audit = self.applied_model(apply_fdwr=True, apply_srr=True)
        census = Geometry.exposed_walls(model)
        # (2000-778)/3000 = 0.4074
        limit = self.n.max_fdwr(vintage='2020', hdd=HDD)
        self.assertAlmostEqual(limit, census['fdwr'], delta=0.03,
                               msg='windows rebuilt to the FDWR limit')
        for wall in census['walls']:
            for ss in wall.subSurfaces():
                self.assertEqual('FixedWindow', ss.subSurfaceType())

        roofs = Geometry.exposed_roofs(model)
        self.assertAlmostEqual(0.02, roofs['srr'], delta=0.002,
                               msg='skylights at 2% of gross roof area')
        self.assertTrue(any(e['step'] == 'geometry'
                            and '3.2.1.4' in str(e.get('article', ''))
                            for e in audit.entries))

    def test_film_convention_default_and_optout(self):
        from btap.modeling.envelope import constructions as Constructions

        films_model, audit = self.applied_model()  # default include_films: True
        btap_model, btap_audit = self.applied_model(include_films=False)
        films_wall = next(s for s in films_model.getSurfaces()
                          if s.outsideBoundaryCondition() == 'Outdoors'
                          and s.surfaceType() == 'Wall')
        btap_wall = next(s for s in btap_model.getSurfaces()
                         if s.nameString() == films_wall.nameString())
        films_c = films_wall.construction().get().to_Construction().get() \
            .thermalConductance().get()
        btap_c = btap_wall.construction().get().to_Construction().get() \
            .thermalConductance().get()
        self.assertGreater(
            films_c, btap_c,
            'default (films) mode: construction conductance is higher so the OVERALL '
            '(with films) U meets the table')
        # default: overall U with films equals the table value (1.4.1.2 definition)
        r_films = Constructions.film_r('wall', 'outdoors')
        overall_u = 1.0 / ((1.0 / films_c) + r_films)
        self.assertAlmostEqual(0.265, overall_u, delta=1e-3)
        # opt-out: construction-only conductance equals the table value (old BTAP)
        self.assertAlmostEqual(0.265, btap_c, delta=1e-4)
        self.assertTrue(any(e['action'] == 'film convention'
                            and 'code-literal' in str(e.get('value', ''))
                            for e in audit.entries))
        self.assertTrue(any(e['action'] == 'film convention'
                            and 'BTAP' in str(e.get('value', ''))
                            for e in btap_audit.entries))

    # 1.4.1.2 "building envelope" scope: an unconditioned attic's deck/gables
    # are NOT envelope (constructions untouched); the ceiling below IS — set to
    # the ROOF row (3.1.1.7.(6) inclination rule) with the enclosure credited
    # at U 6.25 (3.1.1.7.(4)) and interior films on both faces.
    def test_attic_scope_deck_untouched_ceiling_retargeted(self):
        import openstudio

        from btap.modeling.envelope import constructions as Constructions

        model = openstudio.model.Model()
        cond = openstudio.model.Space.fromFloorPrint(print_at(0.0), 3.0, model).get()
        attic = openstudio.model.Space.fromFloorPrint(print_at(3.0), 2.0, model).get()
        spaces = openstudio.model.SpaceVector()
        for s in (cond, attic):
            spaces.append(s)
        openstudio.model.matchSurfaces(spaces)
        attic.setPartofTotalFloorArea(False)

        # seed every surface with a real layered construction
        mat = openstudio.model.StandardOpaqueMaterial(
            model, 'MediumSmooth', 0.02, 0.5, 800, 1000)
        ins = openstudio.model.StandardOpaqueMaterial(
            model, 'MediumSmooth', 0.2, 0.03, 45, 1000)
        seed = openstudio.model.Construction(model)
        seed.setLayers([mat, ins, mat])
        for s in model.getSurfaces():
            s.setConstruction(seed)
        deck = next(s for s in attic.surfaces()
                    if s.surfaceType() == 'RoofCeiling'
                    and s.outsideBoundaryCondition() == 'Outdoors')
        deck_before = deck.construction().get().nameString()

        self.n.apply_prescriptive(model, vintage='2020', hdd=HDD)

        self.assertEqual(deck_before, deck.construction().get().nameString(),
                         'attic deck is not envelope — construction untouched')
        ceiling = next(s for s in cond.surfaces()
                       if s.surfaceType() == 'RoofCeiling'
                       and s.outsideBoundaryCondition() == 'Surface')
        target = 1.0 / ((1.0 / 0.156) - (1.0 / 6.25)
                        - Constructions.film_r_interzone('roofceiling'))
        self.assertAlmostEqual(
            target,
            ceiling.construction().get().to_Construction().get().thermalConductance().get(),
            delta=1e-4,
            msg='ceiling to attic set to roof row with enclosure credit + interzone films')
        attic_floor = next(s for s in attic.surfaces() if s.surfaceType() == 'Floor')
        self.assertEqual(ceiling.construction().get().nameString(),
                         attic_floor.construction().get().nameString(),
                         'paired surface carries the same construction')

    def test_windows_preserve_shgc(self):
        import openstudio

        model = load_raw_fixture()
        # give one wall a window with a known SHGC before applying
        wall = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == 'Outdoors'
                    and s.surfaceType() == 'Wall')
        wall.setWindowToWallRatio(0.3)
        glazing = openstudio.model.SimpleGlazing(model)
        glazing.setUFactor(3.5)
        glazing.setSolarHeatGainCoefficient(0.42)
        construction = openstudio.model.Construction(model)
        construction.setLayers([glazing])
        for ss in wall.subSurfaces():
            ss.setSubSurfaceType('FixedWindow')
            ss.setConstruction(construction)

        self.n.apply_prescriptive(model, vintage='2020', hdd=HDD)
        ss = wall.subSurfaces()[0]
        new_glazing = ss.construction().get().to_Construction().get() \
            .layers()[0].to_SimpleGlazing().get()
        self.assertAlmostEqual(1.9, new_glazing.uFactor(), delta=1e-6,
                               msg='window U at Table 3.2.2.3 value')
        self.assertAlmostEqual(0.42, new_glazing.solarHeatGainCoefficient(), delta=1e-6,
                               msg='SHGC preserved')

    def test_unresolvable_hdd_raises(self):
        with self.assertRaises(ValueError):
            self.n.apply_prescriptive(load_raw_fixture(), vintage='2020')


if __name__ == '__main__':
    unittest.main()
