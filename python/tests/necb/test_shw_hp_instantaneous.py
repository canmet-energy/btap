"""HP + instantaneous water heaters (the last SHW backlog item minus vintages).

Port of btap-necb/test/test_shw_hp_instantaneous.rb.
"""

from __future__ import annotations

import unittest

from tests.necb.support import needs_sdk, tagged_model


@needs_sdk
class TestHPInstantaneous(unittest.TestCase):
    def instantaneous_heater(self, model, fuel, capacity_w):
        import openstudio
        heater = openstudio.model.WaterHeaterMixed(model)
        heater.setTankVolume(0.005)  # 5 L -> instantaneous bound (<= 7.6 L)
        heater.setHeaterMaximumCapacity(capacity_w)
        heater.setHeaterFuelType(fuel)
        return heater

    def test_instantaneous_bins(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb import shw

        model = openstudio.model.Model()
        audit = AuditLog()

        small_gas = self.instantaneous_heater(model, "NaturalGas", 40_000)
        shw.apply_water_heater_efficiency(small_gas, vintage="2020", audit=audit)
        self.assertAlmostEqual(0.86, small_gas.heaterThermalEfficiency().get(), delta=1e-9,
                               msg="gas < 59 kW: conservative UEF row")
        self.assertAlmostEqual(
            0.0, small_gas.offCycleLossCoefficienttoAmbientTemperature().get(),
            delta=1e-9, msg="tankless: zero UA")

        big_gas = self.instantaneous_heater(model, "NaturalGas", 100_000)
        shw.apply_water_heater_efficiency(big_gas, vintage="2020", audit=audit)
        self.assertAlmostEqual(0.94, big_gas.heaterThermalEfficiency().get(), delta=1e-9,
                               msg="gas all others: Et 0.94")

        oil = self.instantaneous_heater(model, "FuelOilNo2", 40_000)
        shw.apply_water_heater_efficiency(oil, vintage="2020", audit=audit)
        self.assertAlmostEqual(0.80, oil.heaterThermalEfficiency().get(), delta=1e-9)

        self.assertTrue(any("instantaneous rows" in str(e.get("article") or "")
                            for e in audit.entries))
        self.assertTrue(any("conservative" in str(e.get("evidence") or "")
                            for e in audit.entries), "flow assumption audited")

    def test_heat_pump_water_heater_build_and_floor(self):
        from btap.audit import AuditLog
        from btap.necb import shw

        model = tagged_model()
        audit = AuditLog()
        loop = shw.apply_shw(model, vintage="2020", fuel="HeatPump", audit=audit)

        self.assertIsNotNone(loop)
        hpwhs = model.getWaterHeaterHeatPumps()
        self.assertEqual(1, len(hpwhs), "pumped-condenser HPWH built")
        hpwh = hpwhs[0]
        tank = hpwh.tank().to_WaterHeaterMixed().get()
        self.assertEqual("Electricity", tank.heaterFuelType())
        self.assertGreater(tank.tankVolume().get(), 0,
                           "loop tank wrapped (not the default throwaway tank)")
        self.assertTrue(hpwh.thermalZone().is_initialized(), "compressor placed in a zone")

        coil = hpwh.dXCoil().to_CoilWaterHeatingAirToWaterHeatPump().get()
        self.assertAlmostEqual(2.1, coil.ratedCOP(), delta=1e-9,
                               msg="2020 EF floor as rated COP")
        self.assertTrue(any("conservative" in e["action"]
                            and "heat pump" in str(e.get("article") or "")
                            for e in audit.entries))

    def test_2025_uef_floor(self):
        from btap.necb import shw

        model = tagged_model()
        shw.apply_shw(model, vintage="2025", fuel="HeatPump")
        coil = (model.getWaterHeaterHeatPumps()[0]
                .dXCoil().to_CoilWaterHeatingAirToWaterHeatPump().get())
        self.assertAlmostEqual(2.23, coil.ratedCOP(), delta=1e-9, msg="2025 UEF floor")

    def test_hphw_costing_detection(self):
        from btap.audit import AuditLog
        from btap.necb import shw

        model = tagged_model()
        shw.apply_shw(model, vintage="2020", fuel="HeatPump")
        audit = AuditLog()
        report = shw.cost(model, city="TORONTO", province_state="ONTARIO", audit=audit)
        self.assertGreaterEqual(report.shw["hphw"], 1, "HPWH tank costed as HPHW_Heater")
        self.assertEqual(0, report.shw["elec"],
                         "not double-counted as a plain electric tank")
        decisions = [e["action"] for e in audit.entries
                     if e["step"] == "costing_equipment"]
        self.assertFalse(any("flue" in d for d in decisions), "no flue for HPWH")
        # legacy: HPHW tanks are EXCLUDED from the electric utility wire/conduit run
        self.assertFalse(any("utility conduit" in d for d in decisions),
                         "HPHW excluded from the electric utility run")
