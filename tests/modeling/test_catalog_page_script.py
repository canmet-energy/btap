"""The catalogue page's SHIPPED JavaScript filters what Python filters.

Astra (taxonomy review, follow-up): a Python reimplementation would test the
data, not the code a browser runs. So this executes the page's own
`SCRIPT_JS` — the exact string `catalog_report` writes into the HTML — in a
JavaScript engine (QuickJS through the `quickjs` package, which the CI
`python` lane installs; skipped with that reason where it is absent), feeds it
the same per-system data the page embeds, and requires its filtering to agree
with `btap.modeling.systems(**filters)`.
"""

from __future__ import annotations

import json
import unittest

from btap.modeling.hvac import catalog, catalog_report, taxonomy

try:
    import quickjs
except ImportError:                       # pragma: no cover - environment-dependent
    quickjs = None


def _items():
    out = []
    for row in catalog.rows():
        card = {"row": row, "display": taxonomy.display(row),
                "facets": taxonomy.facets(row), "annotations": []}
        out.append({"id": row["id"], "facets": card["facets"],
                    "search": catalog_report._search_text(card)})
    return out


@unittest.skipIf(quickjs is None, "no JavaScript engine: pip install quickjs")
class TestTheShippedScript(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ctx = quickjs.Context()
        # The shipped script, verbatim. It defines BtapCatalog and touches the
        # DOM only when `document` exists, which it does not here.
        cls.ctx.eval(catalog_report.SCRIPT_JS)
        cls.ctx.eval("var ITEMS = " + json.dumps(_items()) + ";")

    def run_filter(self, query, selected):
        result = self.ctx.eval(
            "JSON.stringify(BtapCatalog.filterItems(ITEMS, %s, %s))"
            % (json.dumps(query), json.dumps(selected)))
        return json.loads(result)

    def test_filters_agree_with_python(self):
        cases = [
            {"system_type": ["psz"], "ahu_heating": ["gas"]},
            {"terminal": ["fc4"], "hw_plant": ["awhp"]},
            {"category": ["oa_plus_zone"], "zone_heating": ["elec_baseboard"]},
            {"chw_plant": ["water_cooled_chiller", "air_cooled_chiller"]},
            {"vent_heat_recovery": ["erv", "hrv"]},
            {"necb_lineage": ["6"]},
        ]
        for selected in cases:
            with self.subTest(selected=selected):
                js = sorted(self.run_filter("", selected)["visible"])
                py = sorted(r["id"] for r in catalog.list_systems(**selected))
                self.assertTrue(py)
                self.assertEqual(py, js)

    def test_search_words_and_together(self):
        js = set(self.run_filter("gas rooftop", {})["visible"])
        self.assertTrue(js)
        for item in _items():
            if item["id"] in js:
                self.assertIn("gas", item["search"])
                self.assertIn("rooftop", item["search"])
        self.assertIn("psz-gas-hwbb-gasboiler", js)

    def test_a_legacy_name_finds_its_system(self):
        js = self.run_filter("PSZ RTU Gas and DX Coils and Hot Water Baseboard", {})["visible"]
        self.assertIn("psz-gas-hwbb-gasboiler", js)

    def test_counts_are_disjunctive(self):
        """A group's counts ignore that group's own ticks: ticking 'gas'
        must not zero the 'electric' chip in the same group."""
        before = self.run_filter("", {"system_type": ["psz"]})["counts"]["ahu_heating"]
        after = self.run_filter("", {"system_type": ["psz"], "ahu_heating": ["gas"]})["counts"]["ahu_heating"]
        self.assertEqual(before, after)
        self.assertGreater(after.get("electric", 0), 0)

    def test_the_url_state_round_trips(self):
        state = {"q": "gas rooftop", "selected": {"ahu_heating": ["gas", "electric"]},
                 "sys": "psz-gas-hwbb-gasboiler"}
        back = json.loads(self.ctx.eval(
            "JSON.stringify(BtapCatalog.parseHash(BtapCatalog.buildHash(%s)))" % json.dumps(state)))
        self.assertEqual(state, back)


if __name__ == "__main__":
    unittest.main()
