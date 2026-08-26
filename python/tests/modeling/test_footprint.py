"""Measured-footprint gate (port of btap-modeling/test/test_footprint.rb): a
real GeoJSON outline plus a measured height builds valid zoned massing; the
SDK traps that make raw outlines fail (winding, non-decimating simplify,
mitre overlap at reflex corners) stay pinned."""

import json
import math
import unittest

from tests.support import FIXTURES, needs_sdk

try:
    import openstudio

    import btap.modeling as modeling
    from btap._compat import ruby_round
    from btap.modeling.geometry import footprint as fp
except ImportError:  # no SDK — @needs_sdk skips (or hard-fails) every test below
    openstudio = None
    modeling = None
    fp = None

# A real NRCan building-stock record (feature 870226c8, Ottawa K1P): 69
# vertices, 33 of them reflex, 5,266 m2 published area, 82.65 m measured.
# Kept verbatim so the traps it exposes cannot quietly stop being tested.
OTTAWA_TOWER = json.loads((FIXTURES / "footprint_ottawa_tower.json").read_text(encoding="utf-8"))
PUBLISHED_AREA = 5266.0
MEASURED_HEIGHT = 82.65


@needs_sdk
class TestFootprint(unittest.TestCase):
    def rect_ring(self, length=50.0, width=30.0):
        return fp.clockwise([openstudio.Point3d(x, y, 0)
                             for x, y in [(0, 0), (0, width), (length, width), (length, 0)]])

    # The tangent-plane projection has to reproduce the publisher's own area,
    # or every area downstream is wrong.
    def test_projection_reproduces_published_area(self):
        ring = fp.ring_from_geojson(OTTAWA_TOWER)
        outline = fp.normalize(fp.project(ring))
        self.assertAlmostEqual(PUBLISHED_AREA, fp.area(outline), delta=PUBLISHED_AREA * 0.005,
                               msg="projected area within 0.5% of published")
        self.assertEqual(69, len(outline), "no vertices lost to normalization")

    # THE trap: Space.fromFloorPrint wants clockwise-from-above and returns an
    # uninitialized Optional (no message) otherwise. normalize must always
    # deliver clockwise regardless of the source ring's winding.
    def test_normalize_forces_clockwise_either_way(self):
        ring = fp.ring_from_geojson(OTTAWA_TOWER)
        forward = fp.normalize(fp.project(ring))
        reversed_ = fp.normalize(fp.project(list(reversed(ring))))

        self.assertLess(fp.signed_area(forward), 0, "clockwise viewed from above")
        self.assertLess(fp.signed_area(reversed_), 0, "reversed input still comes back clockwise")
        self.assertAlmostEqual(fp.area(forward), fp.area(reversed_), delta=0.5)

        model = openstudio.model.Model()
        self.assertTrue(
            openstudio.model.Space.fromFloorPrint(fp.to_vector(forward), 3.048,
                                                  model).is_initialized(),
            "clockwise ring is accepted by the SDK")
        self.assertFalse(
            openstudio.model.Space.fromFloorPrint(fp.to_vector(list(reversed(forward))), 3.048,
                                                  model).is_initialized(),
            "counter-clockwise is silently rejected — this is why normalize exists")

    # openstudio.simplify only drops collinear points; it does NOT decimate.
    # Douglas-Peucker has to, or every storey carries 69 exterior walls.
    def test_decimate_where_sdk_simplify_will_not(self):
        outline = fp.normalize(fp.project(fp.ring_from_geojson(OTTAWA_TOWER)))
        self.assertEqual(
            len(outline), len(openstudio.simplify(fp.to_vector(outline), False, 1.0)) + 1,
            "SDK simplify removes at most a collinear point at 1 m — it does not decimate")

        coarse = fp.decimate(outline, 4.0)
        self.assertLess(len(coarse), 25, "Douglas-Peucker actually reduces the vertex count")
        self.assertLess(fp.signed_area(coarse), 0, "winding preserved")
        self.assertAlmostEqual(fp.area(outline), fp.area(coarse), delta=fp.area(outline) * 0.01,
                               msg="area preserved within 1%")
        self.assertEqual(len(outline), len(fp.decimate(outline, 0)), "tolerance 0 is a no-op")

    # The mitred offset is exact on a convex outline. If this drifts, every
    # core/perimeter area downstream is wrong.
    def test_core_and_perimeter_tiles_a_rectangle_exactly(self):
        plan = fp.core_and_perimeter(self.rect_ring(), 4.57)
        self.assertFalse(plan.get("rejected"),
                         "a plain rectangle must accept core and perimeter zoning")
        self.assertEqual(4, len(plan["perimeters"]), "one perimeter zone per outer edge")

        tiled = fp.area(plan["core"]) + sum(fp.area(quad) for quad in plan["perimeters"])
        self.assertAlmostEqual(1500.0, tiled, delta=0.001,
                               msg="core + perimeters tile the outline exactly")
        self.assertAlmostEqual((50.0 - (2 * 4.57)) * (30.0 - (2 * 4.57)),
                               fp.area(plan["core"]), delta=0.001)
        self.assertTrue(all(fp.signed_area(quad) < 0 for quad in plan["perimeters"]),
                        "every zone clockwise")

    # What actually decides whether an outline can carry core-and-perimeter
    # zoning is wall-run length against the offset depth, NOT vertex count or
    # concavity. The offset must report the outline's own ceiling, and
    # honouring it must be what recovers the zoning.
    def test_zoning_is_bounded_by_wall_runs_not_by_vertex_count(self):
        outline = fp.normalize(fp.project(fp.ring_from_geojson(OTTAWA_TOWER)))
        reflex = 0
        for i in range(len(outline)):
            a = outline[(i - 1) % len(outline)]
            b = outline[i]
            c = outline[(i + 1) % len(outline)]
            if (((b.x() - a.x()) * (c.y() - b.y())) - ((b.y() - a.y()) * (c.x() - b.x()))) > 0:
                reflex += 1
        self.assertGreater(reflex, 20, "fixture really is a reflex-heavy outline")

        raw = fp.core_and_perimeter(outline, 4.57)
        self.assertTrue(raw.get("rejected"),
                        "raw outline cannot carry a 15 ft perimeter and must be refused")
        self.assertRegex(raw["rejected"], r"lower perimeter_zone_depth",
                         "rejection names the real lever")

        # Decimating to 20 vertices does NOT rescue it: one wall run is still
        # 0.29 m short of surviving a 4.57 m offset, and that zone would
        # self-intersect.
        coarse = fp.decimate(outline, 4.0)
        ceiling = fp.max_perimeter_depth(coarse)
        self.assertAlmostEqual(4.46, ceiling, delta=0.05,
                               msg="the outline's own ceiling, reported not guessed")
        self.assertTrue(fp.core_and_perimeter(coarse, 4.57).get("rejected"),
                        "above the ceiling stays refused")

        # Honouring the reported ceiling is what makes it viable.
        plan = fp.core_and_perimeter(coarse, 3.0)
        self.assertFalse(plan.get("rejected"), "below the ceiling the same outline zones cleanly")
        self.assertLessEqual(plan["tiling_error"], fp.TILING_TOLERANCE)
        self.assertEqual(len(coarse), len(plan["perimeters"]), "one perimeter zone per wall run")

    # The ceiling is exact and derivable by hand: every edge of a rectangle
    # sits between two right angles, each eating D off it, so the limit is
    # half the short side.
    def test_max_perimeter_depth_is_exact_on_a_rectangle(self):
        self.assertAlmostEqual(15.0, fp.max_perimeter_depth(self.rect_ring(50.0, 30.0)),
                               delta=1e-9)
        self.assertAlmostEqual(3.0, fp.max_perimeter_depth(self.rect_ring(8.0, 6.0)), delta=1e-9)
        self.assertFalse(fp.core_and_perimeter(self.rect_ring(50.0, 30.0), 10.0).get("rejected"),
                         "well under the ceiling holds")
        self.assertTrue(fp.core_and_perimeter(self.rect_ring(50.0, 30.0), 15.1).get("rejected"),
                        "over the ceiling does not")

        # Geometrically viable is not the same as useful: at 14.9 m the offset
        # still closes, but the core is 0.27% of the floor. The sliver guard is
        # what stops that, and it fires before the geometry does.
        sliver = fp.core_and_perimeter(self.rect_ring(50.0, 30.0), 14.9)
        self.assertTrue(sliver.get("rejected"))
        self.assertRegex(sliver["rejected"], r"sliver")

    # 'auto' keeps the 15 ft convention where it fits and backs off only where
    # it must — and says so, because a reduced band is no longer the code
    # daylit zone.
    def test_auto_perimeter_depth_prefers_the_convention(self):
        self.assertAlmostEqual(fp.CONVENTIONAL_DEPTH,
                               fp.auto_perimeter_depth(self.rect_ring(50.0, 30.0)), delta=1e-9,
                               msg="a roomy outline keeps the full 15 ft")
        narrow = fp.auto_perimeter_depth(self.rect_ring(12.0, 9.0))
        self.assertLess(narrow, fp.CONVENTIONAL_DEPTH, "a tight outline is reduced")
        self.assertAlmostEqual(4.5 * 0.95, narrow, delta=1e-9,
                               msg="5% headroom off the outline ceiling")
        self.assertIsNone(fp.auto_perimeter_depth(self.rect_ring(3.0, 2.0)),
                          "below the useful minimum, no depth at all")

        audit = modeling.AuditLog()
        modeling.create_from_footprint(geojson=OTTAWA_TOWER, height_m=20.0,
                                       decimate_tolerance=4.0, audit=audit)
        reduced = next((w for w in audit.warnings
                        if "reduced below the 15 ft convention" in w["action"]), None)
        self.assertIsNotNone(reduced, "a non-conventional perimeter band must never be silent")
        self.assertLess(reduced["inputs"]["perimeter_zone_depth"], fp.CONVENTIONAL_DEPTH)
        self.assertEqual(fp.CONVENTIONAL_DEPTH, reduced["inputs"]["conventional_depth"])

    def test_core_and_perimeter_rejects_outline_too_narrow_for_a_core(self):
        plan = fp.core_and_perimeter(self.rect_ring(8.0, 6.0), 4.57)
        self.assertTrue(plan.get("rejected"))
        self.assertRegex(plan["rejected"], r"supports perimeter_zone_depth up to 3\.00 m",
                         "the rejection carries the number the caller needs")

    # Perimeter zones merge by compass bin: spaces stay one-per-edge (exact
    # geometry, no polygon union) while the ZONE each joins is its
    # orientation. The SDK's own Surface#azimuth is the ground truth for the
    # convention.
    def test_perimeter_zones_merge_by_orientation(self):
        model = modeling.create_from_footprint(
            points=self.rect_ring(50.0, 30.0), storeys=1, zoning="core_perimeter",
            perimeter_zone_depth=4.57)
        self.assertEqual(5, len(model.getSpaces()), "one space per edge plus the core")
        self.assertEqual(5, len(model.getThermalZones()), "N/E/S/W + core")
        self.assertEqual(["Story 0 Core ZN", "Story 0 East ZN", "Story 0 North ZN",
                          "Story 0 South ZN", "Story 0 West ZN"],
                         sorted(z.nameString() for z in model.getThermalZones()))

        # Every zone's exterior walls must actually face the way its name
        # claims.
        expected = {"North": 0, "East": 90, "South": 180, "West": 270}
        for zone in model.getThermalZones():
            bin_ = zone.nameString().split()[2]
            if bin_ == "Core":
                continue

            azimuths = sorted({ruby_round(s.azimuth() * 180 / math.pi)
                               for space in zone.spaces() for s in space.surfaces()
                               if s.surfaceType() == "Wall"
                               and s.outsideBoundaryCondition() == "Outdoors"})
            self.assertEqual([expected[bin_]], azimuths, f"{bin_} zone walls face {bin_}")
        core = next(z for z in model.getThermalZones() if "Core" in z.nameString())
        self.assertEqual([], [s for space in core.spaces() for s in space.surfaces()
                              if s.surfaceType() == "Wall"
                              and s.outsideBoundaryCondition() == "Outdoors"],
                         "the core has no exterior wall — that is what makes it a core")

    # The point of merging: a many-edged real outline collapses to the 4+1
    # zones a modeller expects, without a single wall landing in the wrong bin.
    def test_orientation_merge_collapses_a_real_outline(self):
        model = modeling.create_from_footprint(
            geojson=OTTAWA_TOWER, height_m=MEASURED_HEIGHT,
            floor_to_floor_height=fp.NRCAN_IMPLIED, decimate_tolerance=4.0, multiplier="mid")
        self.assertGreater(len(model.getSpaces()), 20, "still one space per edge per storey")
        self.assertEqual(15, len(model.getThermalZones()),
                         "5 zones x 3 storeys, not one per space")
        self.assertEqual(5, sum(1 for z in model.getThermalZones()
                                if z.nameString().startswith("Story 0 ")),
                         "exactly N/E/S/W + core on the ground storey")

        misfiled = 0
        for zone in model.getThermalZones():
            bin_ = zone.nameString().split()[2]
            if bin_ == "Core":
                continue

            misfiled += sum(
                1 for space in zone.spaces() for s in space.surfaces()
                if s.surfaceType() == "Wall" and s.outsideBoundaryCondition() == "Outdoors"
                and fp.ORIENTATIONS[math.floor(
                    (((s.azimuth() * 180 / math.pi) + 45) % 360) / 90)] != bin_)
        self.assertEqual(0, misfiled, "every exterior wall sits in its own compass bin")

        # zones must not span storeys — a multiplied storey needs its own zones
        self.assertEqual([1, 22], sorted({z.multiplier() for z in model.getThermalZones()}))

    # The azimuth convention is the SDK's, not one of our own invention.
    def test_edge_orientation_matches_sdk_azimuth(self):
        ring = self.rect_ring(50.0, 30.0)
        model = openstudio.model.Model()
        space = openstudio.model.Space.fromFloorPrint(fp.to_vector(ring), 3.0, model).get()
        sdk = sorted(ruby_round((s.azimuth() * 180 / math.pi) % 360)
                     for s in space.surfaces() if s.surfaceType() == "Wall")
        mine = sorted(ruby_round(fp.edge_azimuth(ring[i], ring[(i + 1) % len(ring)])) % 360
                      for i in range(len(ring)))
        self.assertEqual(sdk, mine, "edge_azimuth reproduces Surface#azimuth exactly")

        # bin boundaries sit at 45 degrees, and North wraps through 0
        def pt(x, y):
            return openstudio.Point3d(x, y, 0)

        self.assertEqual("North", fp.edge_orientation(pt(0, 0), pt(1, 0)))
        self.assertEqual("South", fp.edge_orientation(pt(1, 0), pt(0, 0)))
        self.assertEqual("West", fp.edge_orientation(pt(0, 0), pt(0, 1)))
        self.assertEqual("East", fp.edge_orientation(pt(0, 1), pt(0, 0)))

    # Windows are PURE GEOMETRY here: a caller-chosen ratio, no default, no
    # code knowledge. The NECB maximum belongs to btap.necb (envelope domain).
    def test_apply_wwr_scalar(self):
        model = modeling.create_from_footprint(points=self.rect_ring(50.0, 30.0), storeys=2,
                                               zoning="single")
        self.assertEqual(0, len(model.getSubSurfaces()),
                         "measured massing starts with no windows at all")

        audit = modeling.AuditLog()
        result = modeling.apply_wwr(model, 0.35, audit=audit)
        self.assertEqual(8, result["walls"], "4 walls x 2 storeys")
        self.assertEqual(8, result["glazed"])
        self.assertEqual(0, result["refused"])
        self.assertAlmostEqual(0.35, result["fdwr"], delta=1e-6,
                               msg="achieved ratio hits the request")
        self.assertEqual(8, len(model.getSubSurfaces()))

        entry = next(e for e in reversed(audit.entries) if "windows cut" in e["action"])
        self.assertEqual(0.35, entry["inputs"]["requested"])

    # Orientation-specific glazing — the companion to orientation-merged
    # zoning. A bin left out of the dict gets NO windows, it does not fall
    # back.
    def test_apply_wwr_per_orientation(self):
        model = modeling.create_from_footprint(points=self.rect_ring(50.0, 30.0), storeys=1,
                                               zoning="single")
        # both spellings must work: bins as keywords and an explicit dict
        modeling.apply_wwr(model, South=0.5, North=0.15)

        by_bin = {}
        for s in model.getSurfaces():
            if s.surfaceType() == "Wall" and s.outsideBoundaryCondition() == "Outdoors":
                by_bin.setdefault(fp.wall_orientation(s), []).append(s)
        self.assertAlmostEqual(
            0.5,
            sum(sum(ss.netArea() for ss in s.subSurfaces()) for s in by_bin["South"])
            / sum(s.grossArea() for s in by_bin["South"]), delta=1e-6)
        self.assertAlmostEqual(
            0.15,
            sum(sum(ss.netArea() for ss in s.subSurfaces()) for s in by_bin["North"])
            / sum(s.grossArea() for s in by_bin["North"]), delta=1e-6)
        self.assertEqual([], [ss for s in by_bin["East"] for ss in s.subSurfaces()],
                         "omitted bins get no windows")
        self.assertEqual([], [ss for s in by_bin["West"] for ss in s.subSurfaces()])

    # The seam with btap.necb (envelope domain): the NECB maximum is ITS rule
    # (3.2.1.4), this gem only cuts the opening. Pinned as a number so a
    # change in either gem is visible — HDD 4500 gives (2000 - 0.2*4500)/3000
    # by hand.
    def test_apply_wwr_accepts_an_externally_computed_necb_limit(self):
        model = modeling.create_from_footprint(points=self.rect_ring(50.0, 30.0), storeys=1,
                                               zoning="single")
        necb_limit_hdd4500 = (2000 - (0.2 * 4500)) / 3000.0
        self.assertAlmostEqual(0.3667, necb_limit_hdd4500, delta=0.0001)
        result = modeling.apply_wwr(model, necb_limit_hdd4500)
        self.assertAlmostEqual(necb_limit_hdd4500, result["fdwr"], delta=1e-6)

    def test_apply_wwr_rejects_bad_ratios(self):
        model = modeling.create_from_footprint(points=self.rect_ring(50.0, 30.0), storeys=1,
                                               zoning="single")
        with self.assertRaises(ValueError):
            modeling.apply_wwr(model, 1.0)
        with self.assertRaises(ValueError):
            modeling.apply_wwr(model, -0.1)
        with self.assertRaises(ValueError):
            modeling.apply_wwr(model, "lots")
        with self.assertRaises(ValueError):
            modeling.apply_wwr(model, {"South": 1.5})
        with self.assertRaises(ValueError):
            modeling.apply_wwr(model)

    # Keyword bins and an explicit dict must land in the same place — the
    # signature accepts the spellings on purpose (the Python analog of Ruby's
    # Hash / brace-less / Symbol trio).
    def test_apply_wwr_hash_spellings_agree(self):
        achieved = []
        for index in range(3):
            model = modeling.create_from_footprint(points=self.rect_ring(50.0, 30.0),
                                                   storeys=1, zoning="single")
            if index == 0:
                result = modeling.apply_wwr(model, {"South": 0.4})
            elif index == 1:
                result = modeling.apply_wwr(model, wwr={"South": 0.4})
            else:
                result = modeling.apply_wwr(model, South=0.4)
            achieved.append(result["fdwr"])
        self.assertEqual(1, len(set(achieved)), "dict, wwr= and keyword bins agree")
        self.assertGreater(achieved[0], 0.0)

    # Storey count comes from the measured height. The three plausible storey
    # heights give three different answers, which is exactly why it is an
    # input.
    def test_storeys_derived_from_measured_height(self):
        self.assertEqual(27, fp.storeys_for(MEASURED_HEIGHT, fp.TEN_FEET))
        self.assertEqual(24, fp.storeys_for(MEASURED_HEIGHT, fp.NRCAN_IMPLIED),
                         "matches the publisher's own estimated_floors")
        self.assertEqual(22, fp.storeys_for(MEASURED_HEIGHT, 3.8),
                         "gem-wide default storey height")
        self.assertEqual(1, fp.storeys_for(1.2, 3.8), "never less than one storey")
        with self.assertRaises(ValueError):
            fp.storeys_for(30.0, 0)

    def test_end_to_end_single_zone_massing(self):
        audit = modeling.AuditLog()
        model = modeling.create_from_footprint(
            geojson=OTTAWA_TOWER, height_m=MEASURED_HEIGHT, floor_to_floor_height=fp.TEN_FEET,
            zoning="single", decimate_tolerance=4.0, audit=audit,
            source={"feature_id": "870226c8", "dataset": "nrcan-buildings"})

        self.assertEqual(27, len(model.getSpaces()), "one space per storey at 10 ft floors")
        self.assertEqual(27, len(model.getBuildingStorys()))
        self.assertTrue(all(s.floorArea() > 0 for s in model.getSpaces()))
        self.assertAlmostEqual(PUBLISHED_AREA * 27, model.getBuilding().floorArea(),
                               delta=PUBLISHED_AREA * 27 * 0.01)

        ground = [s for s in model.getSpaces() if s.nameString().startswith("Story 0 ")]
        ground_floors = [srf for s in ground for srf in s.surfaces()
                         if srf.surfaceType() == "Floor"]
        self.assertTrue(all(s.outsideBoundaryCondition() == "Ground" for s in ground_floors),
                        "bottom storey meets the ground")
        self.assertGreater(
            sum(1 for s in model.getSurfaces() if s.outsideBoundaryCondition() == "Surface"),
            40, "storeys matched to each other")

        # site is georeferenced from the ring itself
        self.assertAlmostEqual(45.4214, model.getSite().latitude(), delta=0.01)
        self.assertAlmostEqual(-75.6977, model.getSite().longitude(), delta=0.01)

    def test_end_to_end_core_perimeter_and_story_multiplier(self):
        audit = modeling.AuditLog()
        model = modeling.create_from_footprint(
            geojson=OTTAWA_TOWER, height_m=MEASURED_HEIGHT,
            floor_to_floor_height=fp.NRCAN_IMPLIED, zoning="core_perimeter",
            perimeter_zone_depth=3.0, decimate_tolerance=4.0, multiplier="mid", audit=audit)

        self.assertEqual(3, len(model.getBuildingStorys()), "ground / multiplied middle / top")
        per_storey = len(model.getSpaces()) // 3
        self.assertGreater(per_storey, 4, "core plus one perimeter zone per outer edge")
        self.assertEqual(22, max(z.multiplier() for z in model.getThermalZones()),
                         "24 storeys - 2 real ones")

        entry = next(e for e in reversed(audit.entries)
                     if e["step"] == "geometry" and "measured-footprint" in e["action"])
        self.assertEqual("core_perimeter", entry["inputs"]["zoning"])
        self.assertEqual(24, entry["inputs"]["storeys_above"])
        self.assertAlmostEqual(MEASURED_HEIGHT, entry["inputs"]["modelled_height_m"], delta=2.0)

        adiabatic = sum(1 for s in model.getSurfaces()
                        if s.outsideBoundaryCondition() == "Adiabatic")
        self.assertGreater(adiabatic, 0,
                           "multiplied storey does not leak through unmatched floors/ceilings")

    # Provenance is the whole reason this lives in the gem: a measured massing
    # is only reproducible if the audit records what it was measured from.
    def test_audit_records_full_provenance(self):
        audit = modeling.AuditLog()
        modeling.create_from_footprint(
            geojson=OTTAWA_TOWER, height_m=MEASURED_HEIGHT, decimate_tolerance=4.0,
            source={"feature_id": "870226c8", "dataset": "nrcan-buildings",
                    "height_field": "height_max_m"},
            audit=audit)
        inputs = next(e for e in reversed(audit.entries)
                      if e["step"] == "geometry" and "measured-footprint" in e["action"])["inputs"]

        self.assertEqual("870226c8", inputs["feature_id"])
        self.assertEqual("nrcan-buildings", inputs["dataset"])
        self.assertEqual("height_max_m", inputs["height_field"])
        self.assertEqual(MEASURED_HEIGHT, inputs["height_m"])
        self.assertEqual(3.8, inputs["floor_to_floor_height"],
                         "the assumption is recorded, not buried")
        self.assertEqual(70, inputs["vertices_raw"], "as supplied, closing vertex included")
        self.assertLess(inputs["vertices_used"], 70)
        self.assertEqual(4.0, inputs["decimate_tolerance"])

    # Degradation must be loud: a noisy outline gets single-zone storeys AND a
    # warning naming the reason, never a silent overlap.
    def test_zoning_degrades_loudly(self):
        audit = modeling.AuditLog()
        model = modeling.create_from_footprint(
            geojson=OTTAWA_TOWER, height_m=20.0, zoning="core_perimeter",
            perimeter_zone_depth=4.57, decimate_tolerance=0, audit=audit)
        warning = next((w for w in audit.warnings if w.get("inputs", {}).get("reason")), None)
        self.assertIsNotNone(warning, "silent degradation is a family contract violation")
        self.assertRegex(warning["inputs"]["reason"], r"raise decimate_tolerance",
                         "warning names the fix")

        entry = next(e for e in reversed(audit.entries)
                     if e["step"] == "geometry" and "measured-footprint" in e["action"])
        self.assertEqual("single", entry["inputs"]["zoning"])
        self.assertEqual("core_perimeter", entry["inputs"]["requested_zoning"])
        self.assertEqual(5, len(model.getSpaces()), "one space per storey after the fallback")

    def test_geojson_shapes_accepted(self):
        ring = fp.ring_from_geojson(OTTAWA_TOWER)
        self.assertEqual(ring, fp.ring_from_geojson(json.dumps(OTTAWA_TOWER)),
                         "raw JSON string")
        self.assertEqual(ring, fp.ring_from_geojson({"geometry": OTTAWA_TOWER}),
                         "wrapped in a Feature")
        self.assertEqual(ring, fp.ring_from_geojson(ring),
                         "a bare [[lon, lat], ...] ring passes through")

        multi = {"type": "MultiPolygon",
                 "coordinates": [[[[0, 0], [0, 1], [1, 1]]], OTTAWA_TOWER["coordinates"]]}
        self.assertEqual(ring, fp.ring_from_geojson(multi), "MultiPolygon takes the largest ring")
        with self.assertRaises(ValueError):
            fp.ring_from_geojson({"type": "LineString", "coordinates": [[0, 0]]})

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            modeling.create_from_footprint(height_m=20.0)
        with self.assertRaises(ValueError):
            modeling.create_from_footprint(geojson=OTTAWA_TOWER)
        with self.assertRaises(ValueError):
            modeling.create_from_footprint(geojson=OTTAWA_TOWER, points=[], height_m=20.0)
        with self.assertRaises(ValueError):
            modeling.create_from_footprint(geojson=OTTAWA_TOWER, height_m=20.0,
                                           zoning="perimeter_only")
        with self.assertRaises(ValueError):
            modeling.create_from_footprint(geojson=OTTAWA_TOWER, height_m=20.0,
                                           multiplier="all")
        with self.assertRaises(ValueError):
            fp.project([[0, 0], [1, 1]])


if __name__ == "__main__":
    unittest.main()
