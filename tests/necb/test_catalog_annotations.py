"""NECB reference use reaches the catalogue from the CODES layer (HVAC taxonomy).

Astra (taxonomy review, follow-up): which NECB System uses a catalogue row is
APPLICABILITY, and `btap.modeling` knows no code. So the modeling page shows
only lineage, and `btap.codes.necb` supplies reference use, edition by
edition, from the same `system_definitions` the reference selection reads.
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk


@needs_sdk
class TestReferenceUse(unittest.TestCase):

    def test_every_definition_lands_on_a_catalogue_row(self):
        from btap.codes import resolve
        from btap.codes.necb.hvac.catalog_annotations import catalog_reference_use
        from btap.modeling.hvac import catalog
        for code in ("necb2020", "necb2025"):
            with self.subTest(code=code):
                uses = catalog_reference_use(code)
                definitions = resolve(code).rules("hvac")["system_definitions"]
                expected = sum(1 for k, v in definitions.items() if k != "table"
                               for e in ("gas", "electric") if v.get(e))
                self.assertEqual(expected, sum(len(v) for v in uses.values()))
                ids = {r["id"] for r in catalog.rows()}
                self.assertLessEqual(set(uses), ids)

    def test_an_override_is_spelled_out(self):
        from btap.codes.necb.hvac.catalog_annotations import catalog_reference_use
        labels = catalog_reference_use("necb2020")["mau-fc4-gas-chw-gasboiler-scrollchiller"]
        self.assertIn("NECB 2020 System 2 reference (electric) with boiler_fuel=Electricity", labels)

    def test_the_modeling_page_carries_no_applicability(self):
        from btap.modeling.hvac import catalog, catalog_report, taxonomy
        row = catalog.resolve("vav-hw-hwbb-gasboiler-scrollchiller")
        card = {"row": row, "display": taxonomy.display(row),
                "facets": taxonomy.facets(row), "annotations": []}
        self.assertNotIn("reference", catalog_report._search_text(card))
        card["annotations"] = ["NECB 2020 System 6 reference (gas)"]
        self.assertIn("system 6 reference", catalog_report._search_text(card))


if __name__ == "__main__":
    unittest.main()
