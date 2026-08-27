"""P4 gate: SHW costing on the hvac engine, SHW energy alive in EnergyPlus,
and the family composition with ONE audit.

Port of btap-costing/test/test_shw_costing_e2e.rb.

Port note (M4): the Ruby fixture builds its SHW loop through
``BtapNECB::SHW.apply_shw`` on a Loads-tagged model. btap.necb is not ported
until M5, so ``shw_model`` here builds the same costing-relevant topology
directly with the SDK — a 'Main Service Water Loop' PlantLoop carrying one
WaterHeaterMixed (fuel/efficiency/capacity as the NECB layer would set them:
small-volume tanks route to the Et=0.9 'all others' row) and one constant-
speed pump. The two NECB-composition tests (EnergyPlus run of the applied
SHW schedules, family one-audit composition) were placeheld until btap.necb
landed; M5 re-enabled them and they now drive the REAL apply_loads /
apply_shw / apply_prescriptive path, as the Ruby original does.
"""

import unittest

from btap.audit import AuditLog
from tests.support import load_fixture, needs_engine, needs_sdk

# A concurrent agent may own tests/costing/support.py; import it if present,
# inline what we need otherwise (never create it here).
try:
    from tests.costing import support as costing_support  # noqa: F401
except ImportError:
    costing_support = None

CITY = "TORONTO"
PROVINCE = "ONTARIO"


def shw_model(fuel="NaturalGas"):
    """The costing-relevant equivalent of ``apply_shw`` on the tagged model:
    one 'Main Service Water Loop' with a WaterHeaterMixed and a pump."""
    import openstudio

    model = load_fixture()
    loop = openstudio.model.PlantLoop(model)
    loop.setName("Main Service Water Loop")

    tank = openstudio.model.WaterHeaterMixed(model)
    tank.setName("SHW tank")
    tank.setHeaterFuelType(fuel)
    # small-volume tanks route to the Et=0.9 'all others' row -> efficiency
    # >= 0.85 -> HE classification (PVC flue + power vent), matching legacy
    # semantics; electric tanks carry Et=1.0 as the NECB layer sets them
    tank.setHeaterThermalEfficiency(1.0 if fuel == "Electricity" else 0.9)
    tank.setHeaterMaximumCapacity(15000.0)  # 15 kW, a small office SHW tank
    tank.setTankVolume(0.19)  # ~50 gal
    loop.addSupplyBranchForComponent(tank)

    pump = openstudio.model.PumpConstantSpeed(model)
    pump.setName("SHW pump")
    pump.setRatedPowerConsumption(150.0)
    pump.addToNode(loop.supplyInletNode())
    return model


