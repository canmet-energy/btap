"""Catalogue row facts RAISE on a broken composite instead of skipping it.

They moved from `btap.stock.identify` to `btap.modeling.hvac.row_facts` so the
catalogue taxonomy can use them, and they now feed system NAMES: a part that
silently dropped out would name a system for equipment it does not build
(Astra, HVAC taxonomy review finding 5).
"""

from __future__ import annotations

import unittest

from btap.modeling.hvac import catalog, row_facts


class TestEveryRowHasFacts(unittest.TestCase):

    def test_every_catalogue_row_computes(self):
        for row in catalog.rows():
            with self.subTest(row=row["name"]):
                row_facts.row_heating_media(row)
                if row.get("family") == "composite":
                    families, _ = row_facts.composite_shape(row)
                    self.assertTrue(families, "a composite with no resolvable part")


class TestABrokenCompositeRaises(unittest.TestCase):

    BROKEN = {"name": "broken", "family": "composite",
              "parts": [{"name": "no such system"}]}

    def test_an_unresolved_part_raises(self):
        for fact in (row_facts.composite_shape, row_facts.row_heating_media):
            with self.subTest(fact=fact.__name__), \
                    self.assertRaisesRegex(row_facts.CatalogFactError, "does not resolve"):
                fact(self.BROKEN)

    def test_runaway_nesting_raises(self):
        with self.assertRaisesRegex(row_facts.CatalogFactError, "nests more than"):
            row_facts.composite_shape(self.BROKEN, _depth=4)

    def test_identify_still_uses_the_same_objects(self):
        from btap.stock import identify
        self.assertIs(identify._composite_shape, row_facts.composite_shape)
        self.assertIs(identify._BUILDER_COIL_DEFAULTS, row_facts.BUILDER_COIL_DEFAULTS)


if __name__ == "__main__":
    unittest.main()
