"""P5 gate: gem-built lighting is ALIVE in EnergyPlus, and the full gem family
composes: loads -> lighting -> hvac -> envelope on ONE model with ONE audit.

Port of btap-necb/test/test_lighting_e2e_run.rb. The Ruby gate skips without
the openstudio CLI; here the engine skip is tests.support's ``needs_engine``
(BTAP_ENGINE_REQUIRED=1 turns it into a failure).
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.necb.support import load_raw_fixture, needs_sdk
from tests.support import DDY, EPW, needs_engine

OFFICE = ["Space Function", "Office enclosed > 25 m2"]


def loaded_lit_model():
    from btap.necb import loads

    model = load_raw_fixture()
    for lights in model.getLightss():
        lights.remove()
    for definition in model.getLightsDefinitions():
        definition.remove()
    map_ = {s.nameString(): list(OFFICE) for s in model.getSpaces()}
    loads.assign_space_types(model, map_, vintage="2020")
    loads.apply_loads(model, vintage="2020")
    return model


@needs_sdk
class TestE2ERun(unittest.TestCase):
    @needs_engine
    def test_lighting_energy_alive_in_energyplus(self):
        from btap.audit import AuditLog
        from btap.necb import lighting
        from btap.simulation.runner import attach_weather, is_clean_run, run_energyplus

        model = loaded_lit_model()
        audit = AuditLog()
        lighting.apply_lights(model, vintage="2020", audit=audit)

        with tempfile.TemporaryDirectory(prefix="oslight-e2e-") as dir_:
            attach_weather(model, epw=EPW, ddy=DDY)
            for z in model.getThermalZones():
                z.setUseIdealAirLoads(True)
            run_dir = run_energyplus(model, Path(dir_) / "lights", sizing_only=False,
                                     run_period={"begin_month": 1, "begin_day": 1,
                                                 "end_month": 1, "end_day": 7})
            self.assertTrue(is_clean_run(run_dir), "NECB lighting")

            sql = model.sqlFile().get()
            lighting_gj = sql.execAndReturnFirstDouble(
                "SELECT SUM(Value) FROM TabularDataWithStrings WHERE "
                "ReportName='AnnualBuildingUtilityPerformanceSummary' "
                "AND TableName='End Uses' AND RowName='Interior Lighting' AND Units='GJ'")
            self.assertTrue(lighting_gj.is_initialized())
            self.assertGreater(lighting_gj.get(), 0,
                               "interior lighting consumes energy on the NECB schedule")
            model.resetSqlFile()

    def test_full_family_composition_one_audit(self):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.necb import envelope, lighting

        model = loaded_lit_model()
        audit = AuditLog()
        lighting.apply_lights(model, vintage="2020", audit=audit)
        modeling.build_system(model, "Baseboard gas boiler",
                              sorted_by_name(model.getThermalZones()))
        envelope.apply_prescriptive(model, vintage="2020", hdd=3890, audit=audit)
        lighting.cost(model, vintage="2020", city="TORONTO", province_state="ONTARIO",
                      audit=audit)

        steps = {e["step"] for e in audit.entries}
        for step in ["lighting", "coverage", "prescriptive", "costing_lighting"]:
            self.assertIn(step, steps)
        self.assertNotEqual([], [light for st in model.getSpaceTypes() for light in st.lights()],
                            "lights present")
        self.assertNotEqual([], list(model.getPlantLoops()), "HVAC present")
        entries = json.loads(audit.to_json())
        self.assertGreater(len(entries), 25,
                           "ONE audit spans lighting apply + envelope + lighting costing")


if __name__ == "__main__":
    unittest.main()
