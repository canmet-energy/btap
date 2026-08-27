"""NECB 2020/2025 4.2.2.1.(10)-(15): the daylighted-area geometry (4.2.2.3./
4.2.2.5., unioned) and the input-POWER photocontrol requirement built on it.
This is the D-57 gate; the legacy NECB 2011 rule it replaced lives behind
placement='necb2011' and is pinned by test_oracle_goldens_lighting.py.

Port of btap-necb/test/test_lighting_daylighting_necb2020.rb.
"""

import re
import unittest

from tests.necb.support import needs_sdk


def add_surface(model, space, points, type_, outside=None):
    import openstudio

    vector = openstudio.Point3dVector([openstudio.Point3d(x, y, z) for x, y, z in points])
    surface = openstudio.model.Surface(vector, model)
    surface.setSpace(space)
    surface.setSurfaceType(type_)
    if outside:
        surface.setOutsideBoundaryCondition(outside)
    return surface


def glazing(model, visible_transmittance):
    import openstudio

    simple = openstudio.model.SimpleGlazing(model)
    simple.setUFactor(2.0)
    simple.setSolarHeatGainCoefficient(0.4)
    simple.setVisibleTransmittance(visible_transmittance)
    construction = openstudio.model.Construction(model)
    construction.setLayers([simple])
    return construction


def box(windows=(), skylights=(), width=10.0, depth=8.0, height=3.0,
        skylight_vt=0.7, space_type=None, latitude=None):
    """A single rectangular space, width x depth x height, with the given windows
    ([x0, x1, z0, z1] on the y = 0 wall) and skylights ([x0, x1, y0, y1])."""
    import openstudio

    from btap.necb import lighting, loads

    model = openstudio.model.Model()
    if latitude:
        model.getSite().setLatitude(latitude)
    space = openstudio.model.Space(model)
    space.setName("test space")
    add_surface(model, space, [(0, 0, 0), (0, depth, 0), (width, depth, 0), (width, 0, 0)], "Floor")
    wall = add_surface(model, space,
                       [(0, 0, height), (0, 0, 0), (width, 0, 0), (width, 0, height)],
                       "Wall", "Outdoors")
    roof = add_surface(model, space,
                       [(0, 0, height), (width, 0, height), (width, depth, height),
                        (0, depth, height)], "RoofCeiling", "Outdoors")
    for index, (x0, x1, z0, z1) in enumerate(windows):
        vector = openstudio.Point3dVector(
            [openstudio.Point3d(x, y, z)
             for x, y, z in [(x0, 0, z1), (x0, 0, z0), (x1, 0, z0), (x1, 0, z1)]])
        sub = openstudio.model.SubSurface(vector, model)
        sub.setName(f"window {index}")
        sub.setSurface(wall)
        sub.setSubSurfaceType("FixedWindow")
        sub.setConstruction(glazing(model, 0.6))
    for index, (x0, x1, y0, y1) in enumerate(skylights):
        vector = openstudio.Point3dVector(
            [openstudio.Point3d(x, y, z)
             for x, y, z in [(x0, y0, height), (x1, y0, height), (x1, y1, height),
                             (x0, y1, height)]])
        sub = openstudio.model.SubSurface(vector, model)
        sub.setName(f"skylight {index}")
        sub.setSurface(roof)
        sub.setSubSurfaceType("Skylight")
        sub.setConstruction(glazing(model, skylight_vt))
    if space_type:
        zone = openstudio.model.ThermalZone(model)
        space.setThermalZone(zone)
        loads.assign_space_types(model, {space.nameString(): ["Space Function", space_type]},
                                 vintage="2020")
        lighting.apply_lights(model, vintage="2020")
    return model, space


