"""8.4.x.9.(5): an affected run is labelled INFORMATIONAL, not certified.

Sol ruled on fetched normative text (`119`) that a reference which does not
implement the multi-energy capacity ratio cannot support an UNQUALIFIED
Code-compliance determination, citing 8.4.1.2, Division A's
building-energy-target definition, 8.4.2.10 and Division C 2.2.2.8. He was
equally clear that the TREATMENT is phylroy's product decision.

phylroy chose INFORMATIONAL: the comparison and its verdict stay visible and
the exit code is unchanged, with the qualification carried INSIDE the verdict
string rather than beside it, because a one-line verdict is the thing most
likely to be quoted on its own.

These tests pin the predicate, the label and — just as important — that an
unaffected single-fuel building is completely untouched.
"""

from __future__ import annotations

import unittest

from btap.codes import cli
from btap.codes.necb.hvac import reference


def _group(zones, fuels):
    return {"zones": list(zones), "heating_energy_types": list(fuels)}


def _facts(groups, plants=()):
    return {"zone_groups": list(groups), "plants": list(plants),
            "purchased_energy": {}}


class _Result:
    def __init__(self, compliant, report=None):
        self.compliant = compliant
        # `verdict_exit` reads `report['annual']` to refuse a verdict on a
        # shortened run, so the stub must carry one.
        self.report = {"annual": True} if report is None else report


class TestThePredicate(unittest.TestCase):
    def test_a_single_fuel_building_is_NOT_affected(self):
        facts = _facts([_group(["Z1"], ["NaturalGas"])])
        self.assertEqual([], reference.multi_energy_serving_groups(facts))
        self.assertEqual([], reference.multi_energy_serving_systems(facts))

    def test_a_dual_fuel_group_IS_affected(self):
        facts = _facts([_group(["Z1"], ["NaturalGas", "Electricity"])])
        self.assertEqual(1, len(reference.multi_energy_serving_groups(facts)))

    def test_a_PURCHASED_group_is_not_affected(self):
        """8.4.x.6 is the separate route, so it is not an unimplemented (5)."""
        facts = _facts([_group(["Z1"], ["Purchased", "Electricity"])])
        self.assertEqual([], reference.multi_energy_serving_groups(facts))

    def test_five_blocks_on_ONE_plant_are_ONE_serving_system(self):
        """The group list overcounts and the label must not: sample 11 is five
        thermal blocks on one plant and ONE disclosure finding. My first
        version of this label said "5 multi-energy serving systems"."""
        plant = {"type": "hot_water", "name": "Hot Water Loop",
                 "fuels": ["NaturalGas", "Electricity"], "boiler_count": 2,
                 "fuel_capacities_w": {"NaturalGas": None, "Electricity": None}}
        groups = [_group([f"Zone {i}"], ["NaturalGas", "Electricity"])
                  for i in range(5)]
        facts = _facts(groups, plants=[plant])
        self.assertEqual(5, len(reference.multi_energy_serving_groups(facts)))
        self.assertEqual(["Hot Water Loop"],
                         reference.multi_energy_serving_systems(facts),
                         "deduped to the plant, matching the one finding")

    def test_two_groups_with_no_covering_plant_stay_two(self):
        """The control: dedupe must not collapse genuinely separate systems."""
        facts = _facts([_group(["A"], ["NaturalGas", "Electricity"]),
                        _group(["B"], ["NaturalGas", "Electricity"])])
        self.assertEqual(2, len(reference.multi_energy_serving_systems(facts)))


