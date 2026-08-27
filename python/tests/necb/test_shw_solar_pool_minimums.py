"""D-63 — Table 6.2.2.1 solar-thermal + pool-heater minimums, apply-when-present.
The printed rows were LOST from the extraction in both editions (hbix table
audit 2026-08-02); values come from the vendored solar_pool_minimums block.

Port of btap-necb/test/test_shw_solar_pool_minimums.rb.
"""

from __future__ import annotations

import unittest

from tests.necb.support import needs_sdk


@needs_sdk
class TestSolarPoolMinimums(unittest.TestCase):
    def spec(self):
        from btap.necb import shw
        return shw.rules("2020")["solar_pool_minimums"]

    def pool_model(self, fuel):
        import openstudio
        model = openstudio.model.Model()
        # A floor surface to host the indoor pool.
        space = openstudio.model.Space(model)
        pts = openstudio.Point3dVector()
        for x, y, z in ([0, 0, 0], [0, 5, 0], [5, 5, 0], [5, 0, 0]):
            pts.append(openstudio.Point3d(x, y, z))
        floor = openstudio.model.Surface(pts, model)
        floor.setSpace(space)
        floor.setSurfaceType("Floor")

        pool = openstudio.model.SwimmingPoolIndoor(model, floor)
        heater = openstudio.model.WaterHeaterMixed(model)
        heater.setHeaterFuelType(fuel)
        heater.setHeaterThermalEfficiency(0.95)

        loop = openstudio.model.PlantLoop(model)
        loop.addSupplyBranchForComponent(heater)
        loop.addDemandBranchForComponent(pool)
        return model, heater

    def test_vendored_values_match_the_printed_rows(self):
        spec = self.spec()
        self.assertEqual(0.82, spec["pool_gas_thermal_efficiency"])
        self.assertEqual(0.78, spec["pool_oil_thermal_efficiency"])
        self.assertEqual(4.0, spec["pool_heat_pump_cop"])
        self.assertEqual(1.4, spec["solar_sef_aux_electric"])
        self.assertEqual(0.9, spec["solar_sef_aux_gas"])

    def test_gas_pool_heater_takes_the_printed_minimum(self):
        from btap.audit import AuditLog
        from btap.necb.shw import efficiency

        model, heater = self.pool_model("NaturalGas")
        audit = AuditLog()
        efficiency.apply_solar_pool_minimums(model, vintage="2020", audit=audit)
        self.assertAlmostEqual(0.82, heater.heaterThermalEfficiency().get(), delta=1e-9)
        entry = next((e for e in audit.entries
                      if "pool heater set to the Table 6.2.2.1 minimum" in e["action"]), None)
        self.assertIsNotNone(entry)
        self.assertIn("D-63", str(entry.get("ruling") or ""))

    def test_oil_pool_heater_takes_its_row_and_electric_is_audited_not_forced(self):
        from btap.audit import AuditLog
        from btap.necb.shw import efficiency

        model, heater = self.pool_model("FuelOilNo2")
        efficiency.apply_solar_pool_minimums(model, vintage="2020", audit=AuditLog())
        self.assertAlmostEqual(0.78, heater.heaterThermalEfficiency().get(), delta=1e-9)

        model, heater = self.pool_model("Electricity")
        audit = AuditLog()
        efficiency.apply_solar_pool_minimums(model, vintage="2020", audit=audit)
        self.assertAlmostEqual(0.95, heater.heaterThermalEfficiency().get(), delta=1e-9,
                               msg="no printed electric pool row — left as cloned")
        self.assertTrue(any("no Table 6.2.2.1 pool row" in e["action"]
                            for e in audit.entries))

    def test_solar_collectors_get_the_rating_level_determination(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb.shw import efficiency

        model = openstudio.model.Model()
        openstudio.model.SolarCollectorFlatPlateWater(model)
        audit = AuditLog()
        efficiency.apply_solar_pool_minimums(model, vintage="2020", audit=audit)
        entry = next((e for e in audit.entries if "Solar Energy" in e["action"]), None)
        self.assertIsNotNone(entry, "solar SEF determination recorded")
        self.assertIn("RATING", entry["action"])
        self.assertIn("D-63", str(entry.get("ruling") or ""))

    def test_no_op_without_pools_or_collectors(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.necb.shw import efficiency

        model = openstudio.model.Model()
        openstudio.model.WaterHeaterMixed(model)
        audit = AuditLog()
        efficiency.apply_solar_pool_minimums(model, vintage="2020", audit=audit)
        self.assertEqual([], [e for e in audit.entries
                              if "D-63" in str(e.get("ruling") or "")],
                         "apply-when-present: silent no-op")
