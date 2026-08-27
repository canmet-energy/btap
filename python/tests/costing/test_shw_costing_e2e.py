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
SHW schedules, family one-audit composition) cannot run without btap.necb
and SKIP loudly with that reason until M5 re-enables them.
"""

import unittest

from tests.support import load_fixture, needs_sdk

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

    @unittest.skip("needs btap.necb (M5): apply_shw builds the NECB SWH schedules "
                   "this EnergyPlus gate exercises")
    def test_shw_energy_alive_in_energyplus(self):
        self.fail("unreachable until btap.necb lands (M5)")

    @unittest.skip("needs btap.necb (M5): Loads/SHW/Envelope application drive the "
                   "one-audit family composition")
    def test_family_composition_one_audit(self):
        self.fail("unreachable until btap.necb lands (M5)")


if __name__ == "__main__":
    unittest.main()
