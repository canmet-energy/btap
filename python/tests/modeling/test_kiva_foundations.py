"""Kiva foundation creation: the perimeter the SDK cannot compute, the four
hazards that produce a silently wrong model, and the refusals that keep a
refused call from leaving half a foundation behind.

Each test states the failure it guards. Where a hazard is only visible by
contrast, the test carries the CONTROL that shows the unguarded path failing,
because a passing assertion on the guarded path alone cannot tell a working
guard from an absent hazard.
"""

import unittest

from tests.support import needs_sdk


def _concrete(model):
    import openstudio

    construction = openstudio.model.Construction(model)
    construction.setName("Slab")
    layer = openstudio.model.StandardOpaqueMaterial(
        model, "Rough", 0.2, 1.9, 2240.0, 900.0)
    layer.setName("Concrete 200")
    construction.setLayers([layer])
    return construction


def _slab(model, name, ox, oy, width=10.0, depth=10.0, construction=None):
    import openstudio

    space = openstudio.model.Space(model)
    space.setName(f"{name} Space")
    points = openstudio.Point3dVector()
    for x, y in [(ox, oy), (ox + width, oy), (ox + width, oy + depth), (ox, oy + depth)]:
        points.append(openstudio.Point3d(x, y, 0.0))
    surface = openstudio.model.Surface(points, model)
    surface.setName(name)
    surface.setSurfaceType("Floor")
    surface.setSpace(space)
    surface.setOutsideBoundaryCondition("Ground")
    if construction is not None:
        surface.setConstruction(construction)
    return surface


def _wall(model, space, name, y, construction, length=10.0, height=3.0):
    import openstudio

    points = openstudio.Point3dVector()
    for x, z in [(0.0, 0.0), (length, 0.0), (length, -height), (0.0, -height)]:
        points.append(openstudio.Point3d(x, y, z))
    surface = openstudio.model.Surface(points, model)
    surface.setName(name)
    surface.setSurfaceType("Wall")
    surface.setSpace(space)
    surface.setConstruction(construction)
    return surface


@needs_sdk
class TestExposedPerimeter(unittest.TestCase):
    def test_a_courtyard_keeps_its_edges(self):
        """The reason neither exposedPerimeter() nor joinAllPolygons() is used.

        A 3x3 ring of 10 m slabs with the centre missing has 120 m of outer
        edge and 40 m of courtyard edge. joinAllPolygons fills the hole and
        returns 120; the interval subtraction must return 160. If this test
        reads 120 the courtyard has been lost and every ring building
        under-insulates its inner slab edge.
        """
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        ring = [
            _slab(model, f"Floor {i}{j}", i * 10.0, j * 10.0)
            for i in range(3) for j in range(3) if (i, j) != (1, 1)
        ]
        measured = foundations.exposed_perimeters(model, ring)

        self.assertAlmostEqual(sum(measured["perimeters"].values()), 160.0, places=3)
        # Each of the eight slabs contributes two of its four edges.
        self.assertEqual(
            sorted(round(v, 3) for v in measured["perimeters"].values()),
            [20.0] * 8)

    def test_an_abutting_slab_removes_the_shared_edge(self):
        """Two slabs side by side expose 60 m, not the 80 m of their polygons."""
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        left = _slab(model, "Left", 0.0, 0.0)
        right = _slab(model, "Right", 10.0, 0.0)
        measured = foundations.exposed_perimeters(model, [left, right])

        self.assertAlmostEqual(measured["perimeters"]["Left"], 30.0, places=3)
        self.assertAlmostEqual(measured["perimeters"]["Right"], 30.0, places=3)

    def test_an_unreported_neighbour_still_covers_its_shared_edge(self):
        """Neighbours come from the whole model, not just the reported floors.

        Reporting only `Left` must not hand back 40 m as though `Right` were
        not there — that is the bug where a caller's selection changes a
        geometric fact.
        """
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        left = _slab(model, "Left", 0.0, 0.0)
        _slab(model, "Right", 10.0, 0.0)
        measured = foundations.exposed_perimeters(model, [left])

        self.assertAlmostEqual(measured["perimeters"]["Left"], 30.0, places=3)

    def test_a_space_less_surface_is_reported_not_crashed(self):
        """`Surface.exposedPerimeter()` SEGFAULTS without a parent Space.

        A segfault takes the interpreter with it, so this test passing at all
        is the assertion: the guard ran instead of the SDK call. gbXML imports
        genuinely produce parentless surfaces.
        """
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        points = openstudio.Point3dVector()
        for x, y in [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]:
            points.append(openstudio.Point3d(x, y, 0.0))
        orphan = openstudio.model.Surface(points, model)
        orphan.setName("Orphan")
        orphan.setSurfaceType("Floor")

        self.assertFalse(foundations.has_space(orphan))
        self.assertIsNone(foundations.world_vertices(orphan))
        measured = foundations.exposed_perimeters(model, [orphan])
        self.assertEqual(measured["no_space"], ["Orphan"])
        self.assertNotIn("Orphan", measured["perimeters"])