@needs_sdk
class TestCostingE2E(unittest.TestCase):
    def test_costing_gas_tank(self):
        from btap.audit import AuditLog
        from btap.costing import shw

        audit = AuditLog()
        report = shw.cost(shw_model(), city=CITY, province_state=PROVINCE, audit=audit)
        self.assertGreater(report.total, 0)
        self.assertGreaterEqual(report.shw["tanks"], 1)
        # small-volume tanks route to the Et=0.9 'all others' row -> efficiency >= 0.85
        # -> HE classification (PVC flue + power vent), matching legacy semantics
        self.assertGreaterEqual(report.shw["reg_gas"] + report.shw["he_gas"], 1)
        self.assertEqual(1, report.shw["pumps"])
        decisions = [e["action"] for e in audit.entries if e["step"] == "costing_equipment"]
        for token in ["flue", "fuel line", "utility conduit", "tank-to-pump"]:
            self.assertTrue(any(token in d for d in decisions), f"{token} costed")
        if report.shw["he_gas"] > 0:
            self.assertTrue(any("power vent" in d for d in decisions),
                            "HE tank gets a power vent")

    def test_costing_electric_tank_no_flue(self):
        from btap.audit import AuditLog
        from btap.costing import shw

        audit = AuditLog()
        report = shw.cost(shw_model(fuel="Electricity"), city=CITY,
                          province_state=PROVINCE, audit=audit)
        self.assertGreater(report.total, 0)
        self.assertGreaterEqual(report.shw["elec"], 1)
        decisions = [e["action"] for e in audit.entries if e["step"] == "costing_equipment"]
        self.assertFalse(any("flue" in d for d in decisions), "no flue for electric tanks")
        self.assertFalse(any("fuel line" in d for d in decisions),
                         "no fuel line for electric tanks")

    def test_no_shw_costs_nothing(self):
        from btap.costing import shw

        report = shw.cost(load_fixture(), city=CITY, province_state=PROVINCE)
        self.assertEqual(0.0, report.total)

    @needs_engine
    def test_shw_energy_alive_in_energyplus(self):
        # Unblocked by M5: the loop now comes from the real NECB apply_shw,
        # so this exercises the NECB SWH schedules rather than a hand-built
        # topology — the whole point of the gate.
        import tempfile

        from btap._compat import opt
        from btap.necb import loads as necb_loads
        from btap.necb import shw as necb_shw
        from btap.simulation import runner
        from tests.necb.support import tagged_model
        from tests.support import DDY, EPW

        model = tagged_model()
        audit = AuditLog()
        necb_loads.apply_loads(model, vintage="2020", audit=audit)
        necb_shw.apply_shw(model, vintage="2020", fuel="NaturalGas", audit=audit)
        for zone in model.getThermalZones():
            zone.setUseIdealAirLoads(True)

        with tempfile.TemporaryDirectory(prefix="osshw-e2e-") as tmp:
            runner.attach_weather(model, epw=str(EPW), ddy=str(DDY))
            run_dir = runner.run_energyplus(model, f"{tmp}/shw", sizing_only=False,
                                            run_period={"begin_month": 1, "begin_day": 1,
                                                        "end_month": 1, "end_day": 7})
            self.assertTrue(runner.is_clean_run(run_dir), "NECB SHW run must be clean")

            sql = opt(model.sqlFile())
            water_gj = opt(sql.execAndReturnFirstDouble(
                "SELECT SUM(Value) FROM TabularDataWithStrings WHERE "
                "ReportName='AnnualBuildingUtilityPerformanceSummary' AND "
                "TableName='End Uses' AND RowName='Water Systems' AND Units='GJ'"))
            self.assertIsNotNone(water_gj)
            self.assertGreater(water_gj, 0,
                               "water systems consume energy on the NECB SWH schedule")

    def test_family_composition_one_audit(self):
        # Unblocked by M5. ONE audit spans loads -> shw -> hvac -> envelope ->
        # costing; the family contract is that every stage writes to it.
        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.necb import envelope as necb_envelope
        from btap.necb import loads as necb_loads
        from btap.necb import shw as necb_shw
        from tests.necb.support import tagged_model

        model = tagged_model()
        audit = AuditLog()
        necb_loads.apply_loads(model, vintage="2020", audit=audit)
        necb_shw.apply_shw(model, vintage="2020", fuel="NaturalGas", audit=audit)
        modeling.build_system(model, "Baseboard gas boiler",
                              sorted_by_name(model.getThermalZones()))
        necb_envelope.apply_prescriptive(model, vintage="2020", hdd=3890, audit=audit)
        necb_shw.cost(model, city=CITY, province_state=PROVINCE, audit=audit)

        steps = list(dict.fromkeys(e["step"] for e in audit.entries))
        for step in ("loads", "shw", "shw_efficiency", "prescriptive", "costing_shw"):
            self.assertIn(step, steps)
        self.assertEqual(2, len(model.getPlantLoops()), "SHW loop + heating loop coexist")
        self.assertTrue(any("6.2.2.1" in str(e.get("article") or "") for e in audit.entries))


if __name__ == "__main__":
    unittest.main()
