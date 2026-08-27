"""Article 4.2.2.2 — Lighting Controls in Storage Garages.

The repo has no storage-garage fixture (every .osm is the same 800 m2 office),
so these build geometry from scratch the way test_lighting_daylighting_necb2020.py
does. That is not incidental: (1) and (4) are geometric rules, and a fixture
with one zone and four windows could not exercise either.

Port of btap-necb/test/test_lighting_storage_garage.rb.
"""

import re
import unittest
from pathlib import Path

from tests.necb.support import needs_sdk


def surface(model, space, points, type_, boundary):
    import openstudio

    s = openstudio.model.Surface(openstudio.Point3dVector(points), model)
    s.setSpace(space)
    s.setSurfaceType(type_)
    s.setOutsideBoundaryCondition(boundary)
    return s


def garage(width=20.0, depth=15.0, height=3.0, wwr=0.0,
           space_type="Storage garage interior", building_type="Space Function"):
    """A rectangular garage. `wwr` glazes the y = 0 wall to that fraction of its
    gross area, which is what 4.2.2.2.(4)'s 40% threshold is measured against."""
    import openstudio

    model = openstudio.model.Model()
    space = openstudio.model.Space(model)
    space.setName("Garage")
    zone = openstudio.model.ThermalZone(model)
    space.setThermalZone(zone)

    floor = [openstudio.Point3d(x, y, 0)
             for x, y in [(0, 0), (width, 0), (width, depth), (0, depth)]]
    surface(model, space, list(reversed(floor)), "Floor", "Ground")
    surface(model, space, [openstudio.Point3d(p.x(), p.y(), height) for p in floor],
            "RoofCeiling", "Outdoors")

    wall = [openstudio.Point3d(0, 0, height), openstudio.Point3d(0, 0, 0),
            openstudio.Point3d(width, 0, 0), openstudio.Point3d(width, 0, height)]
    front = surface(model, space, wall, "Wall", "Outdoors")
    if wwr > 0:
        # A ribbon centred on the wall, sized to hit the requested ratio exactly.
        wh = height * wwr
        sub = [openstudio.Point3d(0, 0, wh), openstudio.Point3d(0, 0, 0),
               openstudio.Point3d(width, 0, 0), openstudio.Point3d(width, 0, wh)]
        window = openstudio.model.SubSurface(openstudio.Point3dVector(sub), model)
        window.setSurface(front)
        window.setSubSurfaceType("FixedWindow")
    for i, (x1, y1, x2, y2) in enumerate([(width, 0, width, depth), (width, depth, 0, depth),
                                          (0, depth, 0, 0)]):
        pts = [openstudio.Point3d(x1, y1, height), openstudio.Point3d(x1, y1, 0),
               openstudio.Point3d(x2, y2, 0), openstudio.Point3d(x2, y2, height)]
        surface(model, space, pts, "Wall", "Outdoors").setName(f"Side {i}")

    st = openstudio.model.SpaceType(model)
    st.setName(f"{building_type} {space_type}")
    st.setStandardsBuildingType(building_type)
    st.setStandardsSpaceType(space_type)
    st.setDefaultScheduleSet(openstudio.model.DefaultScheduleSet(model))
    space.setSpaceType(st)
    return model, space, st


def light(space_type, w_per_m2):
    import openstudio

    definition = openstudio.model.LightsDefinition(space_type.model())
    definition.setWattsperSpaceFloorArea(w_per_m2)
    openstudio.model.Lights(definition).setSpaceType(space_type)


def audit():
    from btap.audit import AuditLog
    return AuditLog()


def entry(log, article):
    return next((e for e in log.entries if str(e.get("article")).startswith(article)), None)


