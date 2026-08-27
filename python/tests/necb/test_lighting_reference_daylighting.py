"""8.4.4.5.(5)-(12): reference photocontrol evaluation — reflectances, set-point
inheritance, placement, and the E+ comparative gate (photocontrols REDUCE
lighting energy in the reference).

Port of btap-necb/test/test_lighting_reference_daylighting.rb. The Ruby gate
skips without the openstudio CLI; here the engine skip is tests.support's
``needs_engine`` (BTAP_ENGINE_REQUIRED=1 turns it into a failure).
"""

import tempfile
import unittest
from pathlib import Path

from tests.necb.support import load_raw_fixture, needs_sdk
from tests.support import DDY, EPW, needs_engine

OFFICE = ["Space Function", "Office enclosed > 25 m2"]


def windowed_office_model():
    from btap.necb import lighting, loads

    model = load_raw_fixture()
    map_ = {s.nameString(): list(OFFICE) for s in model.getSpaces()}
    loads.assign_space_types(model, map_, vintage="2020")
    for w in model.getSurfaces():
        if w.outsideBoundaryCondition() == "Outdoors" and w.surfaceType() == "Wall":
            w.setWindowToWallRatio(0.4)
    lighting.apply_lights(model, vintage="2020")
    return model


@needs_sdk
class TestReferenceDaylighting(unittest.TestCase):
    def test_reflectances_and_setpoint_inheritance(self):
        import openstudio

        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.necb import lighting

        proposed = windowed_office_model()
        control = openstudio.model.DaylightingControl(proposed)
        control.setSpace(sorted_by_name(proposed.getSpaces())[0])
        control.setIlluminanceSetpoint(555.0)

        reference = proposed.clone(True).to_Model()
        audit = AuditLog()
        lighting.reference_daylighting(reference, vintage="2020", proposed=proposed,
                                       placement="all", audit=audit)

        # (10)(b) reflectances on interior-facing layers
        floor = next(s for s in reference.getSurfaces()
                     if s.surfaceType() == "Floor" and s.construction().is_initialized())
        inner = (floor.construction().get().to_LayeredConstruction().get()
                 .layers()[-1].to_OpaqueMaterial().get())
        self.assertAlmostEqual(0.85, inner.visibleAbsorptance(), delta=1e-6,
                               msg="floor reflectance 0.15")

        # (11)(a): the proposed control's set-point wins for its space
        first_space = sorted_by_name(reference.getSpaces())[0]
        ref_control = next((c for c in reference.getDaylightingControls()
                            if c.space().is_initialized()
                            and c.space().get().nameString() == first_space.nameString()), None)
        self.assertIsNotNone(ref_control)
        self.assertAlmostEqual(555.0, ref_control.illuminanceSetpoint(), delta=1e-6,
                               msg="proposed photocontrol set-point inherited")

        # (11)(b): other spaces fall back to the space-type illuminance
        other = next(c for c in reference.getDaylightingControls()
                     if c.space().is_initialized()
                     and c.space().get().nameString() != first_space.nameString())
        self.assertAlmostEqual(400.0, other.illuminanceSetpoint(), delta=1e-6)

        for sentence in ["(10)(b)", "(10)(d)", "(5)-(8)", "(12)"]:
            self.assertTrue(any(sentence in str(e.get("article")) for e in audit.entries),
                            f"sentence {sentence} audited")

    def test_necb_default_placement_flows_through(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        reference = windowed_office_model()
        audit = AuditLog()
        lighting.reference_daylighting(reference, vintage="2020",
                                       placement="necb_default",
                                       office_match="legacy", audit=audit)
        # Post-#2119 legacy threshold semantics: the skylight criteria no longer
        # except a window-only space, and the >=25 m2 office exemption matches the
        # NECB2020 space-type names, so the legacy path DOES place controls.
        self.assertGreater(
            len(reference.getDaylightingControls()), 0,
            "legacy threshold semantics (as fixed by #2119): window-only spaces are no longer "
            "auto-excepted")
        self.assertTrue(any("LEGACY NECB 2011 THRESHOLD EVALUATION IN USE" in w["action"]
                            for w in audit.warnings),
                        "the 2011 rule still shouts that it is not the 2020/2025 requirement")
        self.assertFalse(any("'Office - enclosed'" in w["action"] for w in audit.warnings),
                         "the office-name-drift warning is obsolete: #2119 made the legacy "
                         "matcher a regex")

    @needs_engine
    def test_photocontrols_reduce_lighting_energy(self):
        from btap.necb import lighting
        from btap.simulation.runner import attach_weather, is_clean_run, run_energyplus

        lighting_gj = {}
        for label, daylighting in [("without", False), ("with", True)]:
            model = windowed_office_model()
            if daylighting:
                lighting.reference_daylighting(model, vintage="2020", placement="all")
            for z in model.getThermalZones():
                z.setUseIdealAirLoads(True)
            with tempfile.TemporaryDirectory(prefix=f"osdl-{label}-") as dir_:
                attach_weather(model, epw=EPW, ddy=DDY)
                run_dir = run_energyplus(model, Path(dir_) / "run", sizing_only=False,
                                         run_period={"begin_month": 1, "begin_day": 1,
                                                     "end_month": 1, "end_day": 7})
                self.assertTrue(is_clean_run(run_dir), f"reference daylighting {label}")
                sql = model.sqlFile().get()
                value = sql.execAndReturnFirstDouble(
                    "SELECT SUM(Value) FROM TabularDataWithStrings WHERE "
                    "ReportName='AnnualBuildingUtilityPerformanceSummary' "
                    "AND TableName='End Uses' AND RowName='Interior Lighting' AND Units='GJ'")
                lighting_gj[label] = value.get()
                model.resetSqlFile()

        self.assertLess(lighting_gj["with"], lighting_gj["without"],
                        f"photocontrols must REDUCE lighting energy (with "
                        f"{round(lighting_gj['with'], 3)} GJ vs without "
                        f"{round(lighting_gj['without'], 3)} GJ) — the evaluation is LIVE in E+")


if __name__ == "__main__":
    unittest.main()
