"""P2 gate (standalone half): LPD application, sensor-schedule synthesis above the
8.6 W/m2 threshold, LED path with the fixed atrium height rule, coverage.

Port of btap-necb/test/test_lighting_apply_lights.rb.
"""

import unittest

from tests.necb.support import needs_sdk

OFFICE = ["Space Function", "Office enclosed > 25 m2"]           # 6.9 W/m2 < threshold
CONFERENCE = ["Space Function", "Conference/Meeting/Multi-purpose room"]  # 10.5 W/m2 > threshold


def tagged_space_type(model, building_type, space_type):
    """Ruby FixtureHelper#tagged_space_type."""
    import openstudio

    st = openstudio.model.SpaceType(model)
    st.setName(f"{building_type} {space_type}")
    st.setStandardsBuildingType(building_type)
    st.setStandardsSpaceType(space_type)
    return st


@needs_sdk
class TestApplyLights(unittest.TestCase):
    def test_plain_lpd_below_threshold(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting
        from btap.necb.loads import space_types as SpaceTypes

        model = openstudio.model.Model()
        st = tagged_space_type(model, *OFFICE)
        lighting.apply_lights(model, vintage="2020", audit=AuditLog())

        record = SpaceTypes.record(building_type=OFFICE[0], space_type=OFFICE[1])
        lights = st.lights()[0]
        self.assertIsNotNone(lights)
        expected = openstudio.convert(float(record["lighting_per_area"]), "W/ft^2", "W/m^2").get()
        self.assertAlmostEqual(expected, lights.lightsDefinition().wattsperSpaceFloorArea().get(),
                               delta=1e-9)
        self.assertAlmostEqual(float(record["lighting_fraction_radiant"]),
                               lights.lightsDefinition().fractionRadiant(), delta=1e-9)

        schedule = st.defaultScheduleSet().get().lightingSchedule()
        self.assertTrue(schedule.is_initialized())
        self.assertEqual(record["lighting_schedule"], schedule.get().nameString(),
                         "plain schedule below 8.6 W/m2")

    def test_sensor_schedule_synthesis_above_threshold(self):
        import re

        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting, loads
        from btap.necb.loads import space_types as SpaceTypes

        model = openstudio.model.Model()
        st = tagged_space_type(model, *CONFERENCE)
        audit = AuditLog()
        lighting.apply_lights(model, vintage="2020", audit=audit)

        record = SpaceTypes.record(building_type=CONFERENCE[0], space_type=CONFERENCE[1])
        self.assertGreater(float(record["lighting_per_area"]), 0.799256505,
                           "fixture premise: above threshold")

        schedule = st.defaultScheduleSet().get().lightingSchedule().get()
        self.assertTrue(re.search(r"-Light Ruleset\Z", schedule.nameString()),
                        "synthesized sensor ruleset wired")

        # occupied-hour value == original; deep-night value == original x occ_control
        ruleset = schedule.to_ScheduleRuleset().get()
        default = ruleset.defaultDaySchedule()
        rel = float(record["rel_absence_occ"])
        control = 1 - (rel * float(record["occ_sense"])) - float(record["personal_control"])
        lighting_rows = [r for r in loads.table("2020", "schedules")
                         if r["name"] == record["lighting_schedule"]]
        occupancy_rows = [r for r in loads.table("2020", "schedules")
                          if r["name"] == record["occupancy_schedule"]]
        base = next(r for r in lighting_rows if "Default" in r["day_types"])["values"]
        occ = next(r for r in occupancy_rows if "Default" in r["day_types"])["values"]
        for hour in range(24):
            expected = (float(base[hour]) * control if float(occ[hour]) < rel
                        else float(base[hour]))
            actual = default.getValue(openstudio.Time(0, hour + 1, 0, 0))
            self.assertAlmostEqual(expected, actual, delta=1e-6, msg=f"hour {hour + 1}")
        self.assertTrue(any("occupancy-sensor lighting schedule synthesized" in e["action"]
                            for e in audit.entries))

    def test_led_path_and_atrium_height_fix(self):
        import re

        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting

        model = openstudio.model.Model()
        st = tagged_space_type(model, *OFFICE)
        lighting.apply_lights(model, vintage="2020", lights_type="LED", audit=AuditLog())
        led = lighting.led_record(building_type=OFFICE[0], space_type=OFFICE[1])
        lights = st.lights()[0]
        expected = openstudio.convert(float(led["lighting_per_area"]), "W/ft^2", "W/m^2").get()
        self.assertAlmostEqual(expected, lights.lightsDefinition().wattsperSpaceFloorArea().get(),
                               delta=1e-9)
        self.assertTrue(re.search(r"LED lighting", lights.lightsDefinition().nameString()))

        # atrium: a 9 m-tall space drives the below-12m equation (legacy raises NameError here)
        atrium_model = openstudio.model.Model()
        atrium_st = tagged_space_type(atrium_model, "Space Function", "Atrium (height < 6m)-sch-A")
        space = openstudio.model.Space(atrium_model)
        space.setSpaceType(atrium_st)
        wall_points = openstudio.Point3dVector(
            [openstudio.Point3d(x, y, z)
             for x, y, z in [(0, 0, 9), (0, 0, 0), (10, 0, 0), (10, 0, 9)]])
        openstudio.model.Surface(wall_points, atrium_model).setSpace(space)
        audit = AuditLog()
        lighting.apply_lights(atrium_model, vintage="2020", lights_type="LED", audit=audit)

        atrium_decision = next((e for e in audit.entries if "LED atrium LPD" in e["action"]), None)
        self.assertIsNotNone(atrium_decision, "atrium equation exercised (legacy NameError path)")
        self.assertAlmostEqual(9.0, atrium_decision["inputs"]["height_m"], delta=0.01)
        expected_w_ft2 = (0.0 + 1.06 * 9.0) * 0.092903
        lights = atrium_st.lights()[0]
        self.assertAlmostEqual(
            openstudio.convert(expected_w_ft2, "W/ft^2", "W/m^2").get(),
            lights.lightsDefinition().wattsperSpaceFloorArea().get(), delta=1e-6)

    def test_scale_and_coverage(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import lighting
        from btap.necb.loads import space_types as SpaceTypes

        model = openstudio.model.Model()
        st = tagged_space_type(model, *OFFICE)
        audit = AuditLog()
        lighting.apply_lights(model, vintage="2020", lights_scale=0.5, audit=audit)
        record = SpaceTypes.record(building_type=OFFICE[0], space_type=OFFICE[1])
        expected = openstudio.convert(float(record["lighting_per_area"]) * 0.5,
                                      "W/ft^2", "W/m^2").get()
        self.assertAlmostEqual(expected,
                               st.lights()[0].lightsDefinition().wattsperSpaceFloorArea().get(),
                               delta=1e-9)

        coverage = [e for e in audit.entries if e["step"] == "coverage"]
        self.assertGreaterEqual(len(coverage), 7)
        self.assertTrue(any(e["level"] == "warning" for e in coverage),
                        "not_implemented/partial articles warn")


if __name__ == "__main__":
    unittest.main()
