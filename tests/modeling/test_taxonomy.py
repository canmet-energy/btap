"""The HVAC catalogue taxonomy (docs/plans/HVAC_TAXONOMY_PLAN.md).

Every row lands in exactly one system type, every facet stays inside its
closed vocabulary, minted IDs are model-safe and unique, and display names are
plain ASCII. A facet READ from a row field must move when that field moves —
otherwise a system would be named for equipment it does not build.
"""

from __future__ import annotations

import copy
import re
import unittest
from collections import defaultdict

from btap.modeling.hvac import catalog, taxonomy

ROWS = catalog.rows()
ID_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def row(name):
    return next(r for r in ROWS if r["legacy_name"] == name)


class TestEveryRowIsPlaced(unittest.TestCase):

    def test_every_row_lands_in_exactly_one_type(self):
        placed = [r["legacy_name"] for types in taxonomy.tree().values()
                  for rows in types.values() for r in rows]
        self.assertEqual(sorted(r["legacy_name"] for r in ROWS), sorted(placed))

    def test_facets_stay_in_their_vocabularies(self):
        for r in ROWS:
            with self.subTest(row=r["legacy_name"]):
                facets = taxonomy.facets(r)      # raises on a value outside the vocabulary
                self.assertEqual(set(taxonomy.FACETS), set(facets))

    #: Values only a CONFIGURED build produces, with the override that does.
    #: NECB System 4 is the System 3 row built with `sys_abbr: sys_4` (D-113),
    #: so no row carries lineage 4 and the reference's merged config does.
    OVERRIDE_ONLY = {("necb_lineage", "4"): ("psz-gas-hwbb-gasboiler", {"sys_abbr": "sys_4"})}

    def test_every_vocabulary_value_is_used(self):
        """A value no row can produce is a dead filter an engineer would tick
        and get nothing from — unless a configured build produces it, which
        is stated (and proved) above rather than skipped."""
        used = defaultdict(set)
        for r in ROWS:
            for key, value in taxonomy.facets(r).items():
                used[key].update(value if key in taxonomy.MULTI else [value])
        for key, vocab in taxonomy.FACETS.items():
            with self.subTest(facet=key):
                self.assertEqual([], [v for v in vocab if v not in used[key]
                                      and (key, v) not in self.OVERRIDE_ONLY])

    def test_an_override_only_value_is_really_override_only(self):
        from btap.modeling.hvac import catalog
        for (key, value), (row_id, override) in self.OVERRIDE_ONLY.items():
            with self.subTest(facet=key, value=value):
                self.assertFalse([r["id"] for r in ROWS if taxonomy.facets(r)[key] == value])
                merged = {**catalog.resolve(row_id), **override}
                self.assertEqual(value, taxonomy.facets(merged)[key])


class TestNames(unittest.TestCase):

    def test_minted_ids_are_model_safe_and_unique(self):
        ids = [taxonomy.mint_id(r) for r in ROWS]
        for system_id in ids:
            with self.subTest(id=system_id):
                self.assertRegex(system_id, ID_RE)
                self.assertLessEqual(len(system_id), 40)
        self.assertEqual(len(ids), len({i.lower() for i in ids}))

    def test_display_names_are_ascii_and_unique(self):
        names = [taxonomy.display(r) for r in ROWS]
        for name in names:
            with self.subTest(display=name):
                self.assertTrue(name.isascii())
                self.assertNotIn("|", name)
        self.assertEqual(len(names), len({n.lower() for n in names}))

    def test_necb_system_4_is_the_system_3_row_not_a_twin(self):
        """D-113: the eight '-necbs4' rows built exactly their System 3 row's
        equipment, so they were retired. Their old names resolve to it, and
        the System 4 tag is a config override that changes lineage only."""
        from btap.modeling.hvac import catalog
        three = row("PSZ RTU Gas and DX Coils and Hot Water Baseboard")
        for old in ("PSZ RTU with exhaust Gas and DX Coils and Hot Water Baseboard",
                    "psz-gas-hwbb-gasboiler-necbs4"):
            self.assertEqual(three["id"], catalog.resolve(old)["id"])
        four = {**three, "sys_abbr": "sys_4"}
        f3, f4 = taxonomy.facets(three), taxonomy.facets(four)
        self.assertEqual(("3", "4"), (f3["necb_lineage"], f4["necb_lineage"]))
        self.assertEqual({k: v for k, v in f3.items() if k != "necb_lineage"},
                         {k: v for k, v in f4.items() if k != "necb_lineage"})
        self.assertEqual(three["id"], taxonomy.mint_id(four),
                         "lineage is a facet, never part of an id")
        self.assertFalse([r["id"] for r in ROWS if "necbs4" in r["id"]])


