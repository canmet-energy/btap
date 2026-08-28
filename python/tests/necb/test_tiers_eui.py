"""Port of btap-necb/test/test_tiers_eui.rb: Section 10 tiers, the 2025
archetype-EUI path (8.4.4), and the 2025 Part 11 GHG levels."""

import tempfile
import unittest
from pathlib import Path

from btap.audit import AuditLog
from btap.necb import tiers
from tests.necb.support import DDY, EPW, needs_engine, needs_sdk, proposed_with_hvac


class TestTierArithmetic(unittest.TestCase):
    """The SDK-free arithmetic (Ruby ran these in the same class; split so
    they run everywhere)."""

    def test_tier_arithmetic(self):
        audit = AuditLog()
        self.assertEqual(1, tiers.energy_tier(95_000, 100_000,
                                              audit=audit)["tier"])
        self.assertEqual(2, tiers.energy_tier(70_000, 100_000)["tier"])
        self.assertEqual(3, tiers.energy_tier(50_000, 100_000)["tier"])
        self.assertEqual(4, tiers.energy_tier(39_000, 100_000)["tier"])
        self.assertIsNone(tiers.energy_tier(101_000, 100_000)["tier"])
        self.assertTrue(any("10.1.2.1" in str(e.get("article") or "")
                            for e in audit.entries))

    def test_eui_bet_arithmetic(self):
        audit = AuditLog()
        target = tiers.eui_building_energy_target(
            {"Office": None}, 1600.0, hdd=3890, process_loads_kwh=5000.0,
            audit=audit)
        self.assertAlmostEqual(1600.0 * 175 + 5000.0, target["bet_kwh"],
                               delta=0.1, msg="BET = A x EUI + PL")
        with self.assertRaises(ValueError):
            tiers.eui_building_energy_target({"Casino": 100}, 1600.0, hdd=3890)
        cold = AuditLog()
        tiers.eui_building_energy_target({"Office": None}, 1600.0, hdd=9500,
                                         audit=cold)
        self.assertTrue(any("HDD" in w["action"] for w in cold.warnings),
                        "HDD >= 9000 inapplicability warns")

    def test_ghg_levels(self):
        energy = {"electricity_kwh": 10_000.0, "natural_gas_kwh": 50_000.0}
        kg = tiers.operational_ghg_kg(energy, "ONTARIO")
        self.assertAlmostEqual((10_000 * 57.9 + 50_000 * 185) / 1000.0, kg,
                               delta=0.1)
        audit = AuditLog()
        level = tiers.ghg_level(kg, kg * 4, audit=audit)
        self.assertEqual("B", level["level"],
                         "25% of target -> level B (<= 25%)")
        self.assertEqual("F", tiers.ghg_level(99.0, 100.0)["level"])
        self.assertIsNone(tiers.ghg_level(101.0, 100.0)["level"])


@needs_engine
class TestEUIPathEndToEnd(unittest.TestCase):
    def test_eui_path_end_to_end(self):
        from btap.necb import performance_compliance

        dir = tempfile.mkdtemp(prefix="osnecb-eui-")
        result = performance_compliance(
            proposed_with_hvac(), vintage="2025", path="eui",
            archetypes_map={"Office": "all"},
            weather={"epw": str(EPW), "ddy": str(DDY)}, run_dir=dir,
            run_period={"begin_month": 1, "begin_day": 1, "end_month": 1,
                        "end_day": 7},
            province_state="ONTARIO")

        self.assertIsNone(result.reference_model,
                          "no reference building on the EUI path")
        bet = result.report["reference"]["building_energy_target_kwh"]
        area = result.proposed_model.getBuilding().floorArea()
        self.assertAlmostEqual(area * 175, bet, delta=1.0,
                               msg="BET from the Office archetype EUI (areas "
                                   "computed from the model)")
        self.assertFalse(result.report["eui"]["conformant_to_8_4_4_2"],
                         "bare fixture does not carry Table 8.4.4.2 inputs")
        self.assertTrue(result.report["eui"]["normalized"],
                        "proposed normalized to Table 8.4.4.2 before the run")
        self.assertTrue(
            any("8.4.4.2.(1)" in str(e.get("article") or "")
                for e in result.audit.entries),
            "normalization audited under 8.4.4.2.(1)")
        self.assertIsNotNone(result.compliant,
                             "determination made against the BET")
        self.assertIn("tier", result.report,
                      "Section 10 tier computed against the BET")
        self.assertIn("ghg_kg_co2e", result.report["proposed"],
                      "2025 GHG computed with a province")
        self.assertTrue(any("8.4.4.1." in str(e.get("article") or "")
                            for e in result.audit.entries))


@needs_sdk
class TestEUIPathGuards(unittest.TestCase):
    def test_eui_path_guards(self):
        from btap.necb import performance_compliance

        with self.assertRaises(ValueError):
            performance_compliance(
                proposed_with_hvac(), vintage="2020", path="eui",
                archetypes_map={"Office": "all"},
                run_dir=tempfile.mkdtemp(prefix="osnecb-x-"))

    def test_eui_path_refuses_outside_applicability(self):
        # 8.4.4.1.(1)/Table-note applicability REFUSES on the pure 'eui' path
        # — a verdict outside applicability is not a determination.
        from btap.necb import performance_compliance

        with self.assertRaises(ValueError) as ctx:
            performance_compliance(
                proposed_with_hvac(), vintage="2025", path="eui",
                simulate="none", hdd=9500, archetypes_map={"Office": "all"},
                run_dir=tempfile.mkdtemp(prefix="osnecb-hdd-"))
        self.assertIn("NOT applicable", str(ctx.exception))
        self.assertIn("HDD 9500", str(ctx.exception))
        # the refusal still flushed the audit trail (Ruby asserted this
        # implicitly through the pipeline's failure flush)
        run_dirs = list(Path(tempfile.gettempdir()).glob("osnecb-hdd-*"))
        self.assertTrue(any((d / "audit.txt").exists() for d in run_dirs))


if __name__ == "__main__":
    unittest.main()
