"""Leg-C acceptance for the lighting domain (D-78): the ported code reproduces
the values FROZEN FROM THE PINNED LEGACY ORACLE in
btap-necb/test/goldens/oracle/{lighting_lights,lighting_daylighting,
lighting_costing}.json.

Leg A is the Ruby parity gates comparing gem to live oracle; Leg C is this —
the same oracle values, frozen, consumed by the Python port DIRECTLY, so a bug
faithfully ported from Ruby still fails here even when Ruby and Python agree.

The recipes below are btap-necb/test/support/oracle_probes.rb's Lighting
section (PAIRS, lights, sidelighting, skylight, daylighting_controls) plus
scripts/export_oracle_goldens.rb's build_case / office_tagged; the tolerances
are the Ruby gates' own (test_lighting_lights_parity.rb — exact signature
equality on values rounded to 9/6 decimals; test_lighting_daylighting_parity.rb
— 1e-9; test_lighting_costing.rb — max(|total| x 0.001, 0.05)).

Key sets are asserted in BOTH directions everywhere: a comparison that
silently checked fewer entries than the golden holds would be vacuous.
"""

import json
import unittest

from tests.necb.support import load_raw_fixture, needs_sdk
from tests.support import oracle_goldens_dir

GOLDENS = oracle_goldens_dir()

#: OracleProbes::Lighting::PAIRS
PAIRS = [["Space Function", "Office enclosed > 25 m2"],
         ["Space Function", "Conference/Meeting/Multi-purpose room"],
         ["Space Function", "Corridor/Transition area other-sch-A"],
         ["Space Function", "Dining area - family dining"],
         ["Space Function", "Classroom/Lecture hall/Training room other"]]

#: export_oracle_goldens.rb SIDELIGHTING_CASES / SKYLIGHT_CASES — the keys
#: encode the build parameters, so the geometry is reproducible from them.
SIDELIGHTING_CASES = {"window=2,6,0.8,2.5": {"window": [2.0, 6.0, 0.8, 2.5]},
                      "window=0.2,3,0.5,2.9": {"window": [0.2, 3.0, 0.5, 2.9]},
                      "window=0,10,0,3": {"window": [0.0, 10.0, 0.0, 3.0]}}
SKYLIGHT_CASES = {"skylight=4,6,3,5+window=2,6,0.8,2.5":
                  {"window": [2.0, 6.0, 0.8, 2.5], "skylight": [4.0, 6.0, 3.0, 5.0]},
                  "skylight=4,6,3,5": {"skylight": [4.0, 6.0, 3.0, 5.0]}}

OFFICE = ["Space Function", "Office enclosed > 25 m2"]
CITY = "TORONTO"
PROVINCE = "ONTARIO"


def golden(name):
    return json.loads((GOLDENS / f"{name}.json").read_text(encoding="utf-8"))


# --- the probes' signature builders (OracleProbes::Signatures) --------------

def day_values(day_schedule):
    import openstudio

    from btap._compat import ruby_round

    return [ruby_round(day_schedule.getValue(openstudio.Time(0, hour, 0, 0)), 6)
            for hour in range(1, 25)]


def lights_signature(space_type):
    from btap._compat import ruby_round, sorted_by_name

    instances = [light for light in sorted_by_name(space_type.lights())
                 if "Additional" not in light.nameString()]
    if not instances:
        return None

    lights = instances[0]
    d = lights.lightsDefinition()
    schedule_set = space_type.defaultScheduleSet()
    schedule = schedule_set.get().lightingSchedule() if schedule_set.is_initialized() else None
    sched_sig = None
    if schedule is not None and schedule.is_initialized():
        rs = schedule.get().to_ScheduleRuleset()
        if not rs.is_initialized():
            sched_sig = schedule.get().nameString()
        else:
            sched_sig = {"name": schedule.get().nameString(),
                         "default": day_values(rs.get().defaultDaySchedule()),
                         "rules": [day_values(r.daySchedule())
                                   for r in rs.get().scheduleRules()]}
    watts_area = d.wattsperSpaceFloorArea()
    watts_person = d.wattsperPerson()
    return {"w_m2": ruby_round(watts_area.get(), 9) if watts_area.is_initialized() else None,
            "w_person": ruby_round(watts_person.get(), 9) if watts_person.is_initialized() else None,
            "return_air": ruby_round(d.returnAirFraction(), 9),
            "radiant": ruby_round(d.fractionRadiant(), 9),
            "visible": ruby_round(d.fractionVisible(), 9),
            "schedule": sched_sig}


