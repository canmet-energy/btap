"""P1-P3 gates: rules data, demand/plant construction, and the efficiency bins.

Port of btap-necb/test/test_shw_shw.rb.
"""

from __future__ import annotations

import re
import unittest

from tests.necb.support import load_raw_fixture, needs_sdk, tagged_model


class TestSHWRules(unittest.TestCase):
    """The ruleset gates — SDK-free (JSON only)."""

    def test_rules_and_coverage_lint(self):
        from btap.necb import shw

        for vintage in ("2020", "2025"):
            rules = shw.rules(vintage)
            self.assertEqual(0.82, rules["efficiency"]["fuel_fired"]["burner_efficiency"])
            plc = rules["efficiency"]["part_load_curve"]
            self.assertEqual([0.7576, 1.0071, -1.4443, 0.6844], plc["coefficients"])
            self.assertEqual("Cubic", plc["form"])
            self.assertEqual(["NaturalGas", "FuelOilNo2"], plc["applies_to"],
                             "article scope: fuel-fired only")
            # 8.4.5.9.(2) in 2020, renumbered 8.4.6.9.(2) in 2025 (directional —
            # the 2025 SWH article is 8.4.6.9, NOT 8.4.5.9).
            self.assertEqual("8.4.6.9.(2)" if vintage == "2025" else "8.4.5.9.(2)",
                             plc["article"])
            self.assertEqual([0.021826, 0.97763, 0.000543],
                             plc["code_fheatplc"]["coefficients"])
            coverage = rules["article_coverage"]["articles"]
            self.assertGreaterEqual(len(coverage), 6)
            for a in coverage:
                self.assertTrue(a.get("how") or a.get("gaps"))
        # Vintage aliasing is owned by the loads domain (btap.necb.loads.data_vintage,
        # called directly from shw/demand.py) — shw does not vendor its own
        # data_vintage_alias key (removed as dead config; see provenance.note).
        self.assertIsNone(shw.rules("2025").get("data_vintage_alias"))
        self.assertRegex(shw.rules("2025")["changes_vs_2020"]["heat_pump_storage_water_heater"],
                         r"UEF >= 2\.23")

    # 8.4.5.9.(2) / 8.4.6.9.(2). FUNCTIONAL gate, not a coefficient pin: the code
    # writes a fuel-ratio curve (Fuel_pl = Fuel_des x FHeatPLC) while the E+
    # part-load-factor field is a degradation divisor (fuel = Q/(eta x PLF)), so
    # the model curve must satisfy x / PLF(x) ~= FHeatPLC(x). Comparing the
    # vendored cubic to the code quadratic coefficient-wise would be meaningless.
    def test_part_load_curve_is_functionally_the_code_fheatplc(self):
        from btap.necb import shw

        for vintage in ("2020", "2025"):
            plc = shw.rules(vintage)["efficiency"]["part_load_curve"]
            cubic = plc["coefficients"]
            a, b, c = plc["code_fheatplc"]["coefficients"]

            def poly(k, x):
                return sum(v * (x ** i) for i, v in enumerate(k))

            def fheatplc(x, a=a, b=b, c=c):
                return a + (b * x) + (c * x * x)

            # self-check the code polynomial at its rating point before trusting it
            self.assertAlmostEqual(1.0, fheatplc(1.0), delta=1e-5,
                                   msg=f"{vintage}: FHeatPLC(1.0) must be ~1.0")
            self.assertAlmostEqual(1.0, poly(cubic, 1.0), delta=5e-3,
                                   msg=f"{vintage}: applied PLF(1.0) must be ~1.0")

            worst = max(abs((x / poly(cubic, x)) - fheatplc(x)) / fheatplc(x)
                        for x in (pct / 100.0 for pct in range(25, 101, 5)))
            self.assertLess(worst, 0.03,
                            f"{vintage}: applied curve deviates {worst * 100:.2f}% from "
                            "the code FHeatPLC")


