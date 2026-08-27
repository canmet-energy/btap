"""P3 gate: the 4.2.3.1 exterior allowance calculator (greenfield) and the
8.4.4.5 reference-lighting transform.

Port of btap-necb/test/test_lighting_exterior_and_reference.rb. Ruby's
ArgumentError is ValueError here (the port's standard mapping).
"""

import unittest

from tests.necb.support import load_raw_fixture, needs_sdk


def tagged_space_type(model, building_type, space_type):
    import openstudio

    st = openstudio.model.SpaceType(model)
    st.setName(f"{building_type} {space_type}")
    st.setStandardsBuildingType(building_type)
    st.setStandardsSpaceType(space_type)
    return st


@needs_sdk
class TestExteriorAndReference(unittest.TestCase):
    def test_exterior_allowance_zone3(self):
        from btap.audit import AuditLog
        from btap.necb.lighting import exterior as Exterior

        audit = AuditLog()
        result = Exterior.allowance(
            zone=3,
            quantities={"parking_and_drives_m2": 1000, "walkways_narrow_m": 50,
                        "entrances_exits_m": 10, "drive_up_windows": 2},
            audit=audit)

        self.assertEqual(500.0, result["basic_site_w"], "Table -B zone 3")
        # tradable: 1000x0.65 + 50x2.0 + 10x69 = 650 + 100 + 690 = 1440
        self.assertAlmostEqual(1440.0, result["tradable_w"], delta=0.1)
        # non-tradable: 2 x 200 W drive-throughs
        self.assertAlmostEqual(400.0, result["non_tradable_w"], delta=0.1)
        self.assertAlmostEqual(2340.0, result["total_w"], delta=0.1)
        self.assertEqual(4, len(result["lines"]))
        decision = next((e for e in audit.entries
                         if e.get("article") == "4.2.3.1." and e["level"] == "decision"), None)
        self.assertIsNotNone(decision)

    def test_exterior_zone0_and_unknown_keys_warn(self):
        from btap.audit import AuditLog
        from btap.necb.lighting import exterior as Exterior

        audit = AuditLog()
        result = Exterior.allowance(
            zone=0, quantities={"parking_and_drives_m2": 1000, "bogus_key": 5}, audit=audit)
        self.assertEqual(0.0, result["total_w"], "zone 0: no allowances anywhere")
        self.assertTrue(any("'bogus_key'" in w["action"] for w in audit.warnings))
        self.assertTrue(any("no allowance" in w["action"] and "zone 0" in w["action"]
                            for w in audit.warnings))
        with self.assertRaises(ValueError):
            Exterior.allowance(zone=9, quantities={})

    def test_apply_exterior_lights(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb.lighting import exterior as Exterior

        model = openstudio.model.Model()
        audit = AuditLog()
        lights = Exterior.apply_exterior_lights(model, 2340.0, audit=audit)
        self.assertAlmostEqual(2340.0, lights.exteriorLightsDefinition().designLevel(), delta=1e-6)
        self.assertEqual("AstronomicalClock", lights.controlOption())

    def test_reference_lighting_dwelling_rule_and_coverage(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting

        model = openstudio.model.Model()
        tagged_space_type(model, "Space Function", "Office enclosed > 25 m2")
        dwelling = tagged_space_type(model, "Space Function", "Dwelling units general")

        audit = AuditLog()
        lighting.reference_lighting(model, vintage="2020", audit=audit)

        lights = dwelling.lights()[0] if dwelling.lights() else None
        self.assertIsNotNone(lights, "dwelling space type has lights")
        self.assertAlmostEqual(5.0, lights.lightsDefinition().wattsperSpaceFloorArea().get(),
                               delta=1e-6, msg="8.4.4.5.(2): dwelling units at 5 W/m2")

        for article in ["8.4.4.5.(1)", "8.4.4.5.(2)"]:
            self.assertTrue(any(article in str(e.get("article")) for e in audit.entries), article)
        self.assertTrue(any(w["step"] == "lighting_reference"
                            and "8.4.4.5.(5)-(12)" in str(w.get("article"))
                            for w in audit.warnings),
                        "daylighting gaps are loud when reference_daylighting did NOT run "
                        "(the default)")
        self.assertTrue(any("8.4.4.5.(3)" in str(e.get("article"))
                            and "schedule modulation" in e["action"] for e in audit.entries))

    # The (5)-(12) warning is CONDITIONAL: reference_daylighting.py models and
    # audits those sentences itself, so when the caller runs it (the umbrella's
    # default since D-51) this transform must not claim they are unmodeled.
    def test_reference_lighting_daylighting_kwarg_silences_the_gap_warning(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting

        model = openstudio.model.Model()
        tagged_space_type(model, "Space Function", "Office enclosed > 25 m2")

        audit = AuditLog()
        lighting.reference_lighting(model, vintage="2020", daylighting=True, audit=audit)

        self.assertFalse(any(w["step"] == "lighting_reference"
                             and "8.4.4.5.(5)-(12)" in str(w.get("article"))
                             for w in audit.warnings),
                         "daylighting=True — (5)-(12) is modeled elsewhere, so no "
                         "'NOT modeled' warning here")
        self.assertTrue(any("8.4.4.5.(1)" in str(e.get("article")) for e in audit.entries),
                        "the rest of the reference lighting transform is unchanged")

    def test_reference_2025_prefix(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting

        model = openstudio.model.Model()
        tagged_space_type(model, "Space Function", "Office enclosed > 25 m2")
        audit = AuditLog()
        lighting.reference_lighting(model, vintage="2025", audit=audit)
        self.assertTrue(any("8.4.5.5.(1)" in str(e.get("article")) for e in audit.entries),
                        "2025 renumbered citations")

    # The shared umbrella fixture (5ZoneNoHVAC) has ASHRAE-named, NECB-untagged
    # space types used by real floor-area spaces. reference_lighting must REFUSE
    # it: an unresolvable space type would silently keep the proposed's LPD in
    # the reference (the clone), waiving the 8.4.4.5.(1) allowance. This test
    # previously asserted warn-and-skip ("never raise") — that WAS the defect.
    def test_reference_lighting_refuses_untagged_fixture(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        model = load_raw_fixture()
        audit = AuditLog()
        with self.assertRaises(ValueError) as ctx:
            lighting.reference_lighting(model, vintage="2020", audit=audit)
        self.assertIn("SmallOffice", str(ctx.exception),
                      "refusal names the unresolvable space type")
        self.assertTrue(any("UNRESOLVABLE" in str(w["action"]) for w in audit.warnings),
                        "refusal also lands in the audit trail")

    # Tagged with real catalog names, the same fixture passes the gate, warns on
    # the modelled-gap articles, and emits exactly ONE set of article-coverage
    # entries per call.
    def test_reference_lighting_tagged_fixture_single_coverage(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        model = load_raw_fixture()
        for st in model.getSpaceTypes():
            if st.spaces():
                st.setStandardsBuildingType("Space Function")
                st.setStandardsSpaceType("Office enclosed > 25 m2")
        audit = AuditLog()
        lighting.reference_lighting(model, vintage="2020", audit=audit)

        self.assertTrue(any(w["step"] == "lighting_reference"
                            and "8.4.4.5.(5)-(12)" in str(w.get("article"))
                            for w in audit.warnings),
                        "daylighting gaps still warn loudly on a run without reference_daylighting")

        coverage = [e for e in audit.entries if e["step"] == "coverage"]
        self.assertNotEqual([], coverage, "lighting article coverage emitted")
        articles = [e["article"] for e in coverage]
        self.assertEqual(len(articles), len(set(articles)),
                         "exactly one coverage entry per article (no duplicate emission)")


if __name__ == "__main__":
    unittest.main()