def daylighting_controls_signature(model):
    from btap._compat import ruby_round, sorted_by_name

    return [{"name": c.nameString(),
             "x": ruby_round(c.positionXCoordinate(), 9),
             "y": ruby_round(c.positionYCoordinate(), 9),
             "z": ruby_round(c.positionZCoordinate(), 9),
             "control_type": c.lightingControlType()}
            for c in sorted_by_name(model.getDaylightingControls())]


# --- the fixtures the probes ran on ----------------------------------------

def lights_model(lights_type):
    """OracleProbes::Lighting.lights' model, built with the GEM instead of the
    oracle: one tagged SpaceType per PAIR, then apply_lights."""
    import openstudio

    from btap.necb import lighting

    model = openstudio.model.Model()
    for bt, st in PAIRS:
        space_type = openstudio.model.SpaceType(model)
        space_type.setName(f"{bt} {st}")
        space_type.setStandardsBuildingType(bt)
        space_type.setStandardsSpaceType(st)
    lighting.apply_lights(model, vintage="2020", lights_type=lights_type)
    return model


def add_surface(model, space, points, type_):
    import openstudio

    vec = openstudio.Point3dVector([openstudio.Point3d(x, y, z) for x, y, z in points])
    surface = openstudio.model.Surface(vec, model)
    surface.setSpace(space)
    surface.setSurfaceType(type_)
    return surface


def glazing_construction(model, vt):
    import openstudio

    glazing = openstudio.model.SimpleGlazing(model)
    glazing.setUFactor(2.0)
    glazing.setSolarHeatGainCoefficient(0.4)
    glazing.setVisibleTransmittance(vt)
    construction = openstudio.model.Construction(model)
    construction.setLayers([glazing])
    return construction


def build_case(window=None, skylight=None):
    """export_oracle_goldens.rb build_case, verbatim: a 10x8x3 box with one
    south exterior wall + optional window (VT 0.6) / skylight (VT 0.7)."""
    import openstudio

    model = openstudio.model.Model()
    space = openstudio.model.Space(model)
    floor = add_surface(model, space, [(0, 0, 0), (0, 8, 0), (10, 8, 0), (10, 0, 0)], "Floor")
    wall = add_surface(model, space, [(0, 0, 3), (0, 0, 0), (10, 0, 0), (10, 0, 3)], "Wall")
    wall.setOutsideBoundaryCondition("Outdoors")
    roof = add_surface(model, space, [(0, 0, 3), (10, 0, 3), (10, 8, 3), (0, 8, 3)], "RoofCeiling")
    roof.setOutsideBoundaryCondition("Outdoors")

    if window:
        x0, x1, z0, z1 = window
        vec = openstudio.Point3dVector(
            [openstudio.Point3d(x, y, z)
             for x, y, z in [(x0, 0, z1), (x0, 0, z0), (x1, 0, z0), (x1, 0, z1)]])
        sub = openstudio.model.SubSurface(vec, model)
        sub.setSurface(wall)
        sub.setSubSurfaceType("FixedWindow")
        sub.setConstruction(glazing_construction(model, 0.6))
    if skylight:
        x0, x1, y0, y1 = skylight
        vec = openstudio.Point3dVector(
            [openstudio.Point3d(x, y, z)
             for x, y, z in [(x0, y0, 3), (x1, y0, 3), (x1, y1, 3), (x0, y1, 3)]])
        sub = openstudio.model.SubSurface(vec, model)
        sub.setSurface(roof)
        sub.setSubSurfaceType("Skylight")
        sub.setConstruction(glazing_construction(model, 0.7))
    return model, space, floor


