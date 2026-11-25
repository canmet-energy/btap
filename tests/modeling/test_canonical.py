"""The RETIRED canonical naming grammar still resolves (HVAC taxonomy).

The generated canonical names (`<primary>[ + <zone>][ (<plant>)]`) were
replaced by stable ids and facet-generated display names
(docs/plans/HVAC_TAXONOMY_PLAN.md). Each row keeps its old canonical name in
`aliases`, so code or notes that used one still build the same system; nothing
generates new canonical names.
"""

import unittest

import btap.modeling as modeling
from btap.modeling.hvac import canonical, catalog, taxonomy


class TestTheRetiredGrammarStillResolves(unittest.TestCase):

    def test_every_rows_old_canonical_name_resolves_to_that_row(self):
        for row in catalog.rows():
            with self.subTest(id=row["id"]):
                self.assertTrue(row["aliases"], "the retired canonical name was not kept")
                self.assertEqual(row["id"], catalog.resolve(row["aliases"][0])["id"])

    def test_the_documented_examples(self):
        # The pair the grammar was introduced for: CBECS fuel-first and NECB
        # medium-first legacy names, and an ECM id.
        for old, expected in [
                ("hot water baseboards (gas boiler)", "bb-hwbb-gasboiler"),
                ("packaged single-zone DX with gas heat + hot water baseboards (gas boiler)",
                 "psz-gas-hwbb-gasboiler"),
                ("DOAS ASHP + zone PTHPs", "doas-pthp-ashp-elecsupp"),
                ("electric baseboards", "bb-elecbb")]:
            with self.subTest(old=old):
                self.assertEqual(expected, catalog.resolve(old)["id"])

    def test_an_old_canonical_name_still_builds(self):
        from btap._compat import sorted_by_name
        from tests.support import load_fixture

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, "hot water baseboards (gas boiler)", zones)
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(2, len(model.getBoilerHotWaters()))

    def test_the_shim_returns_the_display_name(self):
        row = catalog.resolve("psz-gas-hwbb-gasboiler")
        self.assertEqual(taxonomy.display(row), canonical.name(row))

    def test_aliases_never_shadow_an_id(self):
        ids = {r["id"].casefold() for r in catalog.rows()}
        for row in catalog.rows():
            for alias in row["aliases"]:
                self.assertNotIn(alias.casefold(), ids - {row["id"].casefold()})


if __name__ == "__main__":
    unittest.main()