class TestFacetsFollowTheirFields(unittest.TestCase):
    """Field-sensitivity: change the field, the facet (and the ID) must change."""

    CASES = [
        ("PSZ RTU Gas and DX Coils and Hot Water Baseboard", "heating_coil_type", "Electric", "ahu_heating"),
        ("PSZ RTU Gas and DX Coils and Hot Water Baseboard", "baseboard_type", "Electric", "zone_heating"),
        ("PSZ-AC with gas coil", "per_zone", False, "scope"),
        ("MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard", "chiller_type", "Centrifugal", "chiller_kind"),
        ("MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard", "chw_source", "air_cooled", "chw_plant"),
        ("Baseboard gas boiler", "hw_source", "district", "hw_plant"),
        ("Baseboard gas boiler", "boiler_fuel", "Electricity", "hw_plant"),
        ("FPFC MAU DX Coils with Scroll Chiller", "mau_cooling_type", "Hydronic", "ahu_cooling"),
        ("FPFC MAU DX Coils with Scroll Chiller", "fan_coil_type", "TPFC", "terminal"),
        ("VAV chiller with gas boiler reheat and rotary ERV", "erv_latent_effectiveness", 0.0, "vent_heat_recovery"),
        ("hs12_ashp_baseboard", "air_eqpt", "ccashp", "ahu_heating"),
        ("VRF", "zone_ventilation", False, "terminal_outdoor_air"),
        ("PSZ RTU ASHP with Gas and ASHP with Gas Supp. Heat Coils and Hot Water Baseboard", "supp_htg_fuel", "Electric", "ahu_backup"),
        ("PSZ RTU ASHP with Gas and ASHP Coils and Hot Water Baseboard with Gas Reheat", "supp_htg_fuel", "Electric", "reheat"),
        ("Shared hot water air handler with water reheat", "reheat", None, "system_type"),
        ("Water source heat pumps", "heat_rejection", "ground", "hw_plant"),
        ("PTAC with baseboard electric", "unit_type", "window_ac", "system_type"),
        ("MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard", "chw_source", "air_cooled", "heat_rejection"),
        ("Recirculating CRAH chilled water with humidity control", "ventilation", True, "outdoor_air"),
        ("FPFC MAU DX Coils with Scroll Chiller", "heating", "none", "changeover"),
    ]

    def test_each_field_moves_its_facet(self):
        for name, field, value, facet in self.CASES:
            with self.subTest(row=name, field=field):
                before = taxonomy.facets(row(name))
                mutated = copy.deepcopy(row(name))
                if value is None:
                    mutated.pop(field)
                else:
                    mutated[field] = value
                if field == "boiler_fuel" or field == "hw_source":
                    mutated["needs_boiler"] = True
                after = taxonomy.facets(mutated)
                self.assertNotEqual(before[facet], after[facet])
                self.assertNotEqual(taxonomy.mint_id(row(name)), taxonomy.mint_id(mutated))