@needs_sdk
class TestKivaCreation(unittest.TestCase):
    def test_a_buried_slab_is_not_left_sun_exposed(self):
        """HAZARD: setAdjacentFoundation leaves SunExposed/WindExposed intact.

        The CONTROL below is the point of this test. Calling
        setAdjacentFoundation on a sun-exposed surface produces a Foundation
        slab that EnergyPlus still gives solar gain. Only the ordered write
        clears it, and without the control a reader cannot tell whether the
        order mattered.
        """
        import openstudio

        from btap.modeling.envelope import foundations

        # CONTROL: the unguarded path leaves the fictitious exposure behind.
        control = openstudio.model.Model()
        bare = _slab(control, "Slab", 0.0, 0.0, construction=_concrete(control))
        bare.setOutsideBoundaryCondition("Outdoors")
        bare.setAdjacentFoundation(openstudio.model.FoundationKiva(control))
        self.assertEqual(bare.outsideBoundaryCondition(), "Foundation")
        self.assertEqual(bare.sunExposure(), "SunExposed")
        self.assertEqual(bare.windExposure(), "WindExposed")

        # Ours: boundary condition first, which is what derives NoSun/NoWind.
        model = openstudio.model.Model()
        floor = _slab(model, "Slab", 0.0, 0.0, construction=_concrete(model))
        floor.setOutsideBoundaryCondition("Outdoors")
        result = foundations.create_kiva_foundation(model, floor)

        self.assertTrue(result["created"], result["refusals"])
        self.assertEqual(floor.outsideBoundaryCondition(), "Foundation")
        self.assertEqual(floor.sunExposure(), "NoSun")
        self.assertEqual(floor.windExposure(), "NoWind")

    def test_the_exposed_perimeter_object_is_written_and_reads_back(self):
        """A Foundation surface with no exposed-perimeter object is an E+ FATAL,
        and the constructor reports success even when it discarded the value."""
        import openstudio

        from btap._compat import opt
        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        floor = _slab(model, "Slab", 0.0, 0.0, construction=_concrete(model))
        result = foundations.create_kiva_foundation(model, floor)

        self.assertTrue(result["created"], result["refusals"])
        self.assertAlmostEqual(result["perimeter_m"], 40.0, places=3)
        written = opt(floor.surfacePropertyExposedFoundationPerimeter())
        self.assertIsNotNone(written)
        self.assertEqual(written.exposedPerimeterCalculationMethod(),
                         "TotalExposedPerimeter")
        self.assertAlmostEqual(opt(written.totalExposedPerimeter()), 40.0, places=3)
        self.assertEqual(len(model.getFoundationKivas()), 1)

    def test_walls_are_attached_in_the_same_ordered_write(self):
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        construction = _concrete(model)
        floor = _slab(model, "Slab", 0.0, 0.0, construction=construction)
        space = floor.space().get()
        walls = [_wall(model, space, f"Wall {i}", i * 1.0, construction)
                 for i in range(3)]
        result = foundations.create_kiva_foundation(model, floor, walls)

        self.assertTrue(result["created"], result["refusals"])
        self.assertEqual(result["walls"], ["Wall 0", "Wall 1", "Wall 2"])
        for wall in walls:
            self.assertEqual(wall.outsideBoundaryCondition(), "Foundation")
            self.assertEqual(wall.sunExposure(), "NoSun")


