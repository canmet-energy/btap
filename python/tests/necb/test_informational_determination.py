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
from tests.support import needs_sdk


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

    def test_the_BLOCK_prose_asserts_nothing_about_the_equipment_either(self):
        """The reason dict and the rendered block are SEPARATE copies of this
        prose. `122` blocker 1 was fixed in `path.py`'s `why` while
        `cli.py`'s block kept printing "the reference elects ONE energy type"
        — the seventh instance of one overclaim, surviving in another layer
        because the test only looked at the first."""
        block = cli.verdict_block(_Result(True), self.AFFECTED)
        self.assertIn("NOT established by this tool", block)
        for overclaim in ("elects ONE energy type", "no single-fuel"):
            self.assertNotIn(overclaim, block)

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
        self.assertIn("conditions", block,
                      "the wrapper must not call them all interpretations: "
                      "an ALTERNATIVE SOLUTION is a requirement the text DOES "
                      "decide and this tool does not meet")
        self.assertIn("ALTERNATIVE SOLUTION", block,
                      "and the block must distinguish the two kinds")
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

    def test_the_banner_asserts_NOTHING_about_the_reference_equipment(self):
        """The eighth instance of one overclaim lived HERE, surviving its
        removal from `path.py` and `cli.py`, because this test asserted the
        conditional text was PRESENT and never that the withdrawn claim was
        ABSENT. The frozen scenario could not catch it either: the annual tier
        runs `--quick --no-report`, so no HTML is rendered at all."""
        html = self._banner({
            "compliant": True, "annual": True, "code_label": "NECB 2020",
            "compliance_determination": "conditional",
            "compliance_determination_reason": {
                "article": "8.4.4.9.(5)",
                "serving_systems": ["Hot Water Loop"],
                "ahj_must_approve": ["how the allocation is REPRESENTED"]}})
        for withdrawn in ("elects ONE energy type", "no single-fuel basis",
                          "reference elects"):
            self.assertNotIn(withdrawn, html)
        self.assertIn("NOT established by this tool", html)

    def test_the_banner_does_not_call_an_alternative_solution_an_interpretation(self):
        """Saying the authority must accept an "interpretation" because the
        text "does not resolve it" is FALSE when the condition is AHJ-1:
        8.4.x.9.(5)(a) does resolve the requirement and this tool does not meet
        it. The neutral word is "conditions"."""
        html = self._banner({
            "compliant": True, "annual": True, "code_label": "NECB 2020",
            "compliance_determination": "conditional",
            "compliance_determination_reason": {
                "article": "8.4.4.9.(5)",
                "serving_systems": ["Hot Water Loop"],
                "ahj_must_approve": ["an ALTERNATIVE SOLUTION: ..."]}})
        self.assertIn("conditions", html)
        self.assertNotIn("does not resolve it", html)

    def test_an_unaffected_report_banner_is_untouched(self):
        html = self._banner({"compliant": True, "annual": True,
                             "code_label": "NECB 2020",
                             "compliance_determination": "code"})
        self.assertNotIn("CONDITIONAL", html)
        self.assertNotIn("AHJ APPROVAL", html)
        self.assertIn("PERFORMANCE PATH: PASS", html)


