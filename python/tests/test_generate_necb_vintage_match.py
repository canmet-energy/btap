"""Direct unit tests for the NECB vintage-match matcher.

The document this script generates is the evidence base for the D-89 adoption
decision, so a matcher defect is a wrong finding rather than an untidy report.
Reviewer findings against the first version, each with a test below:

1. The equipment comparison extracted every number from every row and accepted
   the first nearby value under any of several unit conversions. No equipment
   class, table, row, capacity band, metric or column survived, so its count
   supported nothing. It is replaced by an explicit per-family row-and-column
   mapping, and a family with no faithful mapping is UNMAPPED.
2. The catalog bridge imported Table 4.2.1.6's control-only cross-reference
   (medical supply room -> Storage Room) and reused it for loads and LPD, which
   manufactured a four-cell difference on a row both editions publish.
3. Table C-1 rows were keyed by city alone, which silently drops one of every
   duplicate-city pair (Alma QC/NB, Princeton BC/ON, Waterloo ON/QC, Windsor
   ON/QC) and compares the survivor against whichever row the dict kept.
4. `boiler_modulating` was declared and never consumed.
5. A missing payload became prose instead of a failure.

The fixtures here are SYNTHETIC -- deliberately not the real snapshots -- so
each scenario isolates one join, one conversion or one threshold. The real
document's regeneration plus ``--check`` is the integration proof.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support import REPO_ROOT

SCRIPT = REPO_ROOT / "python" / "scripts" / "generate_necb_vintage_match.py"
_SPEC = importlib.util.spec_from_file_location("generate_necb_vintage_match", SCRIPT)
gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen)


class TestNormalisation(unittest.TestCase):
    """Row labels fold, but the things that distinguish sibling rows do not."""

    def test_comparison_operators_survive_normalisation(self):
        # Table 4.2.1.6 tells "Storage room < 5 m2" from ">= 5 m2" by the
        # operator alone; folding punctuation away collapses the pair.
        self.assertNotEqual(gen.norm_name("Storage room < 5 m²"),
                            gen.norm_name("Storage room ≥ 5 m²"))
        self.assertEqual(gen.norm_name("Office enclosed, < 25 m²"),
                         gen.norm_name("OFFICE  ENCLOSED  <  25 M2"))
        self.assertEqual(gen.norm_name("≥ 5 m²"), gen.norm_name(">= 5 m2"))
        self.assertEqual(gen.norm_name("≤ 5 m²"), gen.norm_name("<= 5 m2"))

    def test_accents_and_case_fold(self):
        self.assertEqual(gen.norm_name("Québec"), gen.norm_name("Quebec"))
        self.assertEqual(gen.norm_name("Trois-Rivières"),
                         gen.norm_name("trois rivieres"))

    def test_qualifier_normalisation_keeps_the_sign(self):
        # 5.2.12.1.-A's heating-mode rows differ only by "at 8.3 C" vs
        # "at -8.3 C"; norm_name folds both, so a qualifier must not use it.
        self.assertEqual(gen.norm_name("at 8.3°C"), gen.norm_name("at -8.3°C"))
        self.assertNotEqual(gen.norm_qualifier("at 8.3°C"),
                            gen.norm_qualifier("at -8.3°C"))
        self.assertNotIn(gen.norm_qualifier("at 8.3"),
                         gen.norm_qualifier("at -8.3°C"))

    def test_subscripts_fold_to_ascii(self):
        self.assertEqual(gen._desubscript("COPₕ"), "COPh")
        self.assertEqual(gen._desubscript("Eₜ"), "Et")

    def test_thin_space_thousands_separator(self):
        self.assertEqual(gen.parse_band("≥ 1 055 and < 2 110"),
                         (1055.0, 2110.0))


class TestProvinceKeying(unittest.TestCase):
    def test_codes_and_names_meet(self):
        self.assertEqual(gen._province_key("QC"), gen._province_key("Québec"))
        self.assertEqual(gen._province_key("QC"), gen._province_key("Quebec"))
        self.assertEqual(gen._province_key("NF"),
                         gen._province_key("Newfoundland and Labrador"))

    def test_distinct_provinces_do_not_collide(self):
        self.assertNotEqual(gen._province_key("QC"), gen._province_key("NB"))
        self.assertNotEqual(gen._province_key("BC"), gen._province_key("ON"))

    def test_unknown_token_survives_rather_than_vanishing(self):
        self.assertEqual(gen._province_key("ZZ"), "zz")


class _C1Fixture:
    """A throwaway snapshot carrying just Table C-1 and its archived payload."""

    def __init__(self, tmp: Path, shipped_rows, edition_rows, headers):
        self.root = tmp
        data = tmp / "necb2020"
        (data / "tables").mkdir(parents=True)
        (data / "tables" / "table_c1.json").write_text(
            json.dumps({"table": shipped_rows}), encoding="utf-8")
        archive = data / "provenance" / gen.ARCHIVE_DIRNAME
        archive.mkdir(parents=True)
        (archive / "C-1.result.json").write_text(
            json.dumps({"get_table:necb:2020:C-1":
                        {"headers": headers, "rows": edition_rows}}),
            encoding="utf-8")


class TestTableC1Join(unittest.TestCase):
    HEADERS = ["Location", "Province", "Degree-Days Below 18°C"]

    def _run(self, shipped_rows, edition_rows):
        with TemporaryDirectory() as tmp:
            _C1Fixture(Path(tmp), shipped_rows, edition_rows, self.HEADERS)
            original = gen.DATA_ROOT
            gen.DATA_ROOT = Path(tmp)
            try:
                res = gen.FileResult("necb2020", "tables/table_c1.json", "x")
                gen.compare_table_c1(res)
                return res
            finally:
                gen.DATA_ROOT = original

    def test_duplicate_city_in_two_provinces_both_match(self):
        """The finding: keying on the city alone drops one Alma."""
        res = self._run(
            [{"city": "Alma", "province": "QC", "degree_days_below_18_c": 5500},
             {"city": "Alma", "province": "NB", "degree_days_below_18_c": 4800}],
            [{"Location": "Alma", "Province": "Québec",
              "Degree-Days Below 18°C": "5500"},
             {"Location": "Alma", "Province": "New Brunswick",
              "Degree-Days Below 18°C": "4800"}])
        self.assertEqual(res.counts["rows matched"], 2)
        self.assertEqual(res.counts["cells differing"], 0)
        self.assertEqual(res.counts["rows unmatched (shipped)"], 0)
        self.assertEqual(res.counts["rows unmatched (edition)"], 0)

    def test_a_city_keyed_join_would_have_compared_the_wrong_row(self):
        """Same two Almas, but with the values swapped between provinces.

        A city-only key matches Alma-to-Alma and sees no difference at all in
        the fixture above; keyed by (city, province) the swap is two differing
        cells, which is what a wrong province actually costs.
        """
        res = self._run(
            [{"city": "Alma", "province": "QC", "degree_days_below_18_c": 4800},
             {"city": "Alma", "province": "NB", "degree_days_below_18_c": 5500}],
            [{"Location": "Alma", "Province": "Quebec",
              "Degree-Days Below 18°C": "5500"},
             {"Location": "Alma", "Province": "New Brunswick",
              "Degree-Days Below 18°C": "4800"}])
        self.assertEqual(res.counts["rows matched"], 2)
        self.assertEqual(res.counts["cells differing"], 2)

    def test_unmatched_rows_are_named_with_their_nearest_candidate(self):
        res = self._run(
            [{"city": "Princeton", "province": "BC", "degree_days_below_18_c": 4000}],
            [{"Location": "Princeton", "Province": "Ontario",
              "Degree-Days Below 18°C": "4100"}])
        self.assertEqual(res.counts["rows matched"], 0)
        self.assertEqual(len(res.unmatched_shipped), 1)
        self.assertEqual(len(res.unmatched_edition), 1)
        self.assertIn("Princeton (Ontario)", res.unmatched_shipped[0])
        self.assertIn("same city, different province", res.unmatched_shipped[0])
        self.assertIn("Princeton (BC)", res.unmatched_edition[0])

    def test_nearest_falls_back_to_a_close_spelling_in_the_same_province(self):
        res = self._run(
            [{"city": "Saint-Jerome", "province": "QC", "degree_days_below_18_c": 1}],
            [{"Location": "Saint-Jerame", "Province": "Quebec",
              "Degree-Days Below 18°C": "1"}])
        self.assertIn("closest spelling, same province", res.unmatched_shipped[0])

    def test_nearest_recognises_a_name_that_contains_the_other(self):
        """The snapshot writes "Arviat / Eskimo Point" where the Code prints one."""
        res = self._run(
            [{"city": "Arviat / Eskimo Point", "province": "NU",
              "degree_days_below_18_c": 1}],
            [{"Location": "Arviat", "Province": "Nunavut",
              "Degree-Days Below 18°C": "1"}])
        self.assertIn("Arviat (Nunavut)", res.unmatched_shipped[0])
        self.assertIn("one name contains the other", res.unmatched_shipped[0])

    def test_nearest_says_so_when_there_is_no_candidate(self):
        res = self._run(
            [{"city": "Qausuittuq", "province": "NU", "degree_days_below_18_c": 1}],
            [{"Location": "Halifax", "Province": "Nova Scotia",
              "Degree-Days Below 18°C": "1"}])
        self.assertIn("no candidate", res.unmatched_shipped[0])

    def test_the_document_says_runtime_reads_coordinates_and_hdd18(self):
        res = self._run(
            [{"city": "Ottawa", "province": "ON", "degree_days_below_18_c": 4500,
              "lat_long": [45.0, -75.0]}],
            [{"Location": "Ottawa", "Province": "Ontario",
              "Degree-Days Below 18°C": "4500"}])
        joined = " ".join(res.notes)
        self.assertIn("lat_long", joined)
        self.assertIn("degree_days_below_18_c", joined)
        self.assertIn("publishes NO coordinates", joined)


class TestScheduleHourAlignment(unittest.TestCase):
    """`12a` is midnight and therefore the FIRST of the 24 hourly values."""

    def test_clock_order_starts_at_midnight_and_noon_is_thirteenth(self):
        self.assertEqual(gen.HOUR_COLUMNS[0], "12a")
        self.assertEqual(gen.HOUR_COLUMNS[12], "12p")
        self.assertEqual(len(gen.HOUR_COLUMNS), 24)
        self.assertEqual(len(set(gen.HOUR_COLUMNS)), 24)

    def test_aligned_schedule_reports_no_difference(self):
        res, counts = self._compare(list(range(24)))
        self.assertEqual(counts["cells differing"], 0)
        self.assertEqual(counts["cells identical"], 24)

    def test_a_one_hour_rotation_is_detected(self):
        """Putting `12a` last instead of first offsets every profile by one."""
        rotated = list(range(1, 24)) + [0]
        _res, counts = self._compare(rotated)
        self.assertEqual(counts["cells differing"], 24)

    def test_the_word_on_compares_as_one_and_off_as_zero(self):
        with TemporaryDirectory() as tmp:
            counts = self._build(Path(tmp), [0.0] * 24,
                                 ["Off"] * 13 + ["On"] * 11,
                                 category="Fans", suffix="FAN")
        # 13 Off cells agree with 0.0; the 11 On cells are the difference.
        self.assertEqual(counts["cells identical"], 13)
        self.assertEqual(counts["cells differing"], 11)

    def _compare(self, values):
        with TemporaryDirectory() as tmp:
            counts = self._build(Path(tmp), values,
                                 [str(h) for h in range(24)])
        return None, counts

    def _build(self, tmp: Path, values, printed, category="Lighting, fraction ON",
               suffix="Lighting"):
        data = tmp / "necb2020"
        (data / "tables").mkdir(parents=True)
        (data / "tables" / "schedules.json").write_text(json.dumps({"table": [
            {"name": f"NECB-A-{suffix}", "type": "Hourly",
             "day_types": "Default|Wkdy", "values": values}]}), encoding="utf-8")
        archive = data / "provenance" / gen.ARCHIVE_DIRNAME
        archive.mkdir(parents=True)
        headers = ["Category", "Day"] + list(gen.HOUR_COLUMNS)
        row = {"Category": category, "Day": "Mon-Fri"}
        row.update(dict(zip(gen.HOUR_COLUMNS, printed)))
        (archive / "A-8.4.3.2.(1)-A.result.json").write_text(
            json.dumps({"get_table:necb:2020:A-8.4.3.2.(1)-A":
                        {"headers": headers, "rows": [row]}}), encoding="utf-8")
        original = gen.DATA_ROOT
        gen.DATA_ROOT = tmp
        try:
            res = gen.FileResult("necb2020", "tables/schedules.json", "x")
            gen.compare_schedules(res, ["A-8.4.3.2.(1)-A"])
            return res.counts
        finally:
            gen.DATA_ROOT = original


class TestCatalogBridgeIsForControlsOnly(unittest.TestCase):
    """A control cross-reference must not steer loads or LPD."""

    ENTRIES = {
        "space_types": {
            "Health care facility medical supply room": {
                "table_row": "Storage room | ≥ 5 m²",
                "mapping": "cross_reference_storage_room",
            },
            "Dining area": {
                "table_row": "Dining area | Dining area other",
                "mapping": "direct",
            },
        }
    }

    def _fixture(self, tmp: Path):
        data = tmp / "necb2020" / "tables"
        data.mkdir(parents=True)
        (data / "daylighting_controls_4_2_1_6.json").write_text(
            json.dumps(self.ENTRIES), encoding="utf-8")
        return tmp

    def _with_root(self, fn):
        with TemporaryDirectory() as tmp:
            self._fixture(Path(tmp))
            original = gen.DATA_ROOT
            gen.DATA_ROOT = Path(tmp)
            try:
                return fn()
            finally:
                gen.DATA_ROOT = original

    def test_control_bridge_keeps_the_cross_reference(self):
        bridge = self._with_root(lambda: gen.catalog_bridge("necb2020"))
        self.assertEqual(
            bridge["health care facility medical supply room"],
            gen.norm_name("Storage room ≥ 5 m²"))

    def test_loads_bridge_drops_it_and_aims_at_the_own_row(self):
        bridge = self._with_root(lambda: gen.loads_bridge("necb2020"))
        self.assertEqual(bridge["health care facility medical supply room"],
                         "healthcare facility medical supply room")
        # A direct mapping is untouched by the exclusion.
        self.assertEqual(bridge["dining area"],
                         gen.norm_name("Dining area Dining area other"))

    def test_cross_references_are_read_from_the_files_own_marker(self):
        found = self._with_root(lambda: gen.control_cross_references("necb2020"))
        self.assertEqual(sorted(found),
                         ["health care facility medical supply room"])
        self.assertEqual(found["health care facility medical supply room"],
                         "cross_reference_storage_room")

    def test_the_alias_list_is_declared_not_fuzzy(self):
        # The one case: the catalog writes "Health care", the Code "Healthcare".
        self.assertEqual(
            gen.SPACE_TYPE_ALIASES["health care facility medical supply room"],
            "healthcare facility medical supply room")


class TestSpaceTypeJoinAndConversions(unittest.TestCase):
    """The medical-supply row against the row both editions actually publish."""

    SHIPPED = [{
        "building_type": "Space Function",
        "space_type": "Health care facility medical supply room",
        "occupancy_per_area": 4.646840148698885,
        "electric_equipment_per_area": 0.0929368029739777,
        "necb_schedule_type": "H",
        "target_illuminance_setpoint": 400,
        "lighting_per_area": 0.62245097,
        "ventilation_per_area": 0.12,
    }]

    LOADS_ROWS = [
        {"Space Type": "medical supply room", "Space Category": "Healthcare facility",
         "Occupant Density, m²/occupant": "20", "Peak Receptacle Load, W/m²": "1",
         "Operating Schedule from A-8.4.3.2.(1)": "H", "Illuminance Levels, lx": "400"},
        {"Space Type": "≥ 5 m²", "Space Category": "Storage room",
         "Occupant Density, m²/occupant": "100", "Peak Receptacle Load, W/m²": "1",
         "Operating Schedule from A-8.4.3.2.(1)": "*", "Illuminance Levels, lx": "100"},
    ]
    LPD_ROWS = [
        {"Space Type": "medical supply room", "Space Category": "Healthcare facility",
         "Lighting Power Density, W/m²": "6.7"},
        {"Space Type": "≥ 5 m²", "Space Category": "Storage room",
         "Lighting Power Density, W/m²": "4.1"},
    ]

    def _run(self):
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "necb2020"
            (data / "tables").mkdir(parents=True)
            (data / "tables" / "space_types.json").write_text(
                json.dumps({"table": self.SHIPPED}), encoding="utf-8")
            (data / "tables" / "led_lighting.json").write_text(
                json.dumps({"table": self.SHIPPED}), encoding="utf-8")
            (data / "tables" / "daylighting_controls_4_2_1_6.json").write_text(
                json.dumps({"space_types": {
                    "Health care facility medical supply room": {
                        "table_row": "Storage room | ≥ 5 m²",
                        "mapping": "cross_reference_storage_room"}}}),
                encoding="utf-8")
            archive = data / "provenance" / gen.ARCHIVE_DIRNAME
            archive.mkdir(parents=True)
            (archive / "A-8.4.3.2.(2)-B.result.json").write_text(
                json.dumps({"get_table:necb:2020:A-8.4.3.2.(2)-B": {
                    "headers": ["Space Type", "Space Category",
                                "Occupant Density, m²/occupant",
                                "Peak Receptacle Load, W/m²",
                                "Operating Schedule from A-8.4.3.2.(1)",
                                "Illuminance Levels, lx"],
                    "rows": self.LOADS_ROWS}}), encoding="utf-8")
            (archive / "4.2.1.6.result.json").write_text(
                json.dumps({"get_table:necb:2020:4.2.1.6": {
                    "headers": ["Space Type", "Space Category",
                                "Lighting Power Density, W/m²"],
                    "rows": self.LPD_ROWS}}), encoding="utf-8")
            original = gen.DATA_ROOT
            gen.DATA_ROOT = Path(tmp)
            try:
                loads = gen.FileResult("necb2020", "tables/space_types.json", "x")
                gen.compare_space_types(loads, ["A-8.4.3.2.(2)-B", "4.2.1.6"])
                led = gen.FileResult("necb2020", "tables/led_lighting.json", "x")
                gen.compare_led_lighting(led, ["4.2.1.6"])
                return loads, led
            finally:
                gen.DATA_ROOT = original

    def test_medical_supply_row_has_zero_differing_cells(self):
        loads, led = self._run()
        self.assertEqual(loads.counts["records matched"], 1)
        self.assertEqual(loads.counts["cells differing"], 0,
                         msg=f"differences: {loads.differences}")
        self.assertEqual(loads.counts["cells identical"], 5)
        self.assertEqual(led.counts["LPD values differing"], 0)
        self.assertEqual(led.counts["LPD values equal to the edition's"], 1)

    def test_w_per_m2_converts_to_w_per_ft2(self):
        # 6.7 W/m2 x 0.09290304 = 0.622450368 W/ft2.
        self.assertAlmostEqual(6.7 * gen.W_PER_M2_TO_W_PER_FT2, 0.622450368,
                               places=9)

    def test_occupant_density_inverts_to_occupants_per_1000_ft2(self):
        # 20 m2/occupant -> 50 occ/1000 m2 -> 4.645152 occ/1000 ft2.
        converted = (1000.0 / 20.0) * gen.W_PER_M2_TO_W_PER_FT2
        self.assertAlmostEqual(converted, 4.645152, places=6)
        self.assertTrue(gen.numbers_equal(4.646840148698885, converted, 2e-3))

    def test_the_cross_reference_is_reported_as_controls_only(self):
        loads, _led = self._run()
        self.assertTrue(any("cross_reference_storage_room" in n
                            for n in loads.notes))

    def test_columns_with_no_edition_source_are_listed(self):
        loads, _led = self._run()
        self.assertIn("ventilation_per_area", loads.no_source_columns)


class TestCapacityBandsAndMetricParsing(unittest.TestCase):
    def test_band_forms(self):
        self.assertEqual(gen.parse_band("< 19"), (None, 19.0))
        self.assertEqual(gen.parse_band("≥ 19 and < 40"), (19.0, 40.0))
        self.assertEqual(gen.parse_band("≥ 223"), (223.0, None))
        self.assertEqual(gen.parse_band("≤ 66"), (None, 66.0))
        self.assertEqual(gen.parse_band("> 66 and ≤ 117"), (66.0, 117.0))
        self.assertEqual(gen.parse_band("All capacities"), (None, None))
        self.assertIsNone(gen.parse_band(""))

    def test_btu_per_h_bin_lines_up_with_the_printed_kw_band(self):
        row = {"minimum_capacity": 65000.0, "maximum_capacity": 136480.0}
        lo, hi, label = gen._capacity_bounds(row, {"capacity_unit": "btu_per_h"})
        self.assertEqual(label, "Btu/h → kW")
        self.assertAlmostEqual(lo, 19.0496, places=3)
        self.assertAlmostEqual(hi, 39.9984, places=3)
        self.assertTrue(gen._bands_align((lo, hi), (19.0, 40.0)))
        self.assertFalse(gen._bands_align((lo, hi), (40.0, 70.0)))

    def test_tons_bin_lines_up_with_the_printed_kw_band(self):
        row = {"minimum_capacity": 150.13, "maximum_capacity": 299.98}
        lo, hi, label = gen._capacity_bounds(row, {"capacity_unit": "ton"})
        self.assertEqual(label, "tons → kW")
        self.assertAlmostEqual(lo, 528.0, places=1)
        self.assertAlmostEqual(hi, 1055.0, places=1)
        self.assertTrue(gen._bands_align((lo, hi), (528.0, 1055.0)))

    def test_a_sentinel_becomes_an_open_bound_not_a_number(self):
        row = {"minimum_capacity": 599.97, "maximum_capacity": 9999.0}
        lo, hi, _ = gen._capacity_bounds(row, {"capacity_unit": "ton"})
        self.assertIsNone(hi)
        self.assertTrue(gen._bands_align((lo, hi), (2110.0, None)))
        row = {"minimum_capacity": 2500000.0, "maximum_capacity": "9.999999999E9"}
        _lo, hi, _ = gen._capacity_bounds(row, {"capacity_unit": "btu_per_h"})
        self.assertIsNone(hi)

    def test_metric_tokens_are_read_longest_first(self):
        metrics = gen.parse_metrics("EER = 12.1 IEER = 12.3")
        self.assertEqual([(m["token"], m["value"]) for m in metrics],
                         [("EER", 12.1), ("IEER", 12.3)])
        metrics = gen.parse_metrics("SEER = 15 / HSPF V = 7.4")
        self.assertEqual([(m["token"], m["value"]) for m in metrics],
                         [("SEER", 15.0), ("HSPF V", 7.4)])

    def test_percent_and_water_steam_qualifiers(self):
        metrics = gen.parse_metrics("AFUE = 90% (water)(3) AFUE = 82% (steam)(3)")
        self.assertEqual(len(metrics), 2)
        self.assertTrue(all(m["percent"] for m in metrics))
        water = gen._pick_metric("AFUE = 90% (water)(3) AFUE = 82% (steam)(3)",
                                 {"metric": "AFUE", "metric_qualifier": "(water)"})
        steam = gen._pick_metric("AFUE = 90% (water)(3) AFUE = 82% (steam)(3)",
                                 {"metric": "AFUE", "metric_qualifier": "(steam)"})
        self.assertEqual(water["value"], 90.0)
        self.assertEqual(steam["value"], 82.0)
        self.assertEqual(
            gen.METRIC_TRANSFORMS["percent_to_fraction"][0](90.0, water), 0.90)

    def test_subscripted_thermal_efficiency_with_a_ge_operator(self):
        metrics = gen.parse_metrics("Eₜ ≥ 90% (water) Eₜ ≥ 81% (steam)")
        self.assertEqual([m["token"] for m in metrics], ["Et", "Et"])
        self.assertEqual(metrics[0]["value"], 90.0)

    def test_the_two_coph_rating_points_are_told_apart_by_sign(self):
        cell = ("COPₕ = 3.30 evaluated at 8.3°C db / 6.1°C wb "
                "COPₕ = 2.25 evaluated at -8.3°C db / -9.4°C wb")
        warm = gen._pick_metric(cell, {"metric": "COPh",
                                       "metric_qualifier": "evaluated at 8.3"})
        self.assertEqual(warm["value"], 3.30)

    def test_an_absent_qualifier_is_not_silently_matched(self):
        self.assertIsNone(gen._pick_metric("AFUE = 90% (steam)",
                                           {"metric": "AFUE",
                                            "metric_qualifier": "(water)"}))

    def test_the_ptac_sliding_minimum_slope_converts_per_kw_to_per_kbtu_per_h(self):
        metric = gen._pick_metric("EER = 14.1 - (1.0435 × Capkw)",
                                  {"metric": "EER"})
        self.assertEqual(metric["value"], 14.1)
        self.assertAlmostEqual(metric["slope"], 1.0435)
        converted = gen.METRIC_TRANSFORMS[
            "slope_per_kw_to_per_kbtu_per_h"][0](metric["value"], metric)
        self.assertTrue(gen.numbers_equal(converted, 0.3058, 2e-3))

    def test_cop_converts_to_kw_per_ton(self):
        converted = gen.METRIC_TRANSFORMS["cop_to_kw_per_ton"][0](4.513, {})
        self.assertTrue(gen.numbers_equal(converted, 0.77927, 2e-3))


class TestEquipmentFamilyMapping(unittest.TestCase):
    """Boilers and chillers end to end, against one identified cell each."""

    BOILER_TABLE = {
        "headers": ["Equipment Category", "Type of Equipment",
                    "Cooling or Heating Capacity, kW", "Minimum Performance"],
        "rows": [
            {"Equipment Category": "Gas-fired(4)", "Type of Equipment": "Gas-fired(4)",
             "Cooling or Heating Capacity, kW": "< 88",
             "Minimum Performance": "AFUE = 90% (water)(3) AFUE = 82% (steam)(3)"},
            {"Equipment Category": "Gas-fired(4)", "Type of Equipment": "Gas-fired(4)",
             "Cooling or Heating Capacity, kW": "≥ 88 and < 733",
             "Minimum Performance":
                 "Eₜ ≥ 90% (water) Eₜ ≥ 81% (steam)"},
            {"Equipment Category": "Electric", "Type of Equipment": "Electric",
             "Cooling or Heating Capacity, kW": "< 88",
             "Minimum Performance": "Must be equipped with automatic control"},
        ],
    }
    CHILLER_TABLE = {
        "headers": ["Type of Equipment", "Cooling or Heating Capacity, kW",
                    "Minimum Performance Path A", "Minimum Performance Path B"],
        "rows": [
            {"Type of Equipment":
                 "Water-cooled, rotary screw, scroll, or reciprocating compressor",
             "Cooling or Heating Capacity, kW": "< 264",
             "Minimum Performance Path A": "COPc = 4.694 IPLV = 5.867",
             "Minimum Performance Path B": "COPc = 4.513 IPLV = 7.041"},
            {"Type of Equipment": "Water-cooled, centrifugal compressor",
             "Cooling or Heating Capacity, kW": "< 528",
             "Minimum Performance Path A": "COPc = 5.771 IPLV = 6.401",
             "Minimum Performance Path B": "COPc = 5.065 IPLV = 8.001"},
        ],
    }

    def _run(self, shipped):
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "necb2020"
            data.mkdir(parents=True)
            (data / "efficiencies.json").write_text(json.dumps(shipped),
                                                    encoding="utf-8")
            original = gen.DATA_ROOT
            gen.DATA_ROOT = Path(tmp)
            try:
                res = gen.FileResult("necb2020", "efficiencies.json", "x")
                families = gen.compare_equipment_families(
                    res, {"5.2.12.1.-N": self.BOILER_TABLE,
                          "5.2.12.1.-K": self.CHILLER_TABLE})
                return res, families
            finally:
                gen.DATA_ROOT = original

    def test_a_gas_boiler_row_matches_its_own_band_and_metric(self):
        _res, families = self._run({"boilers": [
            {"fuel_type": "Gas", "fluid_type": "Hot Water",
             "minimum_capacity": "-", "maximum_capacity": 299999.0,
             "minimum_annual_fuel_utilization_efficiency": 0.9},
            {"fuel_type": "Gas", "fluid_type": "Hot Water",
             "minimum_capacity": 300000.0, "maximum_capacity": 2499999.0,
             "minimum_thermal_efficiency": 0.9},
        ]})
        boilers = families["boilers"]
        self.assertEqual(boilers["matched"], 2)
        self.assertEqual(boilers["unmatched"], 0)
        self.assertEqual(boilers["identical"], 2)
        self.assertEqual(boilers["differing"], 0)

    def test_the_steam_value_is_not_accepted_for_the_water_column(self):
        """0.82 is the STEAM AFUE: a scan would find it, the mapping must not."""
        res, families = self._run({"boilers": [
            {"fuel_type": "Gas", "fluid_type": "Hot Water",
             "minimum_capacity": "-", "maximum_capacity": 299999.0,
             "minimum_annual_fuel_utilization_efficiency": 0.82},
        ]})
        self.assertEqual(families["boilers"]["differing"], 1)
        self.assertEqual(families["boilers"]["identical"], 0)
        self.assertIn("AFUE = 90", res.differences[0][2])

    def test_a_wrong_capacity_band_is_caught_not_smoothed_over(self):
        """The <88 kW AFUE value pinned on the 88-733 kW row must differ."""
        _res, families = self._run({"boilers": [
            {"fuel_type": "Gas", "fluid_type": "Hot Water",
             "minimum_capacity": 300000.0, "maximum_capacity": 2499999.0,
             "minimum_annual_fuel_utilization_efficiency": 0.9},
        ]})
        # The 88-733 kW row prints no AFUE at all, only thermal efficiency.
        self.assertEqual(families["boilers"]["no_edition_value"], 1)
        self.assertEqual(families["boilers"]["identical"], 0)

    def test_an_electric_boiler_has_no_published_minimum(self):
        _res, families = self._run({"boilers": [
            {"fuel_type": "Electric", "fluid_type": "Hot Water",
             "minimum_capacity": 0.0, "maximum_capacity": 299999.0,
             "minimum_thermal_efficiency": 1.0},
        ]})
        self.assertEqual(families["boilers"]["matched"], 1)
        self.assertEqual(families["boilers"]["no_edition_value"], 1)
        self.assertEqual(families["boilers"]["differing"], 0)

    def test_chiller_kw_per_ton_against_path_b_by_compressor_type(self):
        _res, families = self._run({"chillers": [
            {"cooling_type": "WaterCooled", "compressor_type": "Scroll",
             "minimum_capacity": 0.0, "maximum_capacity": 75.07,
             "minimum_full_load_efficiency": 0.77927},
            {"cooling_type": "WaterCooled", "compressor_type": "Centrifugal",
             "minimum_capacity": 0.0, "maximum_capacity": 150.13,
             "minimum_full_load_efficiency": 0.69434},
        ]})
        self.assertEqual(families["chillers"]["matched"], 2)
        self.assertEqual(families["chillers"]["identical"], 2)
        self.assertEqual(families["chillers"]["differing"], 0)

    def test_the_centrifugal_value_is_rejected_for_a_scroll_row(self):
        """A value-only scan accepts 0.69434 anywhere in Table 5.2.12.1.-K."""
        _res, families = self._run({"chillers": [
            {"cooling_type": "WaterCooled", "compressor_type": "Scroll",
             "minimum_capacity": 0.0, "maximum_capacity": 75.07,
             "minimum_full_load_efficiency": 0.69434},
        ]})
        self.assertEqual(families["chillers"]["differing"], 1)

    def test_path_a_is_not_accepted_where_path_b_is_mapped(self):
        # Path A's COPc 4.694 -> 0.74922 kW/ton: a real cell of the same row,
        # in the column the mapping does not name.
        _res, families = self._run({"chillers": [
            {"cooling_type": "WaterCooled", "compressor_type": "Scroll",
             "minimum_capacity": 0.0, "maximum_capacity": 75.07,
             "minimum_full_load_efficiency": 0.74922},
        ]})
        self.assertEqual(families["chillers"]["differing"], 1)

    def test_heat_rejection_is_reported_unmapped_never_corroborated(self):
        _res, families = self._run({"heat_rejection": [
            {"equipment_type": "Open Cooling Tower", "fan_type": "Centrifugal",
             "minimum_performance": 20.0, "notes": "From 90.1-2004 Table 6.8.1G"},
        ]})
        entry = families["heat_rejection"]
        self.assertIsNotNone(entry["unmapped_reason"])
        self.assertEqual(entry["identical"], 0)
        self.assertEqual(entry["matched"], 0)
        self.assertIn("ASHRAE 90.1", entry["unmapped_reason"])

    def test_an_undeclared_metric_key_is_listed_rather_than_ignored(self):
        _res, families = self._run({"boilers": [
            {"fuel_type": "Gas", "fluid_type": "Hot Water",
             "minimum_capacity": "-", "maximum_capacity": 299999.0,
             "minimum_annual_fuel_utilization_efficiency": 0.9,
             "minimum_invented_efficiency": 0.5},
        ]})
        self.assertIn("minimum_invented_efficiency",
                      families["boilers"]["undeclared"])

    def test_every_block_names_a_table_a_row_a_band_and_a_column(self):
        for edition_id, blocks in gen.EQUIPMENT_BLOCKS.items():
            for block in blocks:
                where = f"{edition_id}/{block['block']}"
                self.assertTrue(block["table"], where)
                self.assertTrue(block["row_name"], where)
                self.assertTrue(block["row_column"], where)
                self.assertIn(block["capacity_unit"], gen.CAPACITY_UNITS, where)
                self.assertTrue(block["columns"], where)
                for key, spec in block["columns"].items():
                    self.assertIn(spec["metric"], gen.METRIC_TOKENS,
                                  f"{where}/{key}")
                    self.assertIn(spec["transform"], gen.METRIC_TRANSFORMS,
                                  f"{where}/{key}")
                    self.assertTrue(spec["column"], f"{where}/{key}")


class TestModulatingBoilerAndFurnace(unittest.TestCase):
    """`boiler_modulating` was declared and never consumed. It is now."""

    TEN_POINT = {
        "headers": ["Qpartload, Qrated and Qdesign (Part-Load Ratio)", "FHeatPLC"],
        "rows": [{"Qpartload, Qrated and Qdesign (Part-Load Ratio)": f"{p:g}",
                  "FHeatPLC": f"{f:g}"}
                 for p, f in [(0.1, 0.118), (0.2, 0.209), (0.3, 0.308),
                              (0.4, 0.407), (0.5, 0.506), (0.6, 0.605),
                              (0.7, 0.704), (0.8, 0.802), (0.9, 0.901),
                              (1, 1)]],
    }
    COEFFICIENTS = {
        "headers": ["Type of Boiler", "a", "b", "c"],
        "rows": [
            {"Type of Boiler": "Non-condensing", "a": "0.082597",
             "b": "0.996764", "c": "-0.079361"},
        ],
    }
    SHIPPED_CURVE = {
        "name": "BOILER-EFFFPLR", "form": "Cubic",
        "coeff_1": 0.3831, "coeff_2": 2.0567, "coeff_3": -2.6469,
        "coeff_4": 1.2148, "coeff_5": None, "coeff_6": None, "coeff_7": None,
        "coeff_8": None, "coeff_9": None, "coeff_10": None,
    }

    def _records(self):
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "necb2020"
            data.mkdir(parents=True)
            (data / "efficiencies.json").write_text(json.dumps({
                "curves": [self.SHIPPED_CURVE],
                "boilers": [{"fuel_type": "Gas", "fluid_type": "Hot Water",
                             "efffplr": "BOILER-EFFFPLR"}],
            }), encoding="utf-8")
            archive = data / "provenance" / gen.ARCHIVE_DIRNAME
            archive.mkdir(parents=True)
            (archive / "8.4.5.2.-A.result.json").write_text(
                json.dumps({"get_table:necb:2020:8.4.5.2.-A": self.COEFFICIENTS}),
                encoding="utf-8")
            (archive / "8.4.5.2.-B.result.json").write_text(
                json.dumps({"get_table:necb:2020:8.4.5.2.-B": self.TEN_POINT}),
                encoding="utf-8")
            original = gen.DATA_ROOT
            gen.DATA_ROOT = Path(tmp)
            try:
                curves = gen._curve_index("necb2020")
                return gen.fheatplc_records("necb2020", "boiler_plc", curves)
            finally:
                gen.DATA_ROOT = original

    def test_the_ten_point_table_is_consumed_as_a_modulating_requirement(self):
        records = self._records()
        classes = {r["equipment_class"]: r for r in records}
        self.assertIn("Modulating", classes,
                      "Table 8.4.5.2.-B was declared and never consumed")
        modulating = classes["Modulating"]
        self.assertEqual(modulating["requirement_form"], "tabulated")
        self.assertEqual(modulating["table"], "8.4.5.2.-B")

    def test_the_modulating_deviation_is_the_33_percent_one(self):
        modulating = next(r for r in self._records()
                          if r["equipment_class"] == "Modulating")
        # PLF = PLR/FHeatPLC; the shipped non-condensing cubic gives 0.5635 at
        # PLR 0.1 where the modulating requirement is 0.1/0.118 = 0.8475.
        self.assertAlmostEqual(modulating["assigned_deviation"], 0.3351, places=3)

    def test_the_curve_compared_is_the_one_every_row_is_actually_given(self):
        for record in self._records():
            self.assertEqual(record["assigned_name"], "BOILER-EFFFPLR")

    def test_no_shipped_curve_is_named_for_the_modulating_class(self):
        modulating = next(r for r in self._records()
                          if r["equipment_class"] == "Modulating")
        self.assertIsNone(modulating["nominal_name"])
        self.assertIn("no curve named for this class", modulating["detail"])

    def test_the_non_condensing_class_is_the_small_2_67_percent_one(self):
        record = next(r for r in self._records()
                      if r["equipment_class"] == "Non-condensing")
        self.assertAlmostEqual(record["assigned_deviation"], 0.0267, places=3)

    def test_plf_is_plr_over_fheatplc(self):
        self.assertAlmostEqual(
            gen._plf_from_ratio([0.082597, 0.996764, -0.079361], 1.0),
            1.0 / (0.082597 + 0.996764 - 0.079361), places=12)

    def test_a_bivariate_requirement_is_evaluated_over_a_declared_box(self):
        requirement = {"form": "bivariate", "points": {},
                       "coefficients": [-0.09438953, 0.90322417, 0.01546033,
                                        0.00159778, -0.00000645, 0.00111432]}
        points = gen._requirement_points(requirement)
        self.assertEqual(len(points),
                         len(gen.T_W_RETURN_F) * len(gen.PLR_POINTS))
        self.assertEqual(gen.T_W_RETURN_F[0], 80)
        self.assertEqual(gen.T_W_RETURN_F[-1], 180)
        self.assertTrue(any("T_w" in label for label, _p, _v in points))


class TestCompletenessGate(unittest.TestCase):
    def test_the_matrix_declares_payloads_for_both_editions(self):
        declared = gen.declared_payloads()
        self.assertTrue(declared)
        editions = {edition for edition, _k, _n in declared}
        self.assertEqual(editions, {"necb2020", "necb2025"})
        self.assertIn(("necb2020", "get_table", "8.4.5.2.-B"), declared)
        self.assertIn(("necb2025", "get_table", "8.4.6.2"), declared)

    def test_every_declared_payload_is_archived(self):
        missing = gen.missing_payloads()
        self.assertEqual(missing, [],
                         msg="a missing payload must be a failure, not prose")

    def test_a_missing_payload_is_reported(self):
        with TemporaryDirectory() as tmp:
            for edition in ("necb2020", "necb2025"):
                (Path(tmp) / edition).mkdir(parents=True)
                (Path(tmp) / edition / "manifest.json").write_text(
                    json.dumps({"id": edition,
                                "edition": edition.removeprefix("necb"),
                                "provenance": {}}), encoding="utf-8")
            original = gen.DATA_ROOT
            gen.DATA_ROOT = Path(tmp)
            try:
                missing = gen.missing_payloads()
            finally:
                gen.DATA_ROOT = original
        self.assertEqual(len(missing), len(gen.declared_payloads()))

    def test_refresh_is_rejected_without_fetch(self):
        with self.assertRaises(SystemExit):
            gen.main(["--refresh"])


class TestRendering(unittest.TestCase):
    def test_no_blank_line_at_end_of_file(self):
        """`git diff --check` rejects a new blank line at EOF."""
        text = gen.render([], {"prose": ["p"], "rows": [], "conclusion": "c"})
        self.assertTrue(text.endswith("\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_the_generated_document_has_no_trailing_blank_line(self):
        document = (REPO_ROOT / "docs" / "NECB_VINTAGE_MATCH.md").read_text(
            encoding="utf-8")
        self.assertTrue(document.endswith("\n"))
        self.assertFalse(document.endswith("\n\n"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
