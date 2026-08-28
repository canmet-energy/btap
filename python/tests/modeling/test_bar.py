"""Bar engine gate: ratio-true slicing with standards tagging, WWR, party
walls, below-grade handling — and the full-family composition (bar geometry
through compliance with ONE audit). Port of btap-modeling/test/test_bar.rb."""

from __future__ import annotations

import unittest

from tests.support import needs_sdk

RATIOS = {('Space Function', 'Office enclosed > 25 m2'): 0.7,
          ('Space Function', 'Corridor/Transition area other-sch-A'): 0.3}


@needs_sdk
class TestBar(unittest.TestCase):

    # Wizard/bar output has no constructions; downstream envelope work retargets
    # EXISTING ones, so authored models need a seed set first.
    def seed_constructions(self, model):
        import openstudio
        opaque = openstudio.model.MasslessOpaqueMaterial(model, 'MediumSmooth', 2.0)
        opaque.setName('Seed R-2')
        construction = openstudio.model.Construction(model)
        construction.setName('Seed Opaque')
        construction.setLayers([opaque])
        glazing = openstudio.model.SimpleGlazing(model)
        glazing.setUFactor(2.5)
        glazing.setSolarHeatGainCoefficient(0.4)
        glazing.setVisibleTransmittance(0.5)
        window = openstudio.model.Construction(model)
        window.setName('Seed Window')
        window.setLayers([glazing])
        for s in model.getSurfaces():
            s.setConstruction(construction)
        for s in model.getSubSurfaces():
            s.setConstruction(window)

    def test_ratio_true_slicing_and_tagging(self):
        import btap.modeling as modeling
        from btap.audit import AuditLog

        audit = AuditLog()
        model = modeling.bar(space_type_ratios=RATIOS, length=50.0, width=20.0,
                             num_stories_above_grade=2, wwr=0.4, audit=audit)

        self.assertTrue(all(s.spaceType().is_initialized() for s in model.getSpaces()),
                        'every space typed')
        areas = {}
        for s in model.getSpaces():
            key = s.spaceType().get().standardsSpaceType().get()
            areas[key] = areas.get(key, 0.0) + s.floorArea()
        total = sum(areas.values())
        self.assertAlmostEqual(50.0 * 20.0 * 2, total, delta=1.0)
        self.assertAlmostEqual(0.7, areas['Office enclosed > 25 m2'] / total, delta=0.01,
                               msg='ratio-true slicing')
        self.assertAlmostEqual(0.3, areas['Corridor/Transition area other-sch-A'] / total,
                               delta=0.01)

        wall_area = sum(s.grossArea() for s in model.getSurfaces()
                        if s.surfaceType() == 'Wall' and s.outsideBoundaryCondition() == 'Outdoors')
        window_area = sum(s.grossArea() for s in model.getSubSurfaces())
        self.assertAlmostEqual(0.4, window_area / wall_area, delta=0.03, msg='WWR honored')
        self.assertTrue(any('sliced bar massing' in e['action'] for e in audit.entries))

    def test_below_grade_and_party_walls(self):
        import btap.modeling as modeling

        model = modeling.bar(space_type_ratios=RATIOS, length=40.0, width=15.0,
                             num_stories_above_grade=2, num_stories_below_grade=1,
                             party_wall_stories_north=2, wwr=0.3)
        ground = sum(1 for s in model.getSurfaces() if s.outsideBoundaryCondition() == 'Ground')
        self.assertGreaterEqual(ground, 1, 'below-grade surfaces grounded')
        adiabatic = sum(1 for s in model.getSurfaces() if s.outsideBoundaryCondition() == 'Adiabatic')
        self.assertGreaterEqual(adiabatic, 1, 'party walls adiabatic')

    # storeys=/below_grade_storeys= are the canonical names; num_stories_*_grade
    # (the engine's own spelling, used by the tests above) still works, and the
    # two together are ambiguous.
    def test_storey_aliases(self):
        import btap.modeling as modeling
        from btap.audit import AuditLog

        audit = AuditLog()
        canonical = modeling.bar(space_type_ratios=RATIOS, length=30.0, width=15.0,
                                 storeys=2, below_grade_storeys=1, wwr=0.3, audit=audit)
        legacy = modeling.bar(space_type_ratios=RATIOS, length=30.0, width=15.0,
                              num_stories_above_grade=2, num_stories_below_grade=1, wwr=0.3)
        self.assertEqual(len(legacy.getSpaces()), len(canonical.getSpaces()),
                         'old names produce the same geometry')
        self.assertAlmostEqual(sum(s.floorArea() for s in legacy.getSpaces()),
                               sum(s.floorArea() for s in canonical.getSpaces()), delta=0.01)
        inputs = next(e for e in audit.entries if e['step'] == 'geometry')['inputs']
        self.assertEqual(2, inputs['storeys_above'])
        self.assertEqual(1, inputs['storeys_below'])

        # Ruby: ArgumentError; the facade raises ValueError for the ambiguous pair
        with self.assertRaises(ValueError):
            modeling.bar(space_type_ratios=RATIOS, storeys=2, num_stories_above_grade=3)
        # Ruby: ArgumentError (unknown keyword); Python signatures raise TypeError
        with self.assertRaises(TypeError):
            modeling.bar(space_type_ratios=RATIOS, storeyz=2)

    # The Ruby test hard-fails (flunk) if the btap-necb gem goes missing
    # rather than skipping; here btap.necb is a sibling subpackage of the
    # same distribution, so the composition simply runs (it was skipped
    # until M5 landed the necb port, and unskipped in that milestone).
    def test_full_family_composition_from_bar(self):
        import json

        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.necb import envelope as necb_envelope
        from btap.necb import lighting as necb_lighting
        from btap.necb import loads as necb_loads
        from btap.necb import shw as necb_shw

        model = modeling.bar(space_type_ratios=RATIOS, length=50.0, width=20.0,
                             num_stories_above_grade=2, wwr=0.4)
        # wizard output carries no constructions; the envelope pass retargets existing ones
        self.seed_constructions(model)
        audit = AuditLog()
        necb_loads.apply_loads(model, vintage='2020', audit=audit)
        necb_lighting.apply_lights(model, vintage='2020', audit=audit)
        necb_shw.apply_shw(model, vintage='2020', fuel='NaturalGas', audit=audit)
        modeling.build_system(model, 'Baseboard gas boiler',
                              sorted_by_name(model.getThermalZones()))
        necb_envelope.apply_prescriptive(model, vintage='2020', hdd=3890, audit=audit)

        self.assertTrue(list(model.getPeoples()), 'loads live on bar geometry')
        self.assertTrue([light for st in model.getSpaceTypes() for light in st.lights()],
                        'lighting live')
        self.assertTrue(list(model.getWaterUseEquipments()), 'SHW live')
        self.assertGreaterEqual(len(model.getPlantLoops()), 2, 'heating + SHW plants')
        wall = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == 'Outdoors' and s.surfaceType() == 'Wall')
        # D-23: table 0.265 is OVERALL U (incl. films) — constructions are named by
        # the construction-only conductance 1/(1/0.265 - R_films) = 0.2759.
        self.assertRegex(wall.construction().get().nameString(), r':U-0\.2759')
        steps = list(dict.fromkeys(e['step'] for e in audit.entries))
        for step in ('loads', 'lighting', 'shw', 'prescriptive'):
            self.assertIn(step, steps)
        self.assertGreater(len(json.loads(audit.to_json())), 40,
                           'ONE audit spans geometry-authored building through every domain')


if __name__ == '__main__':
    unittest.main()
