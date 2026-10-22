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


def _slab(model, name, ox, oy, width=10.0, depth=10.0, construction=None,
          elevation=0.0, boundary="Ground", space=None):
    import openstudio

    if space is None:
        space = openstudio.model.Space(model)
        space.setName(f"{name} Space")
    points = openstudio.Point3dVector()
    for x, y in [(ox, oy), (ox + width, oy), (ox + width, oy + depth), (ox, oy + depth)]:
        points.append(openstudio.Point3d(x, y, elevation))
    surface = openstudio.model.Surface(points, model)
    surface.setName(name)
    surface.setSurfaceType("Floor")
    surface.setSpace(space)
    surface.setOutsideBoundaryCondition(boundary)
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

    def test_an_upper_storey_does_not_cover_the_ground_slab(self):
        """The filter without which an upper plate eats the slab's edge.

        Measured on the Hangar archetype: 38 of 45 slabs at 0.0 m and 143.1 m
        in total unfiltered, against 13 and 337.0 m filtered.

        The SHAPES here are chosen deliberately. An upper plate with an
        IDENTICAL footprint is already excluded by the duplicate-footprint
        rule, and one strictly LARGER than the slab has no edge collinear with
        it, so neither case can fail — the first version of this test used an
        identical plate and passed with the filter deleted. A partial overlap
        and an inset plate are the cases that discriminate, and they are the
        ones Fable named as the dangerous direction: the perimeter comes out
        WRONG rather than zero, so nothing refuses it.
        """
        import openstudio

        from btap.modeling.envelope import foundations

        cases = [
            # label, upper plate geometry, what an unfiltered search returns
            ("partial overlap", dict(ox=5.0, oy=0.0, width=10.0, depth=10.0), 30.0),
            ("inset", dict(ox=0.0, oy=0.0, width=10.0, depth=5.0), 20.0),
        ]
        for label, plate, unfiltered in cases:
            for boundary in ("Surface", "Outdoors"):
                with self.subTest(plate=label, boundary=boundary):
                    model = openstudio.model.Model()
                    construction = _concrete(model)
                    ground = _slab(model, "Ground", 0.0, 0.0,
                                   construction=construction)
                    _slab(model, "Upper", plate["ox"], plate["oy"],
                          width=plate["width"], depth=plate["depth"],
                          construction=construction, elevation=9.0,
                          boundary=boundary)
                    measured = foundations.exposed_perimeters(model, [ground])

                    self.assertAlmostEqual(measured["perimeters"]["Ground"],
                                           40.0, places=3)
                    # And the value this would have been without the filter,
                    # so the test states what it is guarding against.
                    self.assertNotAlmostEqual(measured["perimeters"]["Ground"],
                                              unfiltered, places=3)

    def test_a_tower_with_offset_plates_still_gets_a_foundation(self):
        """The same failure at the public call site, which is where it bit.

        The plates are offset rather than identical for the reason above.
        """
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        construction = _concrete(model)
        ground = _slab(model, "Ground", 0.0, 0.0, construction=construction)
        for index, elevation in enumerate([3.0, 6.0, 9.0]):
            _slab(model, f"Plate {index}", 5.0, 0.0, construction=construction,
                  elevation=elevation, boundary="Surface")

        result = foundations.create_kiva_foundation(model, ground)
        self.assertTrue(result["created"], result["refusals"])
        self.assertAlmostEqual(result["perimeter_m"], 40.0, places=3)

    def test_coincident_floors_are_reported_rather_than_zeroed(self):
        """Two floors on the same footprint cover each other completely, so
        each would measure 0.0 m and both be refused. A twin is excluded from
        its twin's neighbours and named instead."""
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        construction = _concrete(model)
        first = _slab(model, "Twin A", 0.0, 0.0, construction=construction)
        second = _slab(model, "Twin B", 0.0, 0.0, construction=construction)
        measured = foundations.exposed_perimeters(model, [first, second])

        self.assertAlmostEqual(measured["perimeters"]["Twin A"], 40.0, places=3)
        self.assertAlmostEqual(measured["perimeters"]["Twin B"], 40.0, places=3)
        self.assertEqual(
            measured["duplicates"],
            [{"floor": "Twin A", "duplicates": ["Twin B"]},
             {"floor": "Twin B", "duplicates": ["Twin A"]}])

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
class TestDefaultedConstructions(unittest.TestCase):
    """A DEFAULTED construction does not survive the boundary flip.

    A surface whose construction comes from a DefaultConstructionSet has no
    construction at all once its boundary condition reads `Foundation`: the
    default set maps Ground but not Foundation, so `construction()` returns
    None — and returns the object again if the boundary is reverted.

    Nothing refuses it. `kiva_blockers` ran while the surface was still
    `Ground`, and the forward translator writes `BuildingSurface:Detailed` with
    a BLANK Construction Name and emits NO error. EnergyPlus then reports
    `Missing required property 'construction_name'` and FATALS, which the
    pipeline attributes to the SUBMITTED model — the misattribution the
    architecture exists to prevent.

    Found by Fable on PR #133. 587 of the 588 ground floors in the shipped
    archetypes are defaulted, and six of them took a foundation without also
    taking an explicit construction clone, making their archetypes
    unsimulatable. Every corpus fixture carries a CP02 layer and so gets a
    clone, which is why 2273 tests, 56 scenarios and five green CI jobs were
    all blind to it.
    """

    def _defaulted_slab(self):
        import openstudio

        model = openstudio.model.Model()
        construction = _concrete(model)
        floor = _slab(model, "Slab", 0.0, 0.0)   # NO explicit construction
        space = floor.space().get()
        default_set = openstudio.model.DefaultConstructionSet(model)
        surfaces = openstudio.model.DefaultSurfaceConstructions(model)
        surfaces.setFloorConstruction(construction)
        default_set.setDefaultGroundContactSurfaceConstructions(surfaces)
        space.setDefaultConstructionSet(default_set)
        return model, floor

    def test_the_sdk_really_drops_a_defaulted_construction_on_the_flip(self):
        """The CONTROL: without the fix this is what happens, so a reader can
        see the hazard is real rather than taking the guard on trust."""
        from btap._compat import opt

        model, floor = self._defaulted_slab()
        self.assertTrue(floor.isConstructionDefaulted())
        self.assertIsNotNone(opt(floor.construction()))

        floor.setOutsideBoundaryCondition("Foundation")
        self.assertIsNone(opt(floor.construction()),
                          "if this ever stops being None the pin below is "
                          "no longer needed")
        floor.setOutsideBoundaryCondition("Ground")
        self.assertIsNotNone(opt(floor.construction()))

    def test_creating_a_foundation_keeps_the_defaulted_construction(self):
        from btap._compat import opt
        from btap.modeling.envelope import foundations

        model, floor = self._defaulted_slab()
        before = opt(floor.construction()).nameString()

        result = foundations.create_kiva_foundation(model, floor)

        self.assertTrue(result["created"], result["refusals"])
        self.assertEqual("Foundation", floor.outsideBoundaryCondition())
        kept = opt(floor.construction())
        self.assertIsNotNone(
            kept, "a Foundation surface with no construction FATALS in "
                  "EnergyPlus with 'Missing required property construction_name'")
        self.assertEqual(before, kept.nameString())
        self.assertFalse(floor.isConstructionDefaulted(),
                         "the resolved construction must be pinned explicitly, "
                         "because the default set cannot resolve Foundation")

    def test_a_refused_write_hands_the_construction_back_to_the_default_set(self):
        """The pin is part of the attempt, so the rollback must undo it: a
        refused call leaves no explicit assignment the caller did not have."""
        import unittest.mock

        from btap.modeling.envelope import foundations

        model, floor = self._defaulted_slab()

        def created_then_discarded(surface, perimeter_m):
            surface.createSurfacePropertyExposedFoundationPerimeter(
                "TotalExposedPerimeter", perimeter_m)
            return "injected: the SDK discarded the value"

        with unittest.mock.patch.object(
                foundations, "_write_exposed_perimeter",
                side_effect=created_then_discarded):
            result = foundations.create_kiva_foundation(model, floor)

        self.assertFalse(result["created"])
        self.assertEqual("Ground", floor.outsideBoundaryCondition())
        self.assertTrue(floor.isConstructionDefaulted(),
                        "the surface must go back to being defaulted")


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

    def test_a_non_finite_perimeter_is_refused_and_the_model_restored(self):
        """The only public route to the rollback, and what it has to undo.

        NaN passes every comparison and inf passes the small-value gate, so
        both would reach the SDK write and be discarded there. `kiva.remove()`
        alone is NOT a rollback: it clears `adjacentFoundation` and leaves the
        surface reading 'Foundation', which forward-translates to a BLANK
        Foundation reference that EnergyPlus resolves to its own default
        Foundation:Kiva — a model the caller was told was unmodified would run
        WITH a foundation. Found by Fable on PR #132.
        """
        import openstudio

        from btap.modeling.envelope import foundations

        for bad in (float("nan"), float("inf")):
            with self.subTest(perimeter=bad):
                model = openstudio.model.Model()
                floor = _slab(model, "Slab", 0.0, 0.0,
                              construction=_concrete(model), boundary="Outdoors")
                result = foundations.create_kiva_foundation(
                    model, floor, perimeter_m=bad)

                self.assertFalse(result["created"])
                self.assertTrue(any("not a finite length" in r
                                    for r in result["refusals"]),
                                result["refusals"])
                # The model is as it was, including the derived exposures.
                self.assertEqual(floor.outsideBoundaryCondition(), "Outdoors")
                self.assertEqual(floor.sunExposure(), "SunExposed")
                self.assertEqual(len(model.getFoundationKivas()), 0)
                self.assertFalse(
                    floor.surfacePropertyExposedFoundationPerimeter().is_initialized())

    def test_a_failed_write_restores_every_boundary_condition(self):
        """The rollback, witnessed by INJECTING the failure it exists for.

        No input can reach it any more: the non-finite refusal and the
        small-value gate between them leave only values the SDK accepts, so
        deleting the restore loop leaves the rest of this file green. That is
        the unwitnessed-guard pattern, and the honest fix is to drive the real
        call site with a realistic fault rather than to delete the guard or
        claim it is covered.

        What it must undo: `kiva.remove()` clears `adjacentFoundation` but
        leaves the surface reading 'Foundation'. A surface in that state
        forward-translates to a BLANK Foundation reference, which EnergyPlus
        resolves to its own default Foundation:Kiva — so a model the caller was
        told was unmodified would run WITH a foundation.
        """
        import unittest.mock

        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        construction = _concrete(model)
        floor = _slab(model, "Slab", 0.0, 0.0, construction=construction,
                      boundary="Outdoors")
        space = floor.space().get()
        walls = [_wall(model, space, f"Wall {i}", i * 1.0, construction)
                 for i in range(2)]
        before = {s.nameString(): s.outsideBoundaryCondition()
                  for s in [floor] + walls}
        self.assertEqual(before["Slab"], "Outdoors")

        # The injected fault MATCHES the real hazard: the SDK creates the
        # perimeter object and then discards the value, so the object is
        # present when the write reports failure. A mock that merely returns a
        # reason without creating it leaves the rollback's
        # resetSurfacePropertyExposedFoundationPerimeter() unwitnessed.
        def created_then_discarded(surface, perimeter_m):
            surface.createSurfacePropertyExposedFoundationPerimeter(
                "TotalExposedPerimeter", perimeter_m)
            return "injected: the SDK discarded the value"

        with unittest.mock.patch.object(
                foundations, "_write_exposed_perimeter",
                side_effect=created_then_discarded):
            result = foundations.create_kiva_foundation(model, floor, walls)

        self.assertFalse(result["created"])
        self.assertIn("injected", result["refusals"][0])
        # Nothing of the attempt survives.
        self.assertEqual(len(model.getFoundationKivas()), 0)
        for surface in [floor] + walls:
            self.assertEqual(surface.outsideBoundaryCondition(),
                             before[surface.nameString()])
            self.assertFalse(surface.adjacentFoundation().is_initialized())
        self.assertFalse(
            floor.surfacePropertyExposedFoundationPerimeter().is_initialized())
        # 'Outdoors' re-derives the exposures that 'Foundation' had cleared.
        self.assertEqual(floor.sunExposure(), "SunExposed")
        self.assertEqual(floor.windExposure(), "WindExposed")

    def test_a_rotated_wall_is_measured_by_its_true_length(self):
        """E11 under-counted any wall not aligned to the axes.

        A wall at 45 degrees projects to a 7.07 x 7.07 bounding box, so
        `max(x_extent, y_extent)` read 7.07 m for a 10 m wall. Five such walls
        (50 m true) against a 40 m slab edge were ACCEPTED, and EnergyPlus
        would Fatal on that model. The unrotated control is the comparison.
        """
        import openstudio

        from btap.modeling.envelope import foundations

        for rotation in (0.0, 45.0):
            with self.subTest(rotation=rotation):
                model = openstudio.model.Model()
                construction = _concrete(model)
                space = openstudio.model.Space(model)
                space.setName("Rotated")
                space.setDirectionofRelativeNorth(rotation)
                floor = _slab(model, "Slab", 0.0, 0.0, construction=construction,
                              space=space)
                walls = [_wall(model, space, f"Wall {i}", i * 1.0, construction)
                         for i in range(5)]

                result = foundations.create_kiva_foundation(model, floor, walls)
                self.assertFalse(result["created"])
                self.assertTrue(
                    any("50.000 m" in r and "40.000 m" in r
                        for r in result["refusals"]),
                    result["refusals"])

    def test_a_wall_with_too_many_vertices_is_refused(self):
        """Kiva walls are limited to four vertices."""
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        construction = _concrete(model)
        floor = _slab(model, "Slab", 0.0, 0.0, construction=construction)
        space = floor.space().get()
        points = openstudio.Point3dVector()
        for x, z in [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, -3.0), (0.0, -3.0)]:
            points.append(openstudio.Point3d(x, 0.0, z))
        wall = openstudio.model.Surface(points, model)
        wall.setName("Five Vertex Wall")
        wall.setSurfaceType("Wall")
        wall.setSpace(space)
        wall.setConstruction(construction)

        result = foundations.create_kiva_foundation(model, floor, [wall])
        self.assertFalse(result["created"])
        self.assertTrue(any("limited to 4" in r for r in result["refusals"]),
                        result["refusals"])

    def test_a_floor_with_no_construction_is_refused_not_crashed(self):
        """Without this branch the layer check raises AttributeError on None
        instead of refusing, which Fable's mutation M3 exposed."""
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        floor = _slab(model, "Slab", 0.0, 0.0)   # no construction

        self.assertIn("no construction assigned", foundations.kiva_blockers(floor))
        result = foundations.create_kiva_foundation(model, floor)
        self.assertFalse(result["created"])
        self.assertTrue(any("no construction assigned" in r
                            for r in result["refusals"]), result["refusals"])

    def test_a_space_less_surface_is_a_blocker_in_its_own_right(self):
        """`kiva_blockers` names it even though `world_vertices` also guards it,
        so the refusal does not depend on the perimeter measurement failing."""
        import openstudio

        from btap.modeling.envelope import foundations

        model = openstudio.model.Model()
        points = openstudio.Point3dVector()
        for x, y in [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]:
            points.append(openstudio.Point3d(x, y, 0.0))
        orphan = openstudio.model.Surface(points, model)
        orphan.setName("Orphan")
        orphan.setSurfaceType("Floor")

        self.assertIn("surface has no parent space",
                      foundations.kiva_blockers(orphan))

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
