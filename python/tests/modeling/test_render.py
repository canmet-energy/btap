"""The campus-repo 3D renderer port: crash-isolated glTF export + fallback
ladder + palette boost + <model-viewer> HTML with the geometry embedded as a
base64 data URI.

Port of btap-modeling/test/test_render.rb (D-79).
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from tests.support import needs_sdk


@needs_sdk
class TestRender(unittest.TestCase):
    def wizard_model(self):
        import btap.modeling as modeling
        return modeling.create(shape="rectangle", length=30.0, width=20.0,
                               above_ground_storys=2, floor_to_floor_height=3.5,
                               perimeter_zone_depth=3.0)

    def extract_gltf(self, html):
        m = re.search(r"data:model/gltf\+json;base64,([A-Za-z0-9+/=]+)", html)
        self.assertIsNotNone(m, "embedded glTF data URI present")
        return json.loads(base64.b64decode(m.group(1)))

    def test_render_happy_path_embeds_boosted_gltf(self):
        import btap.modeling as modeling
        from btap.audit import AuditLog

        audit = AuditLog()
        html = modeling.render(self.wizard_model(), audit=audit)

        self.assertIn("<model-viewer", html)
        self.assertIn("model-viewer.min.js", html,
                      "viewer component script tag present")
        self.assertNotIn("Approximate massing", html,
                         "clean model needs no fallback")

        gltf = self.extract_gltf(html)
        materials = {m["name"]: m["pbrMetallicRoughness"] for m in gltf["materials"]}
        wall = materials.get("Wall")
        self.assertIsNotNone(wall, "SDK glTF material names survive")
        self.assertAlmostEqual(0.84, wall["baseColorFactor"][0], delta=1e-6,
                               msg="campus palette applied (warm-sand wall)")
        self.assertAlmostEqual(0.65, wall["roughnessFactor"], delta=1e-6)
        self.assertEqual(0.0, wall["metallicFactor"])
        self.assertTrue(any(
            e["action"] == "3D geometry viewer produced (glTF embedded as data URI)"
            for e in audit.entries))

    def test_render_writes_standalone_page(self):
        import btap.modeling as modeling

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "view.html")
            fragment = modeling.render(self.wizard_model(), path=path)
            self.assertNotEqual("", fragment)
            page = Path(path).read_text(encoding="utf-8")
            self.assertTrue(page.startswith("<!DOCTYPE html>"))
            self.assertIn(fragment[:200], page)

    def test_ladder_falls_back_to_massing_shell(self):
        """The campus fallback ladder, exercised deterministically with an
        injected exporter: full export "crashes", massing-shell export
        succeeds."""
        from btap.modeling.geometry import render

        calls = []

        def exporter(ctrl, out):
            calls.append(ctrl)
            if not (ctrl.get("remove_subsurfaces") and "keep_surfaces" not in ctrl):
                return False
            Path(out).write_text('{"materials":[]}', encoding="utf-8")
            return True

        ok, note = render.export_repaired(
            "unused.osm", os.path.join(tempfile.gettempdir(), "l1.gltf"),
            exporter=exporter)
        self.assertTrue(ok)
        self.assertRegex(note, r"windows/doors omitted")
        self.assertEqual(False, calls[0]["remove_subsurfaces"],
                         "full export attempted first")

    def test_ladder_bisects_out_the_crashing_surface(self):
        """Bisection stage: one poisoned surface handle crashes any export
        containing it; the ladder must isolate exactly that handle and drop
        it."""
        import openstudio

        from btap.modeling.geometry import render

        model = self.wizard_model()
        with tempfile.TemporaryDirectory() as tmp:
            osm = os.path.join(tmp, "m.osm")
            model.save(openstudio.path(osm), True)
            handles = render.surface_handles(osm)
            self.assertGreater(len(handles), 4)
            bad = handles[3]

            def exporter(ctrl, out):
                keep = (ctrl["keep_surfaces"] if ctrl.get("keep_surfaces") is not None
                        else [h for h in handles
                              if h not in (ctrl.get("drop_surfaces") or [])])
                if not ctrl.get("remove_subsurfaces"):  # full export always "crashes"
                    return False
                if bad in keep:
                    return False
                Path(out).write_text('{"materials":[]}', encoding="utf-8")
                return True

            ok, note = render.export_repaired(osm, os.path.join(tmp, "out.gltf"),
                                              exporter=exporter)
            self.assertTrue(ok)
            self.assertRegex(note, r"1 bad surface\(s\) omitted")

    def test_worker_control_removes_subsurfaces(self):
        import openstudio

        from btap.modeling.geometry import render

        model = self.wizard_model()
        wall = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == "Outdoors"
                    and s.surfaceType() == "Wall")
        wall.setWindowToWallRatio(0.4)
        self.assertNotEqual(0, len(model.getSubSurfaces()))
        with tempfile.TemporaryDirectory() as tmp:
            osm = os.path.join(tmp, "m.osm")
            model.save(openstudio.path(osm), True)
            out = os.path.join(tmp, "shell.gltf")
            ok = render.run_export(osm, out, {"remove_subsurfaces": True})
            self.assertTrue(ok, "worker exports the massing shell")
            names = [m["name"]
                     for m in json.loads(Path(out).read_text(encoding="utf-8"))["materials"]]
            self.assertNotIn("Window", names, "sub-surfaces removed before export")


if __name__ == "__main__":
    unittest.main()