@needs_sdk
class TestSHW(unittest.TestCase):
    def test_apply_shw_builds_loop_and_demand(self):
        from btap.audit import AuditLog
        from btap.necb import shw

        model = tagged_model()
        audit = AuditLog()
        loop = shw.apply_shw(model, vintage="2020", fuel="NaturalGas", audit=audit)

        self.assertIsNotNone(loop)
        heaters = model.getWaterHeaterMixeds()
        self.assertTrue(heaters)
        heater = heaters[0]
        self.assertGreater(heater.tankVolume().get(), 0)
        self.assertGreater(heater.heaterMaximumCapacity().get(), 0)
        self.assertEqual("NaturalGas", heater.heaterFuelType())
        self.assertTrue(heater.partLoadFactorCurve().is_initialized(),
                        "SWH-EFFFPLR curve applied")
        self.assertRegex(heater.nameString(), r"Therm Eff",
                         "efficiency applied on the sized heater")

        equipment = model.getWaterUseEquipments()
        self.assertEqual(5, len(equipment), "one water use per demanding space")
        for wue in equipment:
            self.assertTrue(wue.space().is_initialized())
            self.assertTrue(wue.flowRateFractionSchedule().is_initialized())
            self.assertRegex(wue.flowRateFractionSchedule().get().nameString(),
                             r"^NECB-A-Service Water Heating")
            self.assertGreater(wue.waterUseEquipmentDefinition().peakFlowRate(), 0)
        self.assertEqual(5, len(model.getWaterUseConnectionss()))
        self.assertTrue(any("auto-sized" in e["action"] for e in audit.entries))
        self.assertTrue(not audit.warnings
                        or not any("schedule" in w["action"] for w in audit.warnings))

    def test_no_demand_no_loop(self):
        from btap.audit import AuditLog
        from btap.necb import shw

        model = load_raw_fixture()  # untagged: no space types -> no SHW demand
        audit = AuditLog()
        result = shw.apply_shw(model, vintage="2020", audit=audit)
        self.assertIsNone(result)
        self.assertEqual([], list(model.getPlantLoops()))
        self.assertTrue(any("no SHW loop added" in e["action"] for e in audit.entries))

    def test_efficiency_bins_golden(self):
        import openstudio

        from btap._compat import ruby_round
        from btap.audit import AuditLog
        from btap.necb import shw

        model = openstudio.model.Model()
        # gas 150 L / 15 kW -> 76-208 L ladder; FHR = 0.7x150+151 = 256 -> 193-284 bin
        heater = openstudio.model.WaterHeaterMixed(model)
        heater.setTankVolume(0.150)
        heater.setHeaterMaximumCapacity(15_000)
        heater.setHeaterFuelType("NaturalGas")
        audit = AuditLog()
        shw.apply_water_heater_efficiency(heater, vintage="2020", audit=audit)

        self.assertAlmostEqual(0.82, heater.heaterThermalEfficiency().get(), delta=1e-9,
                               msg="burner efficiency")
        uef = 0.6483 - 0.00045 * 150
        decision = next(e for e in audit.entries
                        if e["step"] == "shw_efficiency" and e["level"] == "decision")
        self.assertRegex(decision["evidence"], f"UEF {re.escape(str(ruby_round(uef, 4)))}")
        self.assertGreater(heater.offCycleLossCoefficienttoAmbientTemperature().get(), 0)

        # electric small: 12 kW / 200 L -> SL = 40 + 0.2x200 = 80 W
        electric = openstudio.model.WaterHeaterMixed(model)
        electric.setTankVolume(0.200)
        electric.setHeaterMaximumCapacity(11_000)
        electric.setHeaterFuelType("Electricity")
        shw.apply_water_heater_efficiency(electric, vintage="2020", audit=audit)
        self.assertAlmostEqual(1.0, electric.heaterThermalEfficiency().get(), delta=1e-9)
        expected_ua = openstudio.convert(80.0, "W", "Btu/hr").get() / 70.0
        expected_ua_si = openstudio.convert(expected_ua, "Btu/hr*R", "W/K").get()
        self.assertAlmostEqual(
            expected_ua_si, electric.offCycleLossCoefficienttoAmbientTemperature().get(),
            delta=1e-6)

        # large gas: 100 kW / 500 L -> Et 0.9 + SL formula
        large = openstudio.model.WaterHeaterMixed(model)
        large.setTankVolume(0.500)
        large.setHeaterMaximumCapacity(100_000)
        large.setHeaterFuelType("NaturalGas")
        shw.apply_water_heater_efficiency(large, vintage="2020", audit=audit)
        self.assertGreater(large.heaterThermalEfficiency().get(), 0.9,
                           "Et + UA/capacity adjustment")

    # The curve builder must honour the declared form rather than assume Cubic —
    # a Quadratic spec is built as a Curve:Quadratic, not faked with a zero cubic
    # term, and a mis-shaped spec raises instead of being silently accepted.
    def test_part_load_curve_builder_honours_form(self):
        import openstudio

        from btap.necb.shw import efficiency

        model = openstudio.model.Model()
        quad = efficiency.part_load_curve(
            model, {"name": "Probe Quadratic", "form": "Quadratic",
                    "coefficients": [0.021826, 0.97763, 0.000543]})
        self.assertTrue(quad.to_CurveQuadratic().is_initialized(),
                        "Quadratic form builds a Curve:Quadratic")
        self.assertAlmostEqual(1.0,
                               quad.to_CurveQuadratic().get().coefficient1Constant()
                               + quad.to_CurveQuadratic().get().coefficient2x()
                               + quad.to_CurveQuadratic().get().coefficient3xPOW2(),
                               delta=1e-5)

        # Ruby ArgumentError -> Python ValueError (the port's raise convention).
        with self.assertRaises(ValueError):
            efficiency.part_load_curve(
                model, {"name": "Bad", "form": "Quadratic",
                        "coefficients": [1.0, 2.0, 3.0, 4.0]})
        with self.assertRaises(ValueError):
            efficiency.part_load_curve(
                model, {"name": "Bad2", "form": "Quartic", "coefficients": [1.0]})

    # Scope of 8.4.5.9 is the ARTICLE's: fuel-fired storage AND instantaneous get
    # the curve; electric gets none, and says so in the audit.
    def test_part_load_curve_scope_by_fuel_and_type(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import shw

        model = openstudio.model.Model()

        def build(fuel, volume_m3):
            h = openstudio.model.WaterHeaterMixed(model)
            h.setName(f"Probe {fuel} {volume_m3}")
            h.setHeaterFuelType(fuel)
            h.setHeaterMaximumCapacity(30_000)
            h.setTankVolume(volume_m3)
            audit = AuditLog()
            shw.apply_water_heater_efficiency(h, vintage="2020", audit=audit)
            return h, audit

        gas_storage, _ = build("NaturalGas", 0.3)
        self.assertTrue(gas_storage.partLoadFactorCurve().is_initialized(),
                        "fuel-fired storage carries the curve")

        gas_inst, inst_audit = build("NaturalGas", 0.005)  # 5 L -> instantaneous bound
        self.assertTrue(gas_inst.partLoadFactorCurve().is_initialized(),
                        "fuel-fired INSTANTANEOUS carries the curve — 8.4.5.9 draws no "
                        "storage/instantaneous distinction")
        self.assertTrue(any(e.get("ruling") == "D-53" and e["level"] == "decision"
                            for e in inst_audit.entries))

        oil_inst, _ = build("FuelOilNo2", 0.005)
        self.assertTrue(oil_inst.partLoadFactorCurve().is_initialized(),
                        "oil instantaneous is fuel-fired too")

        elec, elec_audit = build("Electricity", 0.3)
        self.assertFalse(elec.partLoadFactorCurve().is_initialized(),
                         "electric is outside the article scope")
        scope = next((e for e in elec_audit.entries if e.get("ruling") == "D-53"), None)
        self.assertIsNotNone(scope, "the out-of-scope skip is AUDITED, not silent")
        self.assertRegex(scope["action"], r"article scope")

    def test_reference_shw_coverage(self):
        from btap.audit import AuditLog
        from btap.necb import shw

        model = tagged_model()
        shw.apply_shw(model, vintage="2020", fuel="Electricity")
        audit = AuditLog()
        shw.reference_shw(model, vintage="2020", audit=audit)
        self.assertTrue(any(e.get("article") == "8.4.4.20.(1)" for e in audit.entries))
        coverage = [e for e in audit.entries if e["step"] == "coverage"]
        self.assertGreaterEqual(len(coverage), 6)
        self.assertTrue(any(e["level"] == "warning" for e in coverage), "gaps warn")