class TestTheConfiguredBuildIsDescribed(unittest.TestCase):
    """Astra #1: an override changes what is BUILT, so the facets of the merged
    config must follow it — NECB System 2 electric is the gas fan-coil row
    with `boiler_fuel: Electricity`."""

    def test_an_override_reaches_the_facets(self):
        base = row("FPFC MAU Chilled Water Coils with Scroll Chiller")
        electric = {**base, "boiler_fuel": "Electricity"}
        self.assertEqual(["gas_boiler"], taxonomy.facets(base)["hw_plant"])
        self.assertEqual(["electric_boiler"], taxonomy.facets(electric)["hw_plant"])
        self.assertIn("electric boiler", taxonomy.display(electric))


class TestFableFindings(unittest.TestCase):
    """Builder facts an independent read (Fable, 2026-11-25) found the first
    version got wrong."""

    def test_a_water_cooled_chiller_brings_its_cooling_tower(self):
        f = taxonomy.facets(row("MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard"))
        self.assertEqual(("water_cooled_chiller", "cooling_tower"), (f["chw_plant"][0], f["heat_rejection"]))

    def test_a_shared_rooftop_unit_says_so(self):
        name = taxonomy.display(row("PSZ RTU Gas and DX Coils and Hot Water Baseboard"))
        self.assertIn("one unit serving several zones", name)
        self.assertIn("one unit per zone", taxonomy.display(row("PSZ-AC with gas coil")))

    def test_the_fan_coil_mau_defaults_to_dx(self):
        bare = {k: v for k, v in row("FPFC MAU DX Coils with Scroll Chiller").items()
                if k != "mau_cooling_type"}
        self.assertEqual("dx", taxonomy.facets(bare)["ahu_cooling"])

    def test_a_cooled_reheat_handler_is_not_named_like_the_heating_only_one(self):
        heating_only = row("Shared hot water air handler with water reheat")
        cooled = {**heating_only, "cooling": True}
        self.assertNotEqual(taxonomy.mint_id(heating_only), taxonomy.mint_id(cooled))
        self.assertEqual("dx", taxonomy.facets(cooled)["ahu_cooling"])

    def test_a_composite_keeps_every_parts_plant(self):
        f = taxonomy.facets(row("DOAS with fan coil air-cooled chiller with district hot water"))
        self.assertEqual((["district"], ["air_cooled_chiller"]), (f["hw_plant"], f["chw_plant"]))

    def test_configs_it_cannot_describe_are_refused_not_misnamed(self):
        cases = [
            {**row("hs12_ashp_baseboard"), "vent_type": "mixed"},
            {**row("PSZ-AC with gas coil"), "needs_zone_erv": True},
            {**row("FPFC MAU DX Coils with Scroll Chiller"), "mau": False},
        ]
        for config in cases:
            with self.subTest(config=config["id"]), self.assertRaises(taxonomy.TaxonomyUnsupported):
                taxonomy.facets(config)

    def test_needs_erv_is_read_on_any_family(self):
        config = {**row("PSZ-AC with gas coil"), "needs_erv": True, "erv_profile": "plate_erv"}
        self.assertEqual("erv", taxonomy.facets(config)["vent_heat_recovery"])


class TestFixesFromThePR239Review(unittest.TestCase):

    def test_an_ashp_override_without_a_backup_fuel_gets_the_builders_default(self):
        # psz.py: config.get('supp_htg_fuel', 'Electric')
        from btap.modeling.hvac import catalog, taxonomy
        row = dict(catalog.resolve("psz-gas-hwbb-gasboiler"))
        row.pop("supp_htg_fuel", None)
        row["heat_source"] = "ashp"
        self.assertEqual("electric", taxonomy.facets(row)["ahu_backup"])

    def test_a_case_variant_of_an_id_is_not_a_legacy_name(self):
        from btap.modeling.hvac import catalog
        self.assertFalse(catalog.is_legacy_key("PSZ-GAS-HWBB-GASBOILER"))
        self.assertTrue(catalog.is_legacy_key("PSZ RTU Gas and DX Coils and Hot Water Baseboard"))


if __name__ == "__main__":
    unittest.main()