@needs_sdk
class TestDaylightingNecb2020(unittest.TestCase):
    @property
    def DA(self):
        from btap.necb.lighting import daylighted_areas
        return daylighted_areas

    @property
    def REQ(self):
        from btap.necb.lighting import daylight_control_requirement
        return daylight_control_requirement

    # --- geometry: 4.2.2.3. / 4.2.2.5. ---------------------------------------

    def test_primary_and_secondary_use_half_head_height_and_one_head_height_depth(self):
        # 4 m window, head 2.5 m: width 4 + 2 x (2.5/2) = 6.5 m, depth = head = 2.5 m
        _model, space = box(windows=[(2.0, 6.0, 0.5, 2.5)])
        areas = self.DA.areas(space)
        self.assertAlmostEqual(16.25, areas["primary_sidelighted_m2"], delta=0.02,
                               msg="4.2.2.3.(3)(a)/(4)(a): 6.5 m x 2.5 m")
        # 4.2.2.3.(8)(a): the secondary band starts where the primary ends and runs
        # one further head height — the legacy port computed NO secondary area at all
        self.assertAlmostEqual(16.25, areas["secondary_sidelighted_m2"], delta=0.02,
                               msg="4.2.2.3.(6)-(8) secondary band")
        self.assertGreater(areas["secondary_sidelighted_m2"], 0.0,
                           "legacy computed zero secondary area (L-26)")

    def test_overlapping_windows_are_unioned_not_summed(self):
        # Two 2 m windows 0.5 m apart, head 2.5 -> each band 4.5 m wide, bands OVERLAP.
        # Union spans x 0.75..7.75 = 7.0 m; a per-window sum would give 9.0 m.
        _model, space = box(windows=[(2.0, 4.0, 0.5, 2.5), (4.5, 6.5, 0.5, 2.5)])
        overlapping = self.DA.areas(space)
        self.assertAlmostEqual(7.0 * 2.5, overlapping["primary_sidelighted_m2"], delta=0.05,
                               msg="4.2.2.3.(1): combined WITHOUT double-counting overlapping areas")
        self.assertLess(overlapping["primary_sidelighted_m2"], 9.0 * 2.5,
                        "a per-window sum would double-count the overlap")

        # Same two windows moved apart so the bands do not touch: now the total is the
        # sum (clipped at the room edge), proving the union is not simply shrinking.
        _model2, apart = box(windows=[(2.0, 4.0, 0.5, 2.5), (7.0, 9.0, 0.5, 2.5)])
        separated = self.DA.areas(apart)
        self.assertGreater(separated["primary_sidelighted_m2"],
                           overlapping["primary_sidelighted_m2"])

    def test_bands_are_clipped_to_the_space_enclosure(self):
        # Window hard against the x = 10 wall: its band cannot extend past the wall.
        _model, space = box(windows=[(7.0, 9.0, 0.5, 2.5)])
        areas = self.DA.areas(space)
        # band x 5.75..10.25 clipped to 5.75..10.0 = 4.25 m wide, depth 2.5
        self.assertAlmostEqual(4.25 * 2.5, areas["primary_sidelighted_m2"], delta=0.05,
                               msg="4.2.2.3.(3)(b)/(4)(b): the enclosure bounds the band")
        self.assertLessEqual(areas["primary_sidelighted_m2"] + areas["secondary_sidelighted_m2"]
                             + areas["toplighted_m2"], areas["floor_m2"] + 0.01,
                             "no daylighted area escapes the floor")

    def test_skylight_only_space_gets_toplighted_area(self):
        # 2 x 2 skylight, 3 m ceiling: extension 0.7 x 3 = 2.1 m each way -> 6.2 x 6.2.
        # The LEGACY port used to return ZERO here (its accumulator sat inside the
        # exterior-window loop); #2119 moved it out, and the quarantine port mirrors
        # that. For ONE skylight in a windowless box the two rules coincide — they
        # diverge once there are several apertures for 4.2.2.5. to union.
        from btap.necb.lighting import daylighting

        _model, space = box(skylights=[(4.0, 6.0, 3.0, 5.0)])
        areas = self.DA.areas(space)
        self.assertAlmostEqual(6.2 * 6.2, areas["toplighted_m2"], delta=0.05,
                               msg="4.2.2.5.(2)(a): 70% of ceiling height")
        legacy = daylighting.skylight_parameters(space)
        self.assertGreater(
            legacy["area_m2"], 0.0,
            "the legacy port tracks legacy as fixed by #2119: a skylight-only space is no longer zero")

    def test_necb_precedence_primary_beats_toplit_and_secondary_loses_to_both(self):
        # Window and skylight whose areas overlap. 4.2.2.5.(2)(b) caps the skylight
        # extension at the primary sidelighted area, so PRIMARY survives intact and
        # the TOPLIT area is reduced — the opposite of the ASHRAE 90.1 precedence in
        # the openstudio-standards method this geometry was adapted from.
        _model, space = box(windows=[(2.0, 6.0, 0.5, 2.5)], skylights=[(2.0, 6.0, 1.0, 3.0)])
        areas = self.DA.areas(space)
        self.assertAlmostEqual(16.25, areas["primary_sidelighted_m2"], delta=0.05,
                               msg="primary is NOT reduced by the skylight")
        toplit_gross = min(8.1, 10.0) * min(5.1, 8.0)
        self.assertLess(areas["toplighted_m2"], toplit_gross,
                        "4.2.2.5.(2)(b): toplit stops at the primary")
        self.assertAlmostEqual(0.0, areas["secondary_sidelighted_m2"], delta=0.05,
                               msg="4.2.2.3.(9): no secondary area beyond an under-skylight area")
        self.assertLessEqual(areas["primary_sidelighted_m2"] + areas["secondary_sidelighted_m2"]
                             + areas["toplighted_m2"], areas["floor_m2"] + 0.01)

    def test_secondary_never_exceeds_primary_so_the_300_w_test_is_never_decisive_alone(self):
        # Each secondary band is a translate of its primary band and loses every
        # overlap, so total secondary <= total primary and combined <= 2 x primary.
        # Therefore 4.2.2.1.(10)(b)'s 300 W can only be met when (10)(a)'s 150 W
        # already is. Recorded so the redundancy is a known property, not a surprise.
        cases = [{"windows": [(2.0, 6.0, 0.5, 2.5)]},
                 {"windows": [(0.0, 10.0, 0.0, 3.0)]},
                 {"windows": [(2.0, 4.0, 0.5, 2.5), (4.5, 6.5, 0.5, 2.5)]},
                 {"windows": [(0.0, 10.0, 0.5, 2.5)], "depth": 3.0}]
        for index, args in enumerate(cases):
            _model, space = box(**args)
            areas = self.DA.areas(space)
            self.assertLessEqual(areas["secondary_sidelighted_m2"],
                                 areas["primary_sidelighted_m2"] + 0.01,
                                 f"case {index}: secondary <= primary")

    # --- Table 4.2.1.6. control matrix ---------------------------------------

    def test_control_matrix_states_are_all_legal_and_the_residue_is_recorded(self):
        rows = self.REQ.table()["space_types"]
        self.assertGreaterEqual(len(rows), 105, "every NECB space-function catalog name is mapped")
        legal = ["required", "not_required", "not_applicable", "not_listed", "unknown"]
        for name, row in rows.items():
            self.assertIn(row["sidelighting"], legal, f"{name} sidelighting")
            self.assertIn(row["toplighting"], legal, f"{name} toplighting")
        # anything not decided from the code text must be enumerated, not buried
        published = [r["space_type"] for r in self.REQ.residue()]
        unresolved = [name for name, r in rows.items()
                      if r["sidelighting"] in ("unknown", "not_listed")
                      or r["toplighting"] in ("unknown", "not_listed")]
        self.assertEqual(sorted(unresolved), sorted(published),
                         "every column not read straight off the table appears in the published "
                         "residue list")
        self.assertLessEqual(len(self.REQ.residue()), 12, "the residue stays small enough to file")

    def test_dwelling_units_are_not_listed_rather_than_unknown(self):
        # 4.2.2.1.(10)/(13) reach only spaces requiring the control "in accordance
        # with Table 4.2.1.6.", and 4.2.2.1.(2) ties that to the table's space-by-space
        # types. Dwelling units have no row (their LPD is 8.4.4.5.(2)), so the
        # sentences do not reach them — a determination from the code text, NOT a
        # conservative guess. Getting this wrong photocontrolled 122 apartment spaces.
        for suffix in ["general", "long-term"]:
            row = self.REQ.requirement(f"Dwelling units {suffix}")
            self.assertEqual("not_listed", row["sidelighting"])
            self.assertEqual("not_listed", row["toplighting"])
        _model, space = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Dwelling units general")
        verdict, audit = self.evaluate(space)
        self.assertFalse(verdict["required"], "no photocontrols in a dwelling unit")
        self.assertEqual([], [w for w in audit.warnings if "UNRESOLVED" in w["action"]],
                         "not a conservative-default guess: no unresolved-column warning")
        self.assertTrue(any("has NO Table 4.2.1.6. row" in e["action"] for e in audit.entries),
                        "the determination is recorded with its reasoning")

    def test_control_matrix_spot_values(self):
        self.assertEqual("required", self.REQ.requirement("Office enclosed > 25 m2")["sidelighting"])
        self.assertEqual("required", self.REQ.requirement("Office enclosed > 25 m2")["toplighting"])
        # 'X' in the corrected table (hbix#88) — it was not_required only in the
        # corrupt extraction. A genuine '-' row instead:
        self.assertEqual("required", self.REQ.requirement("Library reading area")["sidelighting"])
        self.assertEqual("not_required",
                         self.REQ.requirement("Dormitory living quarters")["sidelighting"])
        # Table 4.2.1.6. refers these two out to other articles entirely
        self.assertEqual("not_applicable", self.REQ.requirement("Guest room")["sidelighting"])
        self.assertEqual("not_applicable",
                         self.REQ.requirement("Storage garage interior")["toplighting"])
        # schedule-letter suffixes resolve to the same row
        self.assertEqual(self.REQ.requirement("Computer/Server room"),
                         self.REQ.requirement("Computer/Server room-sch-C"))
        self.assertTrue(self.REQ.requirement("Retail facility mall concourse")["retail"],
                        "4.2.2.1.(12)(c) retail flag")

    # --- 4.2.2.1.(10)/(13): the power tests ----------------------------------

    def evaluate(self, space, **kwargs):
        from btap.audit import AuditLog

        audit = AuditLog()
        return self.REQ.evaluate(space, audit=audit, **kwargs), audit

    def test_sidelighting_required_when_primary_power_reaches_150_w(self):
        # Office enclosed > 25 m2 = 7.1 W/m2; full-wall glazing head 3 m gives a
        # 10 m x 3 m primary band = 30 m2 -> 213 W >= 150 W.
        _model, space = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        verdict, _ = self.evaluate(space)
        self.assertTrue(verdict["sidelighting"]["required"], verdict["sidelighting"]["reason"])
        self.assertTrue(re.search(r"4\.2\.2\.1\.\(10\)\(a\)", verdict["sidelighting"]["reason"]))
        self.assertTrue(verdict["required"])

    def test_sidelighting_not_required_below_both_thresholds(self):
        # One small window: 6.5 m x 2.5 m = 16.25 m2 primary -> 115 W < 150 W, and
        # 32.5 m2 primary + secondary -> 231 W < 300 W.
        _model, space = box(windows=[(2.0, 6.0, 0.5, 2.5)], space_type="Office enclosed > 25 m2")
        verdict, _ = self.evaluate(space)
        self.assertFalse(verdict["sidelighting"]["required"], verdict["sidelighting"]["reason"])
        self.assertTrue(re.search(r"below both", verdict["sidelighting"]["reason"]))

    def test_toplighting_alone_qualifies_a_space_with_no_windows(self):
        # THE L-26 DEFECT, DIRECTLY: the legacy criteria ANDed sidelighting and
        # skylight tests, so a skylight-only space could never qualify. (13) is
        # independent of (10).
        _model, space = box(skylights=[(4.0, 6.0, 3.0, 5.0)], space_type="Office enclosed > 25 m2")
        verdict, _ = self.evaluate(space)
        self.assertFalse(verdict["sidelighting"]["required"],
                         "no glazing: 4.2.2.1.(12)(b) excepts sidelighting")
        self.assertTrue(verdict["toplighting"]["required"], verdict["toplighting"]["reason"])
        self.assertTrue(re.search(r"4\.2\.2\.1\.\(13\)", verdict["toplighting"]["reason"]))
        self.assertTrue(verdict["required"], "the space qualifies on toplighting ALONE")

    def test_sidelighting_alone_qualifies_a_space_with_no_skylights(self):
        _model, space = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        verdict, _ = self.evaluate(space)
        self.assertTrue(verdict["sidelighting"]["required"])
        self.assertFalse(verdict["toplighting"]["required"], "no skylights: zero toplighted area")
        self.assertTrue(verdict["required"], "the space qualifies on sidelighting ALONE")

    # --- exceptions ----------------------------------------------------------

    def test_glazing_under_2_m2_excepts_sidelighting(self):
        _model, space = box(windows=[(2.0, 3.0, 2.0, 2.5)], space_type="Office enclosed > 25 m2")
        verdict, _ = self.evaluate(space)
        self.assertFalse(verdict["sidelighting"]["required"])
        self.assertTrue(re.search(r"4\.2\.2\.1\.\(12\)\(b\)", verdict["sidelighting"]["reason"]))

    def test_retail_space_excepts_sidelighting_but_not_toplighting(self):
        _model, space = box(windows=[(0.0, 10.0, 0.0, 3.0)], skylights=[(4.0, 6.0, 3.0, 5.0)],
                            space_type="Retail facility mall concourse")
        verdict, _ = self.evaluate(space)
        self.assertFalse(verdict["sidelighting"]["required"])
        self.assertTrue(re.search(r"4\.2\.2\.1\.\(12\)\(c\)", verdict["sidelighting"]["reason"]))
        self.assertTrue(verdict["toplighting"]["required"], "(12) excepts (10) only — (13) is untouched")

    def test_obstruction_ratio_of_two_excepts_sidelighting(self):
        import openstudio

        model, space = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        verdict, _ = self.evaluate(space)
        self.assertTrue(verdict["sidelighting"]["required"],
                        "baseline: required with no adjacent structure")

        # a wall 5 m from the glazing rising 13 m above the window head: ratio 2.6
        group = openstudio.model.ShadingSurfaceGroup(model)
        vector = openstudio.Point3dVector(
            [openstudio.Point3d(x, y, z)
             for x, y, z in [(0, -5, 0), (10, -5, 0), (10, -5, 16), (0, -5, 16)]])
        openstudio.model.ShadingSurface(vector, model).setShadingSurfaceGroup(group)

        obstructed, _ = self.evaluate(space)
        self.assertFalse(obstructed["sidelighting"]["required"])
        self.assertTrue(re.search(r"4\.2\.2\.1\.\(12\)\(a\)", obstructed["sidelighting"]["reason"]))

    def test_low_visible_transmittance_excepts_toplighting(self):
        _model, space = box(skylights=[(4.0, 6.0, 3.0, 5.0)], skylight_vt=0.3,
                            space_type="Office enclosed > 25 m2")
        verdict, _ = self.evaluate(space)
        self.assertFalse(verdict["toplighting"]["required"])
        self.assertTrue(re.search(r"4\.2\.2\.1\.\(15\)\(b\)", verdict["toplighting"]["reason"]))

    def test_above_55_north_with_under_200_w_excepts_toplighting(self):
        # 0.8 x 0.8 skylight, 3 m ceiling -> 5.0 x 5.0 = 25 m2 -> 7.1 x 25 = 178 W:
        # over (13)'s 150 W but under (15)(c)'s 200 W.
        args = {"skylights": [(4.0, 4.8, 3.0, 3.8)], "space_type": "Office enclosed > 25 m2"}
        _model, south = box(latitude=45.0, **args)
        verdict_south, _ = self.evaluate(south)
        self.assertTrue(verdict_south["toplighting"]["required"],
                        verdict_south["toplighting"]["reason"])
        self.assertLess(verdict_south["toplighting"]["power_w"], 200.0)

        _model2, north = box(latitude=60.0, **args)
        verdict_north, _ = self.evaluate(north)
        self.assertFalse(verdict_north["toplighting"]["required"])
        self.assertTrue(re.search(r"4\.2\.2\.1\.\(15\)\(c\)", verdict_north["toplighting"]["reason"]))

    def test_table_column_closes_the_gate_entirely(self):
        _model, space = box(windows=[(0.0, 10.0, 0.0, 3.0)], skylights=[(4.0, 6.0, 3.0, 5.0)],
                            space_type="Dormitory living quarters")
        verdict, _ = self.evaluate(space)
        self.assertFalse(verdict["required"],
                         "Table 4.2.1.6. requires neither column for this space type")
        self.assertTrue(re.search(r"Table 4\.2\.1\.6\.", verdict["sidelighting"]["reason"]))
        self.assertTrue(re.search(r"Table 4\.2\.1\.6\.", verdict["toplighting"]["reason"]))

    def test_unresolved_table_column_warns_and_takes_the_conservative_default(self):
        # A space type with NO Table 4.2.1.6. row at all — the only unresolved kind
        # left once hbix#88 was fixed (the four extraction CONFLICTs are resolved).
        args = {"windows": [(0.0, 30.0, 0.0, 3.0)], "width": 30.0,
                "space_type": "Audience seating area permanent - convention centre"}
        _model, space = box(**args)
        verdict, audit = self.evaluate(space)
        self.assertTrue(verdict["sidelighting"]["required"], "conservative default: required")
        self.assertTrue(any("TABLE 4.2.1.6. SIDELIGHTING COLUMN IS UNRESOLVED" in w["action"]
                            for w in audit.warnings),
                        "the unresolved column is SHOUTED, never silent")

        _model2, space2 = box(**args)
        lenient, lenient_audit = self.evaluate(space2, unknown_default="not_required")
        self.assertFalse(lenient["sidelighting"]["required"], "the caller can flip the default")
        self.assertNotEqual([], lenient_audit.warnings, "flipping it still warns")

    # --- wiring: add_controls / reference_daylighting -------------------------

    def test_controls_are_placed_with_a_daylighted_area_fraction_not_1_0(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        model, space = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        audit = AuditLog()
        created = lighting.add_daylighting_controls(model, vintage="2020", placement="necb2020",
                                                    audit=audit)
        self.assertEqual(1, created)
        zone = space.thermalZone().get()
        self.assertTrue(zone.primaryDaylightingControl().is_initialized())
        fraction = zone.fractionofZoneControlledbyPrimaryDaylightingControl()
        # primary 30 m2 + secondary 30 m2 of an 80 m2 floor = 0.75
        self.assertAlmostEqual(0.75, fraction, delta=0.02,
                               msg="4.2.2.1.(10) controls the lighting IN the daylighted areas, "
                                   "not the whole room")
        self.assertLess(fraction, 1.0)
        control = zone.primaryDaylightingControl().get()
        self.assertEqual("Stepped", control.lightingControlType())
        self.assertEqual(3, control.numberofSteppedControlSteps(),
                         "4.2.2.1.(11)(a)(i): 67% / 33% / off, not the 2011 two-step minimum")
        self.assertTrue(any(e.get("ruling") == "D-57" for e in audit.entries),
                        "the ruling is cited")

    def test_legacy_2011_placement_is_still_reachable_and_shouts(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        model, _ = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        audit = AuditLog()
        created = lighting.add_daylighting_controls(model, vintage="2020",
                                                    placement="necb2011", audit=audit)
        # Post-#2119: the skylight criteria no longer apply to a window-only space,
        # and the >=25 m2 enclosed-office exemption now matches the 2020 name, so
        # the legacy rule qualifies it. L-26 survives as a RULE difference (2011
        # ANDs area/aperture tests; 2020 tests input power independently), which is
        # why this path still shouts.
        self.assertEqual(1, created,
                         "the fixed 2011 criteria qualify a >=25 m2 enclosed office with "
                         "full-wall glazing")
        self.assertTrue(any("LEGACY NECB 2011 THRESHOLD EVALUATION IN USE" in w["action"]
                            for w in audit.warnings))

    def test_reference_daylighting_defaults_to_the_2020_rule(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        model, _ = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        audit = AuditLog()
        lighting.reference_daylighting(model, vintage="2020", audit=audit)
        self.assertEqual(1, len(model.getDaylightingControls()),
                         "the reference now gets photocontrols where 4.2.2.1.(10) requires them")
        self.assertTrue(any("D-57" in str(e.get("ruling")) and e["level"] == "decision"
                            for e in audit.entries))
        # the 2011 alias still reaches the legacy rule for the parity gate — which,
        # post-#2119, places a control here too. What still separates the rules is
        # the step count and the zone fraction, asserted above for 'necb2020'.
        legacy_model, _ = box(windows=[(0.0, 10.0, 0.0, 3.0)],
                              space_type="Office enclosed > 25 m2")
        lighting.reference_daylighting(legacy_model, vintage="2020", placement="necb_default",
                                       office_match="legacy")
        self.assertEqual(1, len(legacy_model.getDaylightingControls()))
        self.assertEqual(
            2,
            legacy_model.getThermalZones()[0].primaryDaylightingControl().get()
            .numberofSteppedControlSteps(),
            "the legacy 2011 rule ran, not the 2020 one (its minimum is two steps)")

    def test_unevaluated_1500_hour_exception_is_declared_every_run(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        model, _ = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        audit = AuditLog()
        lighting.add_daylighting_controls(model, vintage="2020", placement="necb2020", audit=audit)
        self.assertTrue(any("4.2.2.1.(15)(a) EXCEPTION IS NOT EVALUATED" in w["action"]
                            for w in audit.warnings),
                        "the un-modellable exception is declared, not hidden")
        self.assertTrue(any("ROOF" in e["action"] and "MONITORS" in e["action"]
                            for e in audit.entries),
                        "roof monitors being undetectable is declared")

    # --- the deprecated `option:` alias -------------------------------------
    # `placement` is the single selector now; `option` still works (callers
    # exist in the wild) and must land on the SAME rule it used to, loudly.

    def test_deprecated_option_alias_still_selects_the_same_rule(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        # option='NECB_Default' == placement='necb2020', end to end
        model, _ = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        audit = AuditLog()
        created = lighting.add_daylighting_controls(model, vintage="2020", option="NECB_Default",
                                                    audit=audit)
        self.assertEqual(1, created)
        self.assertEqual(3,
                         model.getThermalZones()[0].primaryDaylightingControl().get()
                         .numberofSteppedControlSteps(),
                         "the 2020 rule ran, not the blanket one")
        deprecation = next((e for e in audit.entries
                            if "`option:` argument is DEPRECATED" in e["action"]), None)
        self.assertIsNotNone(deprecation, "passing the deprecated kwarg is audited")
        self.assertEqual("necb2020", deprecation["inputs"]["placement_used"])

        # option='NECB_Default' + placement='necb2011' still reaches the legacy rule
        # (which, post-#2119, qualifies this space — the two-step control proves it
        # was the 2011 rule and not the 2020 one that ran)
        legacy, _ = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        self.assertEqual(1, lighting.add_daylighting_controls(legacy, vintage="2020",
                                                              option="NECB_Default",
                                                              placement="necb2011"))
        self.assertEqual(2,
                         legacy.getThermalZones()[0].primaryDaylightingControl().get()
                         .numberofSteppedControlSteps(),
                         "the legacy 2011 rule ran, not the 2020 one")

        # option='all' wins over placement, exactly as it silently used to
        blanket, _ = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        blanket_audit = AuditLog()
        self.assertEqual(1, lighting.add_daylighting_controls(blanket, vintage="2020",
                                                              option="all", placement="necb2011",
                                                              audit=blanket_audit))
        self.assertEqual(2,
                         blanket.getThermalZones()[0].primaryDaylightingControl().get()
                         .numberofSteppedControlSteps())
        self.assertAlmostEqual(
            1.0,
            blanket.getThermalZones()[0].fractionofZoneControlledbyPrimaryDaylightingControl(),
            delta=1e-9, msg="the blanket path controls the whole zone")
        self.assertTrue(any(e.get("inputs") and e["inputs"].get("placement_used") == "all"
                            for e in blanket_audit.entries))

    def test_placement_default_is_the_blanket_rule_and_unknowns_raise(self):
        from btap.necb import lighting

        model, _ = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        created = lighting.add_daylighting_controls(model, vintage="2020")
        self.assertEqual(1, created)
        self.assertEqual(2,
                         model.getThermalZones()[0].primaryDaylightingControl().get()
                         .numberofSteppedControlSteps(),
                         "bare add_daylighting_controls is still the legacy blanket behaviour "
                         "(placement='all')")

        other, _ = box(windows=[(0.0, 10.0, 0.0, 3.0)], space_type="Office enclosed > 25 m2")
        with self.assertRaises(ValueError):
            lighting.add_daylighting_controls(other, placement="necb2050")


if __name__ == "__main__":
    unittest.main()