class TestTheREALHelperOnRealModels(unittest.TestCase):
    """Sol's `122` blocker 5: nothing invoked the determination creator at all.
    The presentation tests above build the reason dictionary BY HAND, so they
    pin the rendering and say nothing about whether the helper produces it.

    These drive `_mark_informational_if_multi_energy` on models built here,
    and cover the distinction `122` blocker 3 was about: a hydronic plant
    carrying both fuels raises the boiler-cardinality question, and a mixed
    group with no such plant must NOT.
    """

    @staticmethod
    def _model(plant_fuels, *, with_plant=True):
        import openstudio

        m = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(m)
        zone.setName("Zone 1")
        if not with_plant:
            return m
        loop = openstudio.model.PlantLoop(m)
        loop.setName("Hot Water Loop")
        loop.sizingPlant().setLoopType("Heating")
        loop.setLoadDistributionScheme("SequentialLoad")
        for i, fuel in enumerate(plant_fuels):
            b = openstudio.model.BoilerHotWater(m)
            b.setName(f"{'Primary' if i == 0 else 'Secondary'} Boiler")
            b.setFuelType(fuel)
            b.setNominalCapacity(52_000.0)
            loop.addSupplyBranchForComponent(b)
        coil = openstudio.model.CoilHeatingWaterBaseboard(m)
        bb = openstudio.model.ZoneHVACBaseboardConvectiveWater(
            m, m.alwaysOnDiscreteSchedule(), coil)
        bb.addToThermalZone(zone)
        loop.addDemandBranchForComponent(coil)
        return m

    def _run_helper(self, model):
        from btap.audit import AuditLog
        from btap.codes import resolve
        from btap.codes.necb import path as necb_path

        class _Run:
            pass

        run = _Run()
        run.proposed = model
        run.report = {}
        run.ruleset = resolve("necb2020")
        audit = AuditLog()
        necb_path._mark_informational_if_multi_energy(run, audit)
        return run.report, audit

    @needs_sdk
    def test_a_HYDRONIC_dual_fuel_plant_raises_the_boiler_question(self):
        report, audit = self._run_helper(
            self._model(("NaturalGas", "Electricity")))
        self.assertEqual("conditional", report["compliance_determination"])
        reason = report["compliance_determination_reason"]
        self.assertEqual(["Hot Water Loop"], reason["hydronic_serving_systems"])
        self.assertEqual(["AHJ-1", "AHJ-3"], reason["ahj_ids"])
        joined = " ".join(reason["ahj_must_approve"])
        self.assertIn("ALTERNATIVE SOLUTION", joined)
        self.assertIn("REPRESENTED", joined, "the cardinality question applies")
        warned = [e for e in audit.entries
                  if "INFORMATIONAL AND CONDITIONAL" in str(e.get("action"))]
        self.assertEqual(1, len(warned))

    @needs_sdk
    def test_a_SINGLE_fuel_plant_is_not_conditional_at_all(self):
        report, audit = self._run_helper(self._model(("NaturalGas",)))
        self.assertEqual("code", report["compliance_determination"])
        self.assertNotIn("compliance_determination_reason", report)
        self.assertEqual([], [e for e in audit.entries
                              if "CONDITIONAL" in str(e.get("action"))])

    @needs_sdk
    def test_the_prose_asserts_NOTHING_about_the_reference_equipment(self):
        """`122` blocker 1: the reason used to say "the reference elects ONE
        energy type", which is false for outcomes already reproduced."""
        report, _audit = self._run_helper(
            self._model(("NaturalGas", "Electricity")))
        why = report["compliance_determination_reason"]["why"]
        self.assertIn("not established by this tool", why)
        for overclaim in ("elects ONE energy type", "no single-fuel basis"):
            self.assertNotIn(overclaim, why)

    def test_a_NON_hydronic_mixed_group_omits_the_boiler_question(self):
        """`122` blocker 3: a bare dual-fuel group with no plant carrying its
        fuels was handed the boiler-cardinality question anyway. Driven
        through the selector rather than a built model, because the shape is
        a group whose fuels no single plant covers."""
        facts = {"zone_groups": [_group(["Z1"],
                                        ["NaturalGas", "Electricity"])],
                 "plants": [], "purchased_energy": {}}
        self.assertEqual(
            [], reference.multi_energy_serving_systems(facts,
                                                       hydronic_only=True),
            "no plant carries both fuels, so no boiler question arises")
        self.assertEqual(
            1, len(reference.multi_energy_serving_systems(facts)),
            "but the ratio question still applies to the group")


if __name__ == "__main__":
    unittest.main(verbosity=2)