@needs_sdk
class TestStorageGarage(unittest.TestCase):
    @property
    def SG(self):
        from btap.necb.lighting import storage_garage
        return storage_garage

    @property
    def PERIM(self):
        from btap.necb.lighting.storage_garage import perimeter
        return perimeter

    # --- applicability -----------------------------------------------------

    def test_a_model_with_no_garage_is_not_subject_to_the_article(self):
        import openstudio

        model = openstudio.model.Model()
        log = audit()
        self.assertEqual({"applies": False}, self.SG.apply(model, audit=log))
        self.assertTrue(re.search(r"does not apply", entry(log, "4.2.2.2.")["action"]))

    # Table 4.2.1.6 lists emergency vehicle garages as required/required under
    # 4.2.2.1, so they are NOT deferred here and must not be swept in.
    def test_emergency_vehicle_garages_are_not_storage_garages(self):
        model, space, _st = garage(space_type="Emergency vehicle garage")  # noqa: F841
        self.assertFalse(self.SG.is_garage(space))

    def test_both_catalog_garage_rows_are_recognised(self):
        interior_model, interior, _st = garage(space_type="Storage garage interior")  # noqa: F841
        self.assertTrue(self.SG.is_garage(interior))
        whole_model, whole, _st2 = garage(space_type="WholeBuilding",  # noqa: F841
                                          building_type="Storage garage")
        self.assertTrue(self.SG.is_garage(whole))

    # --- (1) zoning --------------------------------------------------------

    def test_a_zone_within_360_m2_passes(self):
        model, _, _ = garage(width=20.0, depth=15.0)   # 300 m2
        log = audit()
        self.SG.apply(model, audit=log)
        e = entry(log, "4.2.2.2.(1)")
        self.assertEqual("decision", e["level"])
        self.assertTrue(re.search(r"within the 360 m2 limit", e["action"]))

    def test_an_oversized_zone_is_a_shouted_finding(self):
        model, _, _ = garage(width=40.0, depth=15.0)   # 600 m2
        log = audit()
        self.SG.apply(model, audit=log)
        e = entry(log, "4.2.2.2.(1)")
        self.assertEqual("warning", e["level"])
        self.assertTrue(re.search(r"EXCEEDS 360 m2", e["action"]), "violations are SHOUTED")

    # --- (4) the geometry that did not exist -------------------------------

    def test_opening_ratio_is_net_over_gross_per_wall(self):
        model, space, _st = garage(width=20.0, height=3.0, wwr=0.5)  # noqa: F841
        front = next(s for s in space.surfaces() if s.subSurfaces())
        self.assertAlmostEqual(0.5, self.PERIM.opening_ratio(front), delta=1e-6)
        blank = next(s for s in space.surfaces()
                     if s.surfaceType() == "Wall" and not s.subSurfaces())
        self.assertAlmostEqual(0.0, self.PERIM.opening_ratio(blank), delta=1e-6)

    def test_only_walls_at_or_above_40_percent_qualify(self):
        under_model, under, _st = garage(wwr=0.39)  # noqa: F841
        self.assertEqual([], self.PERIM.glazed_perimeter_walls(under))
        over_model, over, _st2 = garage(wwr=0.41)  # noqa: F841
        self.assertEqual(1, len(self.PERIM.glazed_perimeter_walls(over)))

    # The band is a fixed 6.1 m from the wall — NOT the head-height-derived band
    # that DaylightedAreas builds for 4.2.2.3.
    def test_the_band_is_6_1_m_deep_and_clipped_to_the_floor(self):
        model, space, _st = garage(width=20.0, depth=15.0, wwr=0.5)  # noqa: F841
        band = self.PERIM.qualifying_band_area(space)
        self.assertAlmostEqual(20.0 * 6.1, band["area_m2"], delta=0.5, msg="one 20 m wall x 6.1 m")

    # A shallower garage than the band depth must not report more band than floor.
    def test_the_band_cannot_exceed_the_floor_it_is_clipped_to(self):
        model, space, _st = garage(width=20.0, depth=4.0, wwr=0.5)  # noqa: F841
        band = self.PERIM.qualifying_band_area(space)
        self.assertLessEqual(band["area_m2"], space.floorArea() + 0.5)

    def test_power_at_or_below_150_w_needs_no_daylight_response(self):
        model, space, st = garage(width=20.0, depth=15.0, wwr=0.5)
        light(st, 1.0)   # 1 W/m2 x ~122 m2 band = ~122 W
        log = audit()
        self.SG.apply(model, audit=log)
        e = entry(log, "4.2.2.2.(4)")
        self.assertTrue(re.search(r"does not require a daylight response", e["action"]))
        self.assertFalse(space.thermalZone().get().primaryDaylightingControl().is_initialized())

    def test_power_above_150_w_gets_a_daylight_control(self):
        model, space, st = garage(width=20.0, depth=15.0, wwr=0.5)
        light(st, 5.0)   # ~610 W in the band
        log = audit()
        self.SG.apply(model, audit=log)
        e = entry(log, "4.2.2.2.(4)")
        self.assertEqual("decision", e["level"])
        self.assertTrue(space.thermalZone().get().primaryDaylightingControl().is_initialized(),
                        "the sentence requires an automatic daylight response")
        self.assertGreater(e["inputs"]["luminaire_power_w"], 150.0)

    # Daylighting.add_controls skips a zone that already has a primary control, so
    # the precedence must be stated rather than left to pass ordering.
    def test_an_existing_primary_control_is_not_duplicated(self):
        import openstudio

        model, space, st = garage(width=20.0, depth=15.0, wwr=0.5)
        light(st, 5.0)
        existing = openstudio.model.DaylightingControl(model)
        existing.setSpace(space)
        space.thermalZone().get().setPrimaryDaylightingControl(existing)
        log = audit()
        self.SG.apply(model, audit=log)
        self.assertTrue(re.search(r"already carries a primary daylighting control",
                                  entry(log, "4.2.2.2.(4)")["action"]))

    def test_an_unglazed_garage_is_outside_sentence_four(self):
        model, _, _ = garage(wwr=0.0)
        log = audit()
        self.SG.apply(model, audit=log)
        self.assertTrue(re.search(r"no storage-garage space has a perimeter wall",
                                  entry(log, "4.2.2.2.(4)")["action"]))

    # --- (3) and (5): declared, not guessed --------------------------------

    def test_entrances_are_declared_when_the_modeller_has_not_named_them(self):
        model, _, _ = garage()
        log = audit()
        self.SG.apply(model, audit=log)
        e = entry(log, "4.2.2.2.(3)")
        self.assertEqual("info", e["level"])
        self.assertTrue(re.search(r"requires identification by the modeller", e["action"]))

    def test_exemptions_are_declared_every_run(self):
        model, _, _ = garage()
        log = audit()
        self.SG.apply(model, audit=log)
        e = entry(log, "4.2.2.2.(5)")
        self.assertTrue(re.search(r"DAYLIGHT TRANSITION ZONES and RAMPS WITHOUT PARKING",
                                  e["action"]))

    # --- the citation bug --------------------------------------------------

    # The general occupancy-sensor path used to tag itself 4.2.2.2., which made the
    # storage-garage manifest entry report citations it never earned.
    def test_the_general_occupancy_path_no_longer_claims_this_article(self):
        source = (Path(__file__).resolve().parents[2]
                  / "btap" / "necb" / "lighting" / "apply_lights.py").read_text(encoding="UTF-8")
        self.assertFalse(re.search(r"article='4\.2\.2\.2\.", source),
                         "apply_lights must not cite 4.2.2.2 — that is the storage-garage article")


if __name__ == "__main__":
    unittest.main()