def office_tagged(model):
    from btap.necb import loads

    map_ = {s.nameString(): list(OFFICE) for s in model.getSpaces()}
    loads.assign_space_types(model, map_, vintage="2020")
    return model


@needs_sdk
class TestOracleGoldensLighting(unittest.TestCase):
    def assert_same_keys(self, expected, actual, what):
        """Key-set equality in BOTH directions — the guard against a comparison
        that silently shrinks."""
        self.assertEqual(set(expected), set(actual), f"{what}: key sets differ")
        self.assertEqual(len(expected), len(actual), f"{what}: entry counts differ")

    # ---- lighting_lights.json: NECB_Default:5 + LED:5 ---------------------

    def test_lights_signatures_match_the_frozen_oracle(self):
        expected = golden("lighting_lights")
        self.assert_same_keys(["NECB_Default", "LED"], expected.keys(), "lighting_lights")
        self.assertEqual(5, len(expected["NECB_Default"]), "NECB_Default: 5 space types")
        self.assertEqual(5, len(expected["LED"]), "LED: 5 space types")

        for lights_type in ["NECB_Default", "LED"]:
            model = lights_model(lights_type)
            names = [f"{bt} {st}" for bt, st in PAIRS]
            self.assert_same_keys(expected[lights_type], names, f"{lights_type} space types")

            for name in names:
                space_type = next(s for s in model.getSpaceTypes() if s.nameString() == name)
                actual = lights_signature(space_type)
                legacy = expected[lights_type][name]
                self.assert_same_keys(legacy, actual, f"{lights_type}/{name} signature fields")
                for field in ["w_m2", "w_person", "return_air", "radiant", "visible"]:
                    self.assertEqual(legacy[field], actual[field],
                                     f"{lights_type}/{name}: {field}")
                if isinstance(legacy["schedule"], str) or legacy["schedule"] is None:
                    self.assertEqual(legacy["schedule"], actual["schedule"],
                                     f"{lights_type}/{name}: schedule")
                else:
                    self.assert_same_keys(legacy["schedule"], actual["schedule"],
                                          f"{lights_type}/{name} schedule fields")
                    self.assertEqual(legacy["schedule"]["name"], actual["schedule"]["name"])
                    self.assertEqual(legacy["schedule"]["default"], actual["schedule"]["default"],
                                     f"{lights_type}/{name}: default day values")
                    self.assertEqual(legacy["schedule"]["rules"], actual["schedule"]["rules"],
                                     f"{lights_type}/{name}: rule day values")

    # ---- lighting_daylighting.json: sidelighting:3, skylight:2, controls:4 -

    def test_daylighting_geometry_and_controls_match_the_frozen_oracle(self):
        from btap.necb.lighting import daylighting

        expected = golden("lighting_daylighting")
        self.assert_same_keys(["sidelighting", "skylight", "controls_on_fixture"],
                              expected.keys(), "lighting_daylighting")
        self.assertEqual(3, len(expected["sidelighting"]), "sidelighting: 3 cases")
        self.assertEqual(2, len(expected["skylight"]), "skylight: 2 cases")
        self.assertEqual(4, len(expected["controls_on_fixture"]),
                         "controls_on_fixture: 4 controls")

        # [primary_sidelighted_area, vt_handle, window_area_sum]
        self.assert_same_keys(expected["sidelighting"], SIDELIGHTING_CASES.keys(),
                              "sidelighting cases")
        for key, params in SIDELIGHTING_CASES.items():
            model, space, _floor = build_case(**params)  # noqa: F841 (model keeps the SDK objects alive)
            gem = daylighting.sidelighting_parameters(space)
            legacy_psa, legacy_vt, legacy_win = expected["sidelighting"][key]
            self.assertAlmostEqual(legacy_psa, gem["area_m2"], delta=1e-9,
                                   msg=f"{key}: primary sidelighted area")
            self.assertAlmostEqual(legacy_vt, gem["vt_handle"], delta=1e-9, msg=f"{key}: VT handle")
            self.assertAlmostEqual(legacy_win, gem["window_area_m2"], delta=1e-9,
                                   msg=f"{key}: window area")

        # [daylighted_under_skylight_area, vt_handle, skylight_area_sum]
        self.assert_same_keys(expected["skylight"], SKYLIGHT_CASES.keys(), "skylight cases")
        for key, params in SKYLIGHT_CASES.items():
            model, space, _floor = build_case(**params)  # noqa: F841
            gem = daylighting.skylight_parameters(space)
            legacy_area, legacy_vt, legacy_sum = expected["skylight"][key]
            self.assertGreater(legacy_area, 0.0,
                               "post-#2119 legacy: a skylight-only space has a real daylighted area")
            self.assertAlmostEqual(legacy_area, gem["area_m2"], delta=1e-9,
                                   msg=f"{key}: daylighted area under skylight")
            self.assertAlmostEqual(legacy_vt, gem["vt_handle"], delta=1e-9)
            self.assertAlmostEqual(legacy_sum, gem["skylight_area_m2"], delta=1e-9)

        # placement 'necb2011' names the legacy rule explicitly — neither of the
        # other two placements does what legacy does ('all' is the blanket
        # default of this entry point, 'necb2020' is the code rule, D-57).
        from btap.audit import AuditLog
        from btap.necb import lighting

        model = office_tagged(load_raw_fixture())
        wall = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == "Outdoors" and s.surfaceType() == "Wall")
        wall.setWindowToWallRatio(0.4)
        audit = AuditLog()
        created = lighting.add_daylighting_controls(model, vintage="2020",
                                                    placement="necb2011", audit=audit)
        actual = daylighting_controls_signature(model)
        legacy_controls = expected["controls_on_fixture"]

        self.assertEqual(len(legacy_controls), len(actual), "same control count as legacy")
        self.assertEqual(len(legacy_controls), created,
                         "every legacy control is one the gem reports creating")
        self.assert_same_keys([c["name"] for c in legacy_controls],
                              [c["name"] for c in actual], "controls land on the same spaces")

        legacy_pos = {c["name"]: c for c in legacy_controls}
        for control in actual:
            expected_control = legacy_pos[control["name"]]
            for axis in ["x", "y", "z"]:
                self.assertAlmostEqual(expected_control[axis], control[axis], delta=1e-9,
                                       msg=f"{control['name']}: sensor {axis} position")
            self.assertEqual("Stepped", control["control_type"])

        # #2119 replaced legacy's exact 'Office - enclosed' comparison with
        # /office\s*-?\s*enclosed/i, so the office-name-drift warning must NOT
        # fire any more — the exemption matches the NECB2020 names on both sides.
        self.assertFalse(any("'Office - enclosed'" in w["action"] for w in audit.warnings),
                         "the 2020 office-name drift warning is obsolete: #2119 made the legacy "
                         "matcher a regex")

    # ---- lighting_costing.json: led_2020_total + context ------------------

    def test_led_2020_fixture_costing_matches_the_frozen_oracle(self):
        from btap.necb import lighting

        expected = golden("lighting_costing")
        self.assert_same_keys(["led_2020_total", "context"], expected.keys(), "lighting_costing")
        self.assertIn("apply_lights LED", expected["context"])
        self.assertIn("ONTARIO/TORONTO", expected["context"])

        model = office_tagged(load_raw_fixture())
        lighting.apply_lights(model, vintage="2020", lights_type="LED")
        model.getBuilding().setStandardsTemplate("NECB2020")

        report = lighting.cost(model, vintage="2020", city=CITY, province_state=PROVINCE)
        legacy_total = expected["led_2020_total"]
        self.assertAlmostEqual(
            legacy_total, report.total, delta=max(abs(legacy_total) * 0.001, 0.05),
            msg="fixture-costing dollar parity vs legacy cost_audit_lighting (LED/NECB2020 path)")


if __name__ == "__main__":
    unittest.main()
