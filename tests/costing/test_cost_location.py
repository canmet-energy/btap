"""Where a model is costed, resolved the same way in all four domains (#237).

Two silent wrong answers: a model whose site was never set (latitude 0,
longitude 0) was priced for ST JOHNS, NEWFOUNDLAND, logged as `info`; and the
regional-factor lookup is an exact match against the table's UPPER-CASE
spelling, so ``city="Toronto"`` silently fell back to the 100 factor on every
item — indistinguishable from a typo, which was also accepted.
"""

from __future__ import annotations

import unittest

from btap.costing import _location
from tests.support import needs_sdk

LOCATIONS = [{"province_state": "ONTARIO", "city": "TORONTO"},
             {"province_state": "QUEBEC", "city": "MONTREAL"}]


class TestCanonical(unittest.TestCase):

    def test_case_and_whitespace_are_ignored(self):
        self.assertEqual(("TORONTO", "ONTARIO"),
                         _location.canonical(LOCATIONS, " toronto ", "Ontario"))

    def test_an_unlisted_place_is_refused_with_a_suggestion(self):
        with self.assertRaisesRegex(ValueError, r"not a cost location — did you mean 'TORONTO, ONTARIO'"):
            _location.canonical(LOCATIONS, "Torono", "Ontario")

    def test_the_province_must_match_too(self):
        with self.assertRaises(ValueError):
            _location.canonical(LOCATIONS, "Toronto", "Quebec")

    def test_no_table_means_no_check(self):
        self.assertEqual(("x", "y"), _location.canonical([], "x", "y"))


@needs_sdk
class TestEveryDomainResolvesTheSameWay(unittest.TestCase):
    """The CALL SITES: each domain's `cost` must route through both helpers."""

    def domains(self):
        from btap.costing import envelope, hvac, lighting, shw
        return {"envelope": envelope.cost, "hvac": hvac.cost,
                "lighting": lighting.cost, "shw": shw.cost}

    def test_an_unset_site_is_refused(self):
        import openstudio
        for name, cost in self.domains().items():
            with self.subTest(domain=name), self.assertRaisesRegex(ValueError, "site location is unset"):
                cost(openstudio.model.Model())

    def test_a_set_site_still_resolves(self):
        import openstudio
        for name, cost in self.domains().items():
            with self.subTest(domain=name):
                model = openstudio.model.Model()
                model.getSite().setLatitude(43.67)
                model.getSite().setLongitude(-79.63)
                self.assertEqual("TORONTO", cost(model).city)

    def test_a_named_city_takes_the_tables_spelling(self):
        import openstudio
        for name, cost in self.domains().items():
            with self.subTest(domain=name):
                report = cost(openstudio.model.Model(), city="toronto", province_state="Ontario")
                self.assertEqual("TORONTO", report.city)

    def test_an_unknown_city_is_refused(self):
        import openstudio
        for name, cost in self.domains().items():
            with self.subTest(domain=name), self.assertRaisesRegex(ValueError, "not a cost location"):
                cost(openstudio.model.Model(), city="Nowhereville", province_state="Ontario")


@needs_sdk
class TestLightingTakesTheCodeId(unittest.TestCase):

    def test_code_not_edition(self):
        import openstudio

        from btap.costing import lighting
        model = openstudio.model.Model()
        lighting.cost(model, code="necb2025", city="TORONTO", province_state="ONTARIO")
        with self.assertRaisesRegex(ValueError, "code id"):
            lighting.cost(model, code="2020", city="TORONTO", province_state="ONTARIO")
        with self.assertRaises(TypeError):
            lighting.cost(model, edition="2020", city="TORONTO", province_state="ONTARIO")


if __name__ == "__main__":
    unittest.main()
