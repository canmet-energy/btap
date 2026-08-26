"""Wizard gate (port of btap-modeling/test/test_wizards.rb): every shape
builds valid zoned massing; rectangle checked in detail (space census,
matched surfaces, below-grade BCs); unknown-parameter typos raise instead of
silently defaulting.

Ruby's ArgumentError sites translate to ValueError (the Python facade's
guard exception).
"""

from __future__ import annotations

import math
import unittest
from collections import Counter

from tests.support import needs_sdk

from btap.audit import AuditLog


@needs_sdk
class TestWizards(unittest.TestCase):
    def test_rectangle_census_and_matching(self):
        import btap.modeling as modeling

        audit = AuditLog()
        model = modeling.create(shape='rectangle', length=40.0, width=25.0,
                                storeys=2, below_grade_storeys=1,
                                floor_to_floor_height=3.6, perimeter_zone_depth=4.0,
                                audit=audit)
        self.assertEqual(15, len(model.getSpaces()), '5 spaces (4 perimeter + core) x 3 storeys')
        self.assertEqual(3, len(model.getBuildingStorys()))

        # below-grade storey: walls Ground, interior floors/ceilings matched
        basement = [s for s in model.getSpaces() if s.nameString().startswith('Story 0')]
        self.assertEqual(5, len(basement))
        ground_walls = [s for space in basement for s in space.surfaces()
                        if s.surfaceType() == 'Wall' and s.outsideBoundaryCondition() == 'Ground']
        self.assertGreaterEqual(len(ground_walls), 4, 'below-grade exterior walls are Ground')

        matched = sum(1 for s in model.getSurfaces() if s.outsideBoundaryCondition() == 'Surface')
        self.assertGreater(matched, 20, 'interior surfaces matched between storeys and zones')

        total_area = sum(s.floorArea() for s in model.getSpaces())
        self.assertAlmostEqual(40.0 * 25.0 * 3, total_area, delta=0.5,
                               msg='floor area = footprint x storeys')
        decision = next(e for e in audit.entries if e['step'] == 'geometry')
        self.assertEqual(15, decision['inputs']['spaces'])
        self.assertEqual(2, decision['inputs']['storeys_above'])
        self.assertEqual(1, decision['inputs']['storeys_below'])

    def test_storey_aliases_and_guards(self):
        """The canonical facade vocabulary is storeys=/below_grade_storeys=; the
        engines' own spellings stay accepted, mixing the two raises, and the
        unknown-parameter guard still fires for a real typo."""
        import btap.modeling as modeling

        canonical = modeling.create(shape='rectangle', length=40.0, width=25.0,
                                    storeys=2, below_grade_storeys=1, perimeter_zone_depth=4.0)
        legacy = modeling.create(shape='rectangle', length=40.0, width=25.0,
                                 above_ground_storys=2, under_ground_storys=1, perimeter_zone_depth=4.0)
        self.assertEqual(len(legacy.getSpaces()), len(canonical.getSpaces()),
                         'old names produce the same geometry')
        self.assertEqual(len(legacy.getBuildingStorys()), len(canonical.getBuildingStorys()))
        self.assertAlmostEqual(sum(s.floorArea() for s in legacy.getSpaces()),
                               sum(s.floorArea() for s in canonical.getSpaces()), delta=0.01)
        self.assertEqual(
            Counter((s.surfaceType(), s.outsideBoundaryCondition()) for s in legacy.getSurfaces()),
            Counter((s.surfaceType(), s.outsideBoundaryCondition()) for s in canonical.getSurfaces()))

        # non-rectangle shapes: storeys= -> num_floors, no below-grade support
        aliased = modeling.create(shape='l', length=40.0, width=40.0, storeys=2)
        self.assertEqual(
            len(modeling.create(shape='l', length=40.0, width=40.0, num_floors=2).getSpaces()),
            len(aliased.getSpaces()))
        with self.assertRaises(ValueError):
            modeling.create(shape='l', storeys=2, below_grade_storeys=1)

        # alias + target together is ambiguous
        with self.assertRaises(ValueError):
            modeling.create(shape='rectangle', length=40.0, width=25.0, storeys=2, above_ground_storys=3)
        with self.assertRaises(ValueError):
            modeling.create(shape='rectangle', length=40.0, width=25.0,
                            below_grade_storeys=1, under_ground_storys=0)

        # and a genuine typo still raises rather than silently defaulting
        with self.assertRaises(ValueError):
            modeling.create(shape='rectangle', storeyz=2)

    def test_every_shape_builds(self):
        import btap.modeling as modeling

        cases = {
            'aspect_ratio': {'aspect_ratio': 0.6, 'floor_area': 1800.0, 'num_floors': 2},
            'courtyard': {'length': 50.0, 'width': 30.0, 'courtyard_length': 20.0,
                          'courtyard_width': 10.0, 'num_floors': 1},
            'h': {'num_floors': 1},
            'l': {'num_floors': 1},
            't': {'num_floors': 1},
            'u': {'num_floors': 1},
        }
        for shape, params in cases.items():
            model = modeling.create(shape=shape, **params)
            self.assertGreaterEqual(len(model.getSpaces()), 4, f'{shape}: zoned spaces')
            self.assertTrue(all(s.floorArea() > 0 for s in model.getSpaces()),
                            f'{shape}: positive areas')
            exterior_walls = sum(1 for s in model.getSurfaces()
                                 if s.surfaceType() == 'Wall' and s.outsideBoundaryCondition() == 'Outdoors')
            self.assertGreaterEqual(exterior_walls, 4, f'{shape}: exterior walls present')

    def test_courtyard_has_inner_facade(self):
        import btap.modeling as modeling

        model = modeling.create(shape='courtyard', length=50.0, width=30.0,
                                courtyard_length=20.0, courtyard_width=10.0, num_floors=1)
        footprint = sum(s.floorArea() for s in model.getSpaces())
        self.assertAlmostEqual(50.0 * 30.0 - 20.0 * 10.0, footprint, delta=0.5,
                               msg='courtyard void excluded from floor area')

    def test_invalid_parameters(self):
        import btap.modeling as modeling

        with self.assertRaises(ValueError):
            modeling.create(shape='dodecagon')
        with self.assertRaises(ValueError):
            modeling.create(shape='rectangle', lenght=40.0)  # typo must raise
        with self.assertRaises(ValueError):
            modeling.create(shape='rectangle', length=10.0, width=10.0, perimeter_zone_depth=6.0)

    def test_rotation_via_aspect_ratio(self):
        import btap.modeling as modeling

        model = modeling.create(shape='aspect_ratio', aspect_ratio=0.5, floor_area=1000.0,
                                rotation=45.0, num_floors=1)
        group = model.getSpaces()[0]
        matrix = group.transformation().matrix()
        self.assertAlmostEqual(45.0 * math.pi / 180,
                               math.atan2(matrix[1, 0], matrix[0, 0]), delta=0.2)


if __name__ == '__main__':
    unittest.main()
