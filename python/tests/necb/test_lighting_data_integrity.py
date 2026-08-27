"""P1 gate: vendored lighting data is sound and the 2025 verification holds.

Port of btap-necb/test/test_lighting_data_integrity.rb. SDK-free except for the
2020-LPD spot check, which reads the loads catalog (no model objects).
"""

import re
import unittest

from btap.necb import lighting


class TestDataIntegrity(unittest.TestCase):
    def test_led_table_matches_legacy_shape(self):
        led = lighting.table("led_lighting_2020")
        self.assertEqual(308, len(led))
        record = lighting.led_record(building_type="Space Function",
                                     space_type="Office enclosed > 25 m2")
        self.assertIsNotNone(record)
        self.assertGreater(float(record["lighting_per_area"]), 0)
        self.assertIn("lighting_fraction_radiant", record)

    def test_2025_space_function_table(self):
        rows = lighting.table("lpd_space_functions_2025")
        self.assertGreaterEqual(len(rows), 90)
        atrium = [r["lpd_w_per_m2"] for r in rows if r["space_category"] == "Atrium"]
        self.assertEqual([4.2, 5.2, 6.5], sorted(atrium), "2025 atrium bins == 2020 legacy values")
        office = next((r for r in rows
                       if r["space_category"] == "Office"
                       or "enclosed" in ("" if r["space_type"] is None else str(r["space_type"]))),
                      None)
        self.assertIsNotNone(office)
        with_controls = sum(1 for r in rows if r["controls_4_2_2_1"] != "")
        self.assertGreater(with_controls, 80, "the 2025 4.2.2.1 control matrix is vendored")

    def test_2025_building_type_table(self):
        rows = lighting.table("lpd_building_types_2025")
        self.assertEqual(32, len(rows))
        office = next(r for r in rows if r["building_type"] == "Office")
        self.assertAlmostEqual(6.9, office["lpd_w_per_m2"], delta=1e-9)
        garage = next(r for r in rows if r["building_type"] == "Storage garage")
        self.assertAlmostEqual(1.9, garage["lpd_w_per_m2"], delta=1e-9)

    def test_2020_lpds_spot_verified_vs_space_types(self):
        from btap.necb.loads import space_types as SpaceTypes

        # atrium bins in the loads-gem space-type records equal the code values
        for letter in ["A"]:
            for name, si in {f"Atrium (height < 6m)-sch-{letter}": 4.2,
                             f"Atrium (6 =< height <= 12m)-sch-{letter}": 5.2,
                             f"Atrium (height > 12m)-sch-{letter}": 6.5}.items():
                record = SpaceTypes.record(building_type="Space Function", space_type=name)
                self.assertAlmostEqual(si, float(record["lighting_per_area"]) * 10.7639,
                                       delta=0.05, msg=name)

    def test_rules_and_coverage_lint(self):
        for vintage in ["2020", "2025"]:
            rules = lighting.rules(vintage)
            self.assertAlmostEqual(0.799256505, rules["sensor_schedule_lpd_threshold_w_per_ft2"],
                                   delta=1e-9)
            self.assertEqual(5.0, rules["dwelling_unit_lpd_w_per_m2"])
            self.assertTrue(rules["atrium_led"]["below_12m"]["slope"])
            coverage = rules["article_coverage"]["articles"]
            self.assertGreaterEqual(len(coverage), 7)
            for article in coverage:
                self.assertIn(article["status"],
                              ["implemented", "partial", "not_implemented",
                               "satisfied_by_clone", "host_scope"])
                self.assertTrue(article.get("how") or article.get("gaps"))
        self.assertEqual("2020", lighting.data_vintage("2025"))
        self.assertTrue(re.search(r"zero LPD differences|ZERO value differences",
                                  lighting.rules("2025")["provenance"]["method"],
                                  re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