@needs_sdk
class TestKivaRefusals(unittest.TestCase):
    def test_walls_exceeding_the_perimeter_are_refused(self):
        """E11, measured by Fable on #121: paired walls longer than the exposed
        perimeter is `** Fatal ** Kiva: Errors discovered, program terminates.`

        Eight 10 m walls (80 m) against a 40 m slab edge. The refusal must come
        BEFORE anything is written, so the model is asserted untouched.
        """
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        construction = _concrete(model)
        floor = _slab(model, "Slab", 0.0, 0.0, construction=construction)
        space = floor.space().get()
        walls = [_wall(model, space, f"Wall {i}", i * 1.0, construction)
                 for i in range(8)]
        result = foundations.create_kiva_foundation(model, floor, walls)

        self.assertFalse(result["created"])
        self.assertTrue(
            any("80.000 m" in r and "40.000 m" in r for r in result["refusals"]),
            result["refusals"])
        # Nothing half-written.
        self.assertEqual(len(model.getFoundationKivas()), 0)
        self.assertEqual(floor.outsideBoundaryCondition(), "Ground")
        self.assertFalse(
            floor.surfacePropertyExposedFoundationPerimeter().is_initialized())

    def test_a_massless_layer_is_refused(self):
        """EnergyPlus refuses a Foundation surface whose construction has a
        no-mass layer. openstudio's own exampleModel() carries one."""
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.exampleModel()
        floor = next(s for s in model.getSurfaces()
                     if s.surfaceType() == "Floor"
                     and s.outsideBoundaryCondition() == "Ground")
        result = foundations.create_kiva_foundation(model, floor)

        self.assertFalse(result["created"])
        self.assertTrue(
            any("not a standard opaque material" in r for r in result["refusals"]),
            result["refusals"])
        self.assertEqual(len(model.getFoundationKivas()), 0)

    def test_a_surface_with_subsurfaces_is_refused(self):
        """The Foundation boundary condition is not allowed with windows."""
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        construction = _concrete(model)
        floor = _slab(model, "Slab", 0.0, 0.0, construction=construction)
        points = openstudio.Point3dVector()
        for x, y in [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]:
            points.append(openstudio.Point3d(x, y, 0.0))
        window = openstudio.model.SubSurface(points, model)
        window.setSurface(floor)

        result = foundations.create_kiva_foundation(model, floor)
        self.assertFalse(result["created"])
        self.assertTrue(any("windows or doors" in r for r in result["refusals"]),
                        result["refusals"])

    def test_a_second_floor_is_not_accepted_as_a_wall(self):
        """EnergyPlus allows exactly one floor per Foundation:Kiva object, which
        is why the signature takes one floor rather than a list."""
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        construction = _concrete(model)
        first = _slab(model, "Slab C", 0.0, 0.0, construction=construction)
        second = _slab(model, "Slab D", 50.0, 50.0, construction=construction)
        result = foundations.create_kiva_foundation(model, first, [second])

        self.assertFalse(result["created"])
        self.assertTrue(any("is a Floor" in r for r in result["refusals"]),
                        result["refusals"])
        self.assertEqual(len(model.getFoundationKivas()), 0)

    def test_a_write_the_sdk_silently_discarded_is_caught(self):
        """HAZARD: createSurfacePropertyExposedFoundationPerimeter returns an
        INITIALIZED optional even when it threw the input away.

        Probed on OpenStudio 3.11.0: a negative total reads back as unset, and
        an unknown method reads back as ''. Both report success. The public
        path cannot reach either — `create_kiva_foundation` refuses a
        non-positive perimeter first and never passes a caller's method — so
        this drives `_write_exposed_perimeter` directly. Without it the
        read-back verification is unwitnessed and can be deleted with the suite
        still green, which is how it was first shipped.
        """
        import openstudio

        from btap._compat import opt
        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        floor = _slab(model, "Slab", 0.0, 0.0, construction=_concrete(model))

        # The hazard itself: the SDK reports success and holds nothing.
        rejected = floor.createSurfacePropertyExposedFoundationPerimeter(
            "TotalExposedPerimeter", -5.0)
        self.assertTrue(rejected.is_initialized())
        self.assertIsNone(opt(rejected.get().totalExposedPerimeter()))
        floor.resetSurfacePropertyExposedFoundationPerimeter()

        # And our write catches it rather than trusting is_initialized().
        reason = foundations._write_exposed_perimeter(floor, -5.0)
        self.assertIsNotNone(reason)
        self.assertIn("did not take", reason)

        # A good value still writes and verifies, and re-applying replaces it.
        self.assertIsNone(foundations._write_exposed_perimeter(floor, 40.0))
        self.assertIsNone(foundations._write_exposed_perimeter(floor, 25.0))
        written = opt(floor.surfacePropertyExposedFoundationPerimeter())
        self.assertAlmostEqual(opt(written.totalExposedPerimeter()), 25.0, places=3)

    def test_a_floor_with_no_exposed_edge_is_refused(self):
        """A slab fully enclosed by neighbours has no slab edge to solve."""
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        construction = _concrete(model)
        # The centre of a full 3x3 grid: every edge abuts another floor.
        for i in range(3):
            for j in range(3):
                _slab(model, f"Floor {i}{j}", i * 10.0, j * 10.0,
                      construction=construction)
        centre = next(s for s in model.getSurfaces()
                      if s.nameString() == "Floor 11")
        result = foundations.create_kiva_foundation(model, centre)

        self.assertFalse(result["created"])
        self.assertTrue(any("exposed slab edge" in r for r in result["refusals"]),
                        result["refusals"])


if __name__ == "__main__":
    unittest.main()
