"""Per-storey floor plans: the SDK extraction (world coordinates, floor
surfaces, storey grouping), the SDK-free SVG layer (fills, labels, tooltips,
legend) and the self-contained standalone page.

Port of btap-modeling/test/test_floor_plan.rb (D-79).
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import needs_sdk

PY_ROOT = Path(__file__).resolve().parents[2]


@needs_sdk
class TestFloorPlan(unittest.TestCase):
    # 15 spaces / 3 storeys (test_wizards.rb:9-32), 40 x 25 m footprint,
    # 4 m perimeter depth => a core space of exactly 32 x 17 m.
    def wizard_model(self, storeys=2, below=1):
        import btap.modeling as modeling
        return modeling.create(shape="rectangle", length=40.0, width=25.0,
                               storeys=storeys, below_grade_storeys=below,
                               floor_to_floor_height=3.6, perimeter_zone_depth=4.0)

    # The wizards zone SPACES, not thermal zones — give every space its own
    # zone so the zone-dependent drawing rules (fill, second label line) are
    # exercised.
    def zone_every_space(self, model):
        import openstudio

        from btap._compat import sorted_by_name
        for space in sorted_by_name(model.getSpaces()):
            zone = openstudio.model.ThermalZone(model)
            zone.setName(f"Zone {space.nameString()}")
            space.setThermalZone(zone)
        return model

    def bar_model(self):
        import btap.modeling as modeling
        return modeling.bar(
            space_type_ratios={("Space Function", "Office enclosed > 25 m2"): 0.7,
                               ("Space Function", "Corridor/Transition area other-sch-A"): 0.3},
            length=50.0, width=20.0, storeys=2, wwr=0.4)

    # Even-odd point-in-polygon (used to prove a courtyard void is really
    # void).
    def inside(self, ring, px, py):
        hits = False
        for index, (x1, y1) in enumerate(ring):
            x2, y2 = ring[(index + 1) % len(ring)]
            if (y1 > py) == (y2 > py):
                continue
            if px < (((x2 - x1) * (py - y1)) / (y2 - y1)) + x1:
                hits = not hits
        return hits

    # ------------------------------------------------------------- extraction

    def test_multi_storey_wizard_numeric_polygons(self):
        from btap.audit import AuditLog
        from btap.modeling.geometry import plan_query as query

        audit = AuditLog()
        data = query.extract(self.wizard_model(), audit=audit)

        self.assertFalse(data["inferred_storeys"],
                         "the wizard sets BuildingStorys — nothing to infer")
        self.assertEqual(["Story 0", "Story 1", "Story 2"],
                         [s["name"] for s in data["storeys"]],
                         "storeys in display order = ascending world z")
        self.assertEqual([-3.6, 0.0, 3.6], [s["z"] for s in data["storeys"]])
        self.assertEqual([5, 5, 5], [len(s["spaces"]) for s in data["storeys"]])
        self.assertEqual({"min_x": 0.0, "min_y": 0.0, "max_x": 40.0, "max_y": 25.0},
                         data["bounds"])

        core = next((s for s in data["storeys"][1]["spaces"]
                     if s["name"] == "Story 1 Core Space"), None)
        self.assertIsNotNone(core, "core space extracted")
        self.assertEqual([[[4.0, 4.0], [4.0, 21.0], [36.0, 21.0], [36.0, 4.0]]],
                         core["polygons"],
                         "world-coordinate ring, 4 m perimeter depth inset on every side")
        self.assertAlmostEqual(32.0 * 17.0, core["area_m2"], delta=0.01)
        self.assertEqual([20.0, 12.5], core["centroid"])
        self.assertEqual(0.0, core["z"])

        # every extracted area sums to the model's own floor area
        total = sum(sp["area_m2"] for s in data["storeys"] for sp in s["spaces"])
        self.assertAlmostEqual(40.0 * 25.0 * 3, total, delta=0.5)
        self.assertEqual([], audit.warnings,
                         "a clean wizard model produces no plan warnings")

    def test_multi_floor_space_keeps_the_lowest_set(self):
        """A space whose floors sit at two elevations (mezzanine modelled as
        one space) is cut at the LOWEST plane — a plan is one horizontal
        cut."""
        import openstudio

        from btap.modeling.geometry import plan_query as query

        model = openstudio.model.Model()
        space = openstudio.model.Space(model)
        space.setName("Mezz Space")
        for ring in [[[0, 0, 0], [0, 10, 0], [10, 10, 0], [10, 0, 0]],
                     [[0, 0, 3], [0, 4, 3], [4, 4, 3], [4, 0, 3]]]:
            vertices = openstudio.Point3dVector()
            for x, y, z in ring:
                vertices.append(openstudio.Point3d(x, y, z))
            openstudio.model.Surface(vertices, model).setSpace(space)

        record = query.extract(model)["storeys"][0]["spaces"][0]
        self.assertEqual(1, len(record["polygons"]),
                         "only the lowest floor plane is drawn")
        self.assertAlmostEqual(100.0, record["area_m2"], delta=0.01)

    def test_floorless_space_is_warned_and_skipped(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.modeling.geometry import plan_query as query

        model = self.wizard_model(storeys=1, below=0)
        bare = openstudio.model.Space(model)
        bare.setName("Shaft (no floor)")

        audit = AuditLog()
        data = query.extract(model, audit=audit)
        names = [sp["name"] for s in data["storeys"] for sp in s["spaces"]]
        self.assertNotIn("Shaft (no floor)", names)
        warning = next((e for e in audit.warnings
                        if e.get("target") == "Shaft (no floor)"), None)
        self.assertIsNotNone(warning, "the skip is audited, never silent")
        self.assertRegex(warning["action"], r"no Floor surface")

    def test_rotation_regression_world_coordinates(self):
        """The xOrigin trap's regression test. BTAP's rotate_model
        re-expresses each space in a rotated LOCAL frame while leaving the
        building where it stands, so `space.transformation() * vertices` must
        be invariant — while the rotation-blind `xOrigin + local vertex`
        shortcut now yields garbage."""
        from btap._compat import ruby_round
        from btap.modeling.geometry import helpers
        from btap.modeling.geometry import plan_query as query

        model = self.wizard_model(storeys=1, below=0)
        before = query.extract(model)
        space = min(model.getSpaces(), key=lambda s: s.nameString())
        floor = next(s for s in space.surfaces() if s.surfaceType() == "Floor")
        local_before = [[ruby_round(p.x(), 3), ruby_round(p.y(), 3)]
                        for p in floor.vertices()]

        helpers.rotate_model(model, 90)
        after = query.extract(model)

        local_after = [[ruby_round(p.x(), 3), ruby_round(p.y(), 3)]
                       for p in floor.vertices()]
        self.assertNotEqual(local_before, local_after,
                            "rotate_model DID move the local frame")
        self.assertAlmostEqual(-90.0, space.directionofRelativeNorth(), delta=1e-6)
        self.assertEqual(before["storeys"][0]["spaces"], after["storeys"][0]["spaces"],
                         "world coordinates are invariant — the building did not move")

        naive = [[ruby_round(space.xOrigin() + x, 3), ruby_round(space.yOrigin() + y, 3)]
                 for x, y in local_after]
        world = next(s for s in after["storeys"][0]["spaces"]
                     if s["name"] == space.nameString())["polygons"][0]
        self.assertNotEqual(world, naive,
                            "the rotation-blind xOrigin shortcut disagrees — never use it")

    def test_rigid_rotation_moves_the_polygons(self):
        """...and a genuine rigid rotation of the building MUST move the
        polygons: +90 deg about z maps (x, y) -> (-y, x)."""
        import openstudio

        from btap._compat import ruby_round
        from btap.modeling.geometry import plan_query as query

        model = self.wizard_model(storeys=1, below=0)
        before = query.extract(model)
        rotation = openstudio.Transformation.rotation(
            openstudio.Vector3d(0, 0, 1), math.pi / 2)
        for space in model.getSpaces():
            space.setTransformation(rotation * space.transformation())
        after = query.extract(model)

        for index, space in enumerate(before["storeys"][0]["spaces"]):
            rotated = after["storeys"][0]["spaces"][index]
            self.assertEqual(space["name"], rotated["name"])
            expected = [[[ruby_round(-y, 3), ruby_round(x, 3)] for x, y in ring]
                        for ring in space["polygons"]]
            self.assertEqual(expected, rotated["polygons"])
            self.assertAlmostEqual(space["area_m2"], rotated["area_m2"], delta=0.01)
        self.assertEqual({"min_x": -25.0, "min_y": 0.0, "max_x": 0.0, "max_y": 40.0},
                         after["bounds"])

    def test_no_storey_fallback_infers_levels(self):
        from btap.audit import AuditLog
        from btap.modeling.geometry import plan_query as query

        model = self.wizard_model()
        for story in model.getBuildingStorys():
            story.remove()
        self.assertEqual(0, len(model.getBuildingStorys()))

        audit = AuditLog()
        data = query.extract(model, audit=audit)
        self.assertTrue(data["inferred_storeys"], "the fallback flags itself")
        self.assertEqual(["Level 1", "Level 2", "Level 3"],
                         [s["name"] for s in data["storeys"]])
        self.assertEqual([-3.6, 0.0, 3.6], [s["z"] for s in data["storeys"]])
        self.assertEqual([5, 5, 5], [len(s["spaces"]) for s in data["storeys"]])
        warning = next((e for e in audit.warnings
                        if "storeys inferred" in e["action"]), None)
        self.assertIsNotNone(warning, "inference is audited, never silent")
        self.assertRegex(warning["action"], r"no BuildingStory objects")

    def test_courtyard_void_is_a_hole(self):
        """The courtyard void is space-less: no polygon covers the courtyard
        centre, although the bounds enclose it."""
        import btap.modeling as modeling
        from btap.modeling.geometry import plan_query as query

        model = modeling.create(shape="courtyard", length=50.0, width=30.0,
                                courtyard_length=15.0, courtyard_width=5.0, storeys=1)
        data = query.extract(model)
        self.assertEqual({"min_x": 0.0, "min_y": 0.0, "max_x": 50.0, "max_y": 30.0},
                         data["bounds"])

        rings = [ring for space in data["storeys"][0]["spaces"]
                 for ring in space["polygons"]]
        self.assertGreaterEqual(len(rings), 12, "every courtyard space renders a ring")
        self.assertFalse(any(self.inside(ring, 25.0, 15.0) for ring in rings),
                         "the courtyard centre is void")
        self.assertTrue(any(self.inside(ring, 1.0, 15.0) for ring in rings),
                        "the west band is solid")

    # ------------------------------------------------------------- SVG layer

    def test_bar_model_space_type_tooltips(self):
        from btap.modeling.geometry import plan as plan_mod

        bundle = plan_mod.diagrams(self.bar_model())
        self.assertFalse(bundle["empty"])
        svg = bundle["storeys"][0]["svg"]
        self.assertIn("Space Function | Office enclosed &gt; 25 m2", svg,
                      "NECB standards tags reach the tooltip (escaped)")
        self.assertIn("Space Function | Corridor/Transition area other-sch-A", svg)
        self.assertRegex(svg, r"<title>[^<]+ \| [^<]+ \| [^<]+ \| [\d.]+ m²</title>")
        self.assertIn("Thermal zones", bundle["legend_svg"])

    def test_sdk_free_layer_on_a_hand_written_hash(self):
        """The whole drawing layer is SDK-FREE: a hand-written dict is
        enough."""
        from btap.modeling.geometry import plan_svg as svg_mod

        storey = {"name": "Level 1", "z": 0.0,
                  "spaces": [{"name": "Big", "zone": "Zone A", "space_type": "Office",
                              "polygons": [[[0, 0], [0, 10], [20, 10], [20, 0]]],
                              "centroid": [10.0, 5.0], "area_m2": 200.0},
                             {"name": "Tiny", "zone": None, "space_type": None,
                              "polygons": [[[0, 0], [0, 1], [1, 1], [1, 0]]],
                              "centroid": [0.5, 0.5], "area_m2": 1.0}]}
        svg = svg_mod.storey_svg(storey, bounds={"min_x": 0.0, "min_y": 0.0,
                                                 "max_x": 20.0, "max_y": 10.0})

        self.assertTrue(svg.startswith('<svg viewBox="0 0 920.0 486.0"'),
                        f"unexpected header: {svg[:80]}")
        self.assertNotRegex(svg, r"<svg[^>]*\bwidth=",
                            "fit-to-width: no width/height attributes (necb convention)")
        self.assertNotRegex(svg, r"<svg[^>]*\bheight=")

        # y is FLIPPED: building (0,0) is bottom-left, svg (26, 460) is
        # bottom-left.
        self.assertIn("26.0,460.0", svg)
        self.assertIn("894.0,26.0", svg)

        self.assertIn("<title>Big | Zone A | Office | 200.0 m²</title>", svg)
        self.assertIn("<title>Tiny | unassigned | no space type | 1.0 m²</title>", svg,
                      "tooltip present even for an unlabelled shape")
        self.assertIn(">Big<", svg)
        self.assertIn(">Zone A<", svg, "second label line is the zone name")
        self.assertNotIn(">Tiny<", svg,
                         "a 1 m x 1 m space is too small for legible text")
        self.assertIn(svg_mod.zone_color("Zone A"), svg, "zone fill applied")
        self.assertIn(svg_mod.NO_ZONE_FILL, svg, "zone-less space is white")

    def test_zone_palette_is_deterministic(self):
        # NOT the language string hash (seeded per process — Ruby's
        # String#hash, Python's hash() via PYTHONHASHSEED) — the same zone
        # must get the same color in every run and every document.
        from btap.modeling.geometry import plan_svg as svg_mod

        self.assertEqual("hsl(202, 45%, 65%)", svg_mod.zone_color("Zone A"))
        self.assertEqual(svg_mod.zone_color("Zone A"), svg_mod.zone_color("Zone A"))
        self.assertNotEqual(svg_mod.zone_color("Zone A"), svg_mod.zone_color("Zone B"))
        self.assertEqual(svg_mod.NO_ZONE_FILL, svg_mod.zone_color(None))

        other = subprocess.run(
            [sys.executable, "-c",
             "import sys; from btap.modeling.geometry import plan_svg; "
             "sys.stdout.write(plan_svg.zone_color('Zone A'))"],
            capture_output=True, text=True, cwd=str(PY_ROOT), check=True).stdout
        self.assertEqual(svg_mod.zone_color("Zone A"), other,
                         "stable across processes (the language seeds its string hash per process)")

    def test_legend_lists_every_zone_once(self):
        from btap.modeling.geometry import plan_svg as svg_mod

        legend = svg_mod.legend_svg(["Zone B", "Zone A", "Zone A", None])
        self.assertEqual(1, legend.count(">Zone A<"), "zones are de-duplicated")
        self.assertIn(">Zone B<", legend)
        self.assertIn(">unassigned<", legend)
        self.assertTrue(legend.startswith('<svg viewBox="0 0 920.0'))

    def test_empty_model_degrades_gracefully(self):
        import openstudio

        from btap.modeling.geometry import plan as plan_mod

        bundle = plan_mod.diagrams(openstudio.model.Model())
        self.assertTrue(bundle["empty"])
        self.assertEqual([], bundle["storeys"])
        self.assertIsNone(bundle["legend_svg"])

        html = plan_mod.page(bundle)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("No floor plans", html)

    # ------------------------------------------------------------- the page

    def test_standalone_page_is_self_contained(self):
        import btap.modeling as modeling
        from btap.audit import AuditLog

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plans.html")
            audit = AuditLog()
            bundle = modeling.floor_plans(self.zone_every_space(self.wizard_model()),
                                          path=path, audit=audit)

            self.assertEqual(3, len(bundle["storeys"]))
            # Explicit UTF-8: the page carries em dashes, 'm²' and ellipses
            # from plan_svg.py, so reading without an encoding picks up the
            # locale default and raises 'invalid byte sequence' wherever the
            # locale is not UTF-8 (the nrel/openstudio CI container).
            html = Path(path).read_text(encoding="utf-8")
            self.assertTrue(html.startswith("<!DOCTYPE html>"))
            self.assertEqual(3, html.count("<svg"),
                             "three storey plans and NOTHING else (the zone legend is "
                             "deliberately not on the page)")
            self.assertNotIn("Thermal zones", html,
                             "no zone legend on the page (redundant with the space inventory)")
            self.assertEqual(3, html.count('class="north-arrow"'),
                             "a north arrow on every storey plan")
            self.assertEqual(2, html.count('class="storey page-break"'),
                             "a page break before every storey but the first")
            self.assertIn("break-inside: avoid", html)
            self.assertIn("<details>", html,
                          "the only interactivity is native <details>")
            self.assertNotRegex(html, re.compile(r"<script", re.IGNORECASE), "no scripts")
            self.assertIn("Story 1 Core Space", html)
            self.assertIn("Zone Story 1 Core Space", html)

            # --- copied verbatim from test_catalog_report.rb:75-80
            self.assertNotRegex(html, re.compile(r"src\s*=\s*[\"']https?:", re.IGNORECASE),
                                "no remote src")
            self.assertNotRegex(html, re.compile(r"<link\b", re.IGNORECASE),
                                "no <link> (external stylesheet/asset)")
            self.assertNotRegex(html, re.compile(r"@import", re.IGNORECASE),
                                "no CSS @import")
            self.assertNotRegex(html, re.compile(r"url\(", re.IGNORECASE),
                                "no CSS url() references")
            self.assertNotRegex(html, re.compile(r"https?://(?!www\.w3\.org)", re.IGNORECASE),
                                "no external URLs except the SVG xmlns namespace")
            # --- end copied block

            entry = next((e for e in audit.entries
                          if e["step"] == "plan" and e["level"] == "decision"), None)
            self.assertIsNotNone(entry)
            self.assertEqual(3, entry["inputs"]["storeys"])
            self.assertEqual(15, entry["inputs"]["spaces"])

    def test_facade_accepts_an_osm_path(self):
        import openstudio

        import btap.modeling as modeling

        with tempfile.TemporaryDirectory() as tmp:
            osm = os.path.join(tmp, "m.osm")
            self.wizard_model(storeys=1, below=0).save(openstudio.path(osm), True)
            bundle = modeling.floor_plans(osm)
            self.assertEqual(1, len(bundle["storeys"]))
            self.assertFalse(bundle["empty"])

    def test_unloadable_path_never_raises(self):
        import btap.modeling as modeling
        from btap.audit import AuditLog

        audit = AuditLog()
        bundle = modeling.floor_plans("/nonexistent/nope.osm", audit=audit)
        self.assertTrue(bundle["empty"])
        self.assertIsNotNone(bundle.get("error"))
        self.assertNotEqual([], audit.warnings)

    # ------------------------------------------------------------- PNG (optional)

    def test_png_rasterizes_when_a_converter_exists(self):
        from btap.modeling.geometry import plan as plan_mod

        if plan_mod.rasterizer() is None:
            # M8: verify installs librsvg2-bin and sets the flag, so this can
            # never go green-but-vacuous there; elsewhere it names the tool.
            if os.environ.get("BTAP_RASTERIZER_REQUIRED") == "1":
                self.fail("BTAP_RASTERIZER_REQUIRED=1 but no SVG rasterizer "
                          "is on PATH (rsvg-convert / cairosvg / magick)")
            self.skipTest("no SVG rasterizer on PATH (rsvg-convert / cairosvg / magick)")

        with tempfile.TemporaryDirectory() as tmp:
            bundle = plan_mod.diagrams(self.wizard_model(storeys=1, below=0))
            written = plan_mod.pngs(bundle, tmp)
            self.assertEqual(len(bundle["storeys"]), len(written))
            for file in written:
                self.assertGreater(os.path.getsize(file), 0)

    def test_png_warns_loudly_when_no_rasterizer_exists(self):
        """The no-rasterizer path is deterministic everywhere: hide PATH."""
        from btap.audit import AuditLog
        from btap.modeling.geometry import plan as plan_mod

        original = os.environ.get("PATH", "")
        os.environ["PATH"] = ""
        try:
            audit = AuditLog()
            with tempfile.TemporaryDirectory() as tmp:
                result = plan_mod.png('<svg xmlns="http://www.w3.org/2000/svg"/>',
                                      os.path.join(tmp, "x.png"), audit=audit)
                self.assertIsNone(result, "no PNG, and no exception")
            warning = audit.warnings[0] if audit.warnings else None
            self.assertIsNotNone(warning)
            self.assertEqual("no SVG rasterizer found — PNG not produced",
                             warning["action"])
        finally:
            os.environ["PATH"] = original

    def test_north_arrow_rotation_follows_the_building_north_axis(self):
        from btap.modeling.geometry import plan_svg as svg_mod

        storey = {"name": "L1", "z": 0.0,
                  "spaces": [{"name": "S", "zone": "Z", "space_type": None,
                              "area_m2": 100.0, "centroid": [5.0, 5.0],
                              "polygons": [[[0.0, 0.0], [10.0, 0.0],
                                            [10.0, 10.0], [0.0, 10.0]]]}]}
        plain = svg_mod.storey_svg(storey)
        self.assertIn('class="north-arrow"', plain)
        self.assertIn("rotate(-0.0)", plain,
                      "no building rotation: north is straight up")

        rotated = svg_mod.storey_svg(storey, north_axis=90.0)
        self.assertIn("rotate(-90.0)", rotated,
                      "north axis 90 (building y faces east) points true north LEFT on the plan")

    def test_bundle_threads_the_model_north_axis_into_every_storey_svg(self):
        from btap.modeling.geometry import plan as plan_mod

        model = self.zone_every_space(self.wizard_model())
        model.getBuilding().setNorthAxis(30.0)
        bundle = plan_mod.diagrams(model)
        self.assertNotEqual([], bundle["storeys"])
        for storey in bundle["storeys"]:
            self.assertIn("rotate(-30.0)", storey["svg"])


if __name__ == "__main__":
    unittest.main()
