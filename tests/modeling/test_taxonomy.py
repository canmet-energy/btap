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
    return next(r for r in ROWS if r["name"] == name)


class TestEveryRowIsPlaced(unittest.TestCase):

    def test_every_row_lands_in_exactly_one_type(self):
        placed = [r["name"] for types in taxonomy.tree().values()
                  for rows in types.values() for r in rows]
        self.assertEqual(sorted(r["name"] for r in ROWS), sorted(placed))

    def test_facets_stay_in_their_vocabularies(self):
        for r in ROWS:
            with self.subTest(row=r["name"]):
                facets = taxonomy.facets(r)      # raises on a value outside the vocabulary
                self.assertEqual(set(taxonomy.FACETS), set(facets))

    def test_every_vocabulary_value_is_used(self):
        """A value no row can produce is a dead filter an engineer would tick
        and get nothing from."""
        used = defaultdict(set)
        for r in ROWS:
            for key, value in taxonomy.facets(r).items():
                used[key].update(value if key in taxonomy.MULTI else [value])
        for key, vocab in taxonomy.FACETS.items():
            with self.subTest(facet=key):
                self.assertEqual([], [v for v in vocab if v not in used[key]])


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

    def test_necb_system_4_is_told_apart_by_provenance_not_equipment(self):
        three = row("PSZ RTU Gas and DX Coils and Hot Water Baseboard")
        four = row("PSZ RTU with exhaust Gas and DX Coils and Hot Water Baseboard")
        f3, f4 = taxonomy.facets(three), taxonomy.facets(four)
        self.assertEqual({k: v for k, v in f3.items() if k != "necb_lineage"},
                         {k: v for k, v in f4.items() if k != "necb_lineage"})
        self.assertEqual(taxonomy.mint_id(three) + "-necbs4", taxonomy.mint_id(four))
        self.assertNotIn("exhaust", taxonomy.display(four).lower())


class TestFacetsFollowTheirFields(unittest.TestCase):
    """Field-sensitivity: change the field, the facet (and the ID) must change."""

    CASES = [
        ("PSZ RTU Gas and DX Coils and Hot Water Baseboard", "heating_coil_type", "Electric", "ahu_heating"),
        ("PSZ RTU Gas and DX Coils and Hot Water Baseboard", "baseboard_type", "Electric", "zone_heating"),
        ("PSZ-AC with gas coil", "per_zone", False, "scope"),
        ("MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard", "chiller_type", "Centrifugal", "chw_plant"),
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


if __name__ == "__main__":
    unittest.main()