class TestTheLabel(unittest.TestCase):
    AFFECTED = {"compliance_determination": "conditional",
                "code_label": "NECB 2020",
                "compliance_determination_reason": {
                    "article": "8.4.4.9.(5)",
                    "serving_systems": ["Hot Water Loop"],
                    "condition": "approval by the authority having jurisdiction",
                    "ahj_must_approve": [
                        "how 8.4.4.9.(5)'s multi-energy capacity allocation is "
                        "to be REPRESENTED when 8.4.4.9.(6) bands the boiler "
                        "count and each boiler object carries ONE fixed fuel."],
                    "why": "..."}}

    def test_the_one_line_determination_carries_the_qualification(self):
        """The qualification must be INSIDE the string, because this is the
        line that gets quoted alone."""
        got = cli.determination(_Result(True), self.AFFECTED)
        self.assertIn("COMPLIANT", got)
        self.assertIn("INFORMATIONAL", got)
        self.assertIn("CONDITIONAL ON APPROVAL BY THE AUTHORITY HAVING "
                      "JURISDICTION", got,
                      "phylroy's decision is informational AND conditional: "
                      "where the acceptable-solution text is ambiguous an "
                      "authority must accept the interpretation")

    def test_a_FAILING_affected_run_is_also_labelled(self):
        got = cli.determination(_Result(False), self.AFFECTED)
        self.assertIn("NOT COMPLIANT", got)
        self.assertIn("INFORMATIONAL", got)
        self.assertIn("AUTHORITY HAVING JURISDICTION", got)

    def test_the_block_opens_with_the_NOT_A_DETERMINATION_banner(self):
        """The same banner the --quick path uses, so the two read alike."""
        block = cli.verdict_block(_Result(True), self.AFFECTED)
        self.assertIn("*** NOT A CODE-COMPLIANT DETERMINATION ***", block)
        self.assertIn("INFORMATIONAL only", block)

    def test_the_block_states_the_CONDITION_and_what_must_be_approved(self):
        """A reader must be able to act: which authority, and on what."""
        block = cli.verdict_block(_Result(True), self.AFFECTED)
        self.assertIn("CONDITIONAL", block)
        self.assertIn("authority having jurisdiction must accept", block)
        self.assertIn("acceptable-solution", block,
                      "and WHY it is not ours to decide")
        self.assertIn("REPRESENTED", block, "the condition itself is listed")

    def test_the_block_NAMES_the_article_and_each_serving_system(self):
        """A reader must be able to see WHICH systems are unresolved, not just
        that some are."""
        block = cli.verdict_block(_Result(True), self.AFFECTED)
        self.assertIn("8.4.4.9.(5)", block)
        self.assertIn("Hot Water Loop", block)

    def test_an_UNAFFECTED_run_is_completely_untouched(self):
        """Most buildings are single-fuel and must see no change at all."""
        plain = {"compliance_determination": "code", "code_label": "NECB 2020"}
        self.assertNotIn("CONDITIONAL", cli.determination(_Result(True), plain))
        self.assertEqual("COMPLIANT", cli.determination(_Result(True), plain))
        block = cli.verdict_block(_Result(True), plain)
        self.assertNotIn("INFORMATIONAL", block)
        self.assertNotIn("NOT A CODE-COMPLIANT DETERMINATION", block)
        self.assertIn("VERDICT: COMPLIANT", block)

    def test_a_report_with_NO_determination_key_behaves_as_before(self):
        """Older reports and non-annual runs carry no key at all."""
        self.assertEqual("COMPLIANT",
                         cli.determination(_Result(True),
                                           {"code_label": "NECB 2020"}))

    def test_the_exit_code_is_UNCHANGED_by_the_label(self):
        """phylroy's choice is informational, not blocking: an affected
        compliant run still exits 0. This is the part a CI pipeline sees, and
        it is the known weakness of the choice — pinned so that any later
        change to it is deliberate."""
        self.assertEqual(cli.verdict_exit(_Result(True)),
                         cli.EXIT["compliant"])
        self.assertEqual(cli.verdict_exit(_Result(False)),
                         cli.EXIT["not_compliant"])


class TestTheREPORTCarriesTheCondition(unittest.TestCase):
    """phylroy: "that is a part of the report". The HTML report is the
    AHJ-facing artifact, so the condition must be in the verdict banner, not
    only in the CLI and the audit."""

    def _banner(self, report):
        from btap.codes.report import sections

        return sections.verdict_banner({"report": report})

    def test_the_banner_badges_and_states_the_condition(self):
        html = self._banner({
            "compliant": True, "annual": True, "code_label": "NECB 2020",
            "compliance_determination": "conditional",
            "compliance_determination_reason": {
                "article": "8.4.4.9.(5)",
                "serving_systems": ["Hot Water Loop"],
                "ahj_must_approve": ["how the allocation is REPRESENTED"]}})
        self.assertIn("CONDITIONAL", html)
        self.assertIn("AHJ APPROVAL REQUIRED", html)
        self.assertIn("NOT A CODE-COMPLIANT DETERMINATION", html)
        self.assertIn("authority having jurisdiction must accept", html)
        self.assertIn("how the allocation is REPRESENTED", html)
        self.assertIn("Hot Water Loop", html)

    def test_an_unaffected_report_banner_is_untouched(self):
        html = self._banner({"compliant": True, "annual": True,
                             "code_label": "NECB 2020",
                             "compliance_determination": "code"})
        self.assertNotIn("CONDITIONAL", html)
        self.assertNotIn("AHJ APPROVAL", html)
        self.assertIn("PERFORMANCE PATH: PASS", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
