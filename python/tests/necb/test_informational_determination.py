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

import re
import unittest

from btap.codes import cli
from btap.codes.necb.hvac import reference
from tests.support import needs_sdk

from .support import (
    CARDINALITY_CONDITION,
    MULTI_ENERGY_CONDITION,
    SYSTEM_5_CONDITION,
    real_conditional_report,
)


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
    #: Built by the REAL `_set_conditional`, so these renderer tests
    #: cannot pass against a shape the builder no longer produces. The
    #: hand-written version omitted what the builder appends, which is
    #: how the surface lost the condition's substance.
    AFFECTED = real_conditional_report([MULTI_ENERGY_CONDITION])

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
        # Whitespace-normalized: `_wrap_condition` breaks at 62 columns, so a
        # raw `assertIn` fails on a phrase a line break happens to split —
        # which says nothing about whether the claim reached the reader.
        flat = re.sub(r"\s+", " ", block)
        self.assertIn("NOT established by this tool", flat)
        for overclaim in ("elects ONE energy type", "no single-fuel"):
            self.assertNotIn(overclaim, flat)

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
        flat = re.sub(r"\s+", " ", block)
        self.assertIn("conditions", flat,
                      "the wrapper must not call them all interpretations: "
                      "an ALTERNATIVE SOLUTION is a requirement the text DOES "
                      "decide and this tool does not meet")
        self.assertIn("ALTERNATIVE SOLUTION", flat,
                      "and the block must distinguish the two kinds")
        self.assertIn("NON-CONFORMING substitution", flat,
                      "the condition's own title is listed, not prose this "
                      "renderer invents")

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
        html = self._banner(
            real_conditional_report([MULTI_ENERGY_CONDITION,
                                     CARDINALITY_CONDITION]))
        self.assertIn("CONDITIONAL", html)
        self.assertIn("AHJ APPROVAL REQUIRED", html)
        self.assertIn("NOT A CODE-COMPLIANT DETERMINATION", html)
        self.assertIn("authority having jurisdiction must accept", html)
        self.assertIn("permits more than one boiler", html,
                      "AHJ-3's own title carries the cardinality question")
        self.assertIn("Hot Water Loop", html)

    def test_the_banner_asserts_NOTHING_about_the_reference_equipment(self):
        """The eighth instance of one overclaim lived HERE, surviving its
        removal from `path.py` and `cli.py`, because this test asserted the
        conditional text was PRESENT and never that the withdrawn claim was
        ABSENT. The frozen scenario could not catch it either: the annual tier
        runs `--quick --no-report`, so no HTML is rendered at all."""
        html = self._banner(
            real_conditional_report([MULTI_ENERGY_CONDITION]))
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
                "conditions": [
                    {"id": "AHJ-1", "status": "alternative-solution",
                     "title": "a single-fuel reference is a NON-CONFORMING "
                              "substitution",
                     "article": "8.4.4.9.(5)", "target": "Hot Water Loop",
                     "detail": "what the reference's final heating equipment "
                               "carries is NOT established by this tool"}],
                "ahj_ids": ["AHJ-1"],
                "ahj_register": "docs/NECB_AHJ_QUESTIONS.md",
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
        """Drive the REAL path now that applicability is site-owned.

        `_mark_informational_if_multi_energy` is gone. It re-characterized the
        model HERE to decide whether AHJ-1 and AHJ-3 had fired, which was a
        second source of truth beside the disclosure branch that already knew
        (Sol, `127`). So this helper runs the two halves in the order the
        pipeline does: the rule site emits citations onto the audit, then the
        collector resolves them.

        That makes this a stronger test than before — it now proves the two
        halves AGREE, where previously a determination could be reached with
        no disclosure having fired at all.
        """
        from btap.audit import AuditLog
        from btap.codes import resolve
        from btap.codes.necb import path as necb_path
        from btap.codes.necb.hvac import reference as hvac_reference
        from btap.modeling.hvac import classify

        class _Run:
            pass

        run = _Run()
        run.proposed = model
        run.ruleset = resolve("necb2020")
        run.report = {"annual": True, "code": "necb2020"}
        audit = AuditLog()

        facts = classify.characterize(model)
        selection = {"special_rules": {
            "purchased_heating": {"article": "8.4.4.6.(1)"}}}
        disclosed = set()
        for group in facts.get("zone_groups") or ():
            hvac_reference._disclose_multi_energy(
                group, selection, facts, audit, ruleset=run.ruleset,
                disclosed=disclosed)
        necb_path._resolve_ahj_conditions(run, audit)
        return run.report, audit

    @needs_sdk
    def test_a_HYDRONIC_dual_fuel_plant_raises_the_boiler_question(self):
        report, audit = self._run_helper(
            self._model(("NaturalGas", "Electricity")))
        self.assertEqual("conditional", report["compliance_determination"])
        reason = report["compliance_determination_reason"]
        # The ids are now whatever the SITE cited, resolved through the
        # generated register — not recomputed here from the model.
        self.assertEqual(["AHJ-1", "AHJ-3"], reason["ahj_ids"])
        statuses = {c["id"]: c["status"] for c in reason["conditions"]}
        self.assertEqual("alternative-solution", statuses["AHJ-1"])
        self.assertEqual("referral", statuses["AHJ-3"])
        targets = {c["target"] for c in reason["conditions"]}
        self.assertEqual(
            {"Hot Water Loop"}, targets,
            "the condition names the PLANT, because that is what the firing "
            "entry targets when one plant carries every fuel — more useful to "
            "a reviewer than the zone list")
        joined = " ".join(reason["ahj_must_approve"])
        self.assertIn("ALTERNATIVE SOLUTION", joined)
        # The cardinality question now arrives as AHJ-3's own TITLE, not as
        # hardcoded prose in `path.py`. The word "REPRESENTED" lived in that
        # prose, which Sol's `127` required removing so an AHJ-11 System-5
        # condition would not be rendered as a boiler condition.
        self.assertIn("more than one boiler", joined,
                      "the cardinality question reaches the reader")
        self.assertIn("INTERPRETATION", joined,
                      "and is labelled a referral, not an alternative solution")
        self.assertEqual(
            ["AHJ-1", "AHJ-3"],
            [entry["id"] for entry in report["ahj_applied"]],
            "every fired id is listed for traceability, conditional or not")

    @needs_sdk
    def test_a_SINGLE_fuel_plant_is_not_conditional_at_all(self):
        report, audit = self._run_helper(self._model(("NaturalGas",)))
        # Nothing cited, so nothing requires approval and the determination is
        # stated POSITIVELY as "code". A missing key could not distinguish an
        # unqualified determination from a run where the question was never
        # asked (Sol's `127`).
        self.assertEqual("code", report["compliance_determination"])
        self.assertNotIn("compliance_determination_reason", report)
        self.assertNotIn("ahj_applied", report)
        self.assertEqual([], [e for e in audit.entries if e.get("ahj")],
                         "a single-fuel plant raises no register question")

    @needs_sdk
    def test_the_prose_asserts_NOTHING_about_the_reference_equipment(self):
        """`122` blocker 1: the reason used to say "the reference elects ONE
        energy type", which is false for outcomes already reproduced."""
        report, _audit = self._run_helper(
            self._model(("NaturalGas", "Electricity")))
        reason = report["compliance_determination_reason"]
        # The hard-won wording now travels on the CONDITION, quoted from the
        # entry that fired, because the generic `why` cannot know any one
        # question's substance. It must still reach the reader.
        surface = " ".join(
            [reason["why"]] + reason["ahj_must_approve"]
            + [str(c.get("detail")) for c in reason["conditions"]])
        self.assertIn("not established", surface)
        for overclaim in ("reference elects ONE energy type",
                          "no single-fuel basis satisfies"):
            self.assertNotIn(overclaim, surface)

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


class TestANonMultiEnergyConditionRendersTruthfully(unittest.TestCase):
    """Sol's `127`: "An AHJ-11 System-5 condition must not be rendered as a
    boiler-capacity condition."

    Before D-100 the CLI block and HTML banner described the multi-energy
    capacity ratio in hardcoded prose, so ANY conditional run would have been
    reported as a multi-energy one. These assert the absence of that
    vocabulary, not merely the presence of the new text — the distinction that
    let the withdrawn claim survive on the HTML surface for eight rounds.
    """

    MULTI_ENERGY_VOCABULARY = (
        "multi-energy", "capacity-ratio", "capacity ratio",
        "final heating equipment", "boiler",
    )

    def _surfaces(self, conditions):
        from btap.codes import cli
        from btap.codes.report import sections

        report = real_conditional_report(conditions)

        class _Run:
            compliant = True
            report = {"annual": True}

        return {
            "CLI block": cli.verdict_block(_Run(), report),
            "HTML banner": sections.verdict_banner({"report": report}),
        }

    def test_a_SYSTEM_5_condition_names_itself(self):
        for name, text in self._surfaces([SYSTEM_5_CONDITION]).items():
            with self.subTest(name):
                flat = re.sub(r"\s+", " ", text)
                self.assertIn("AHJ-11", flat)
                self.assertIn("two-pipe System 5", flat)
                self.assertIn("8.4.4.1.(5)", flat, "its OWN article")

    def test_a_SYSTEM_5_condition_borrows_no_multi_energy_vocabulary(self):
        for name, text in self._surfaces([SYSTEM_5_CONDITION]).items():
            flat = re.sub(r"\s+", " ", text).lower()
            for word in self.MULTI_ENERGY_VOCABULARY:
                with self.subTest(name, word=word):
                    self.assertNotIn(
                        word, flat,
                        "a System-5 heating-presence question was described "
                        "in multi-energy terms")

    def test_the_MULTI_ENERGY_condition_still_names_itself(self):
        """The control. If the renderers had simply lost all substance, the
        test above would pass for the wrong reason."""
        for name, text in self._surfaces([MULTI_ENERGY_CONDITION]).items():
            with self.subTest(name):
                flat = re.sub(r"\s+", " ", text)
                self.assertIn("AHJ-1", flat)
                self.assertIn("NON-CONFORMING substitution", flat)
                self.assertIn("NOT established by this tool", flat)


class TestTheResolverPolicy(unittest.TestCase):
    """The collector owns POLICY only, and these pin every branch of it."""

    def _report(self, citations, *, annual=True, code="necb2020"):
        from btap.audit import AuditLog
        from btap.codes.necb import path as necb_path

        class _Run:
            pass

        run = _Run()
        run.report = {"annual": annual, "code": code}
        run.ruleset = type("R", (), {"code": code})()
        audit = AuditLog()
        for citation in citations:
            audit.warn("selection", "a choice was made", target="Z1",
                       article="8.4.4.9.(5)", ahj=citation)
        necb_path._resolve_ahj_conditions(run, audit)
        return run.report

    def test_several_ids_on_ONE_entry_all_resolve(self):
        report = self._report(["AHJ-1 AHJ-5"])
        self.assertEqual(["AHJ-1", "AHJ-5"],
                         [e["id"] for e in report["ahj_applied"]])
        self.assertEqual(["AHJ-1"],
                         report["compliance_determination_reason"]["ahj_ids"],
                         "only the approval-required subset")

    def test_a_repeated_id_on_the_SAME_target_is_ONE_choice(self):
        """Rewritten for Sol's `128`.3. This asserted a count of 3 for three
        citations on one target, which was the defect: the efficiency pass runs
        twice, so the same boiler's same class decision was being counted as
        two or three questions. One target, one choice."""
        report = self._report(["AHJ-1", "AHJ-1", "AHJ-1"])
        applied = report["ahj_applied"]
        self.assertEqual(1, len(applied))
        self.assertEqual(1, applied[0]["count"],
                         "three entries on one target are one live choice")

    def test_the_same_id_on_DIFFERENT_targets_counts_each(self):
        """The control: deduping must not collapse two real choices. Two equal
        active boilers in the 176-352 kW band are two questions."""
        from btap.audit import AuditLog
        from btap.codes.necb import path as necb_path

        class _Run:
            pass

        run = _Run()
        run.report = {"annual": True, "code": "necb2020"}
        run.ruleset = type("_R", (), {"code": "necb2020"})()
        audit = AuditLog()
        for target in ("Primary Boiler", "Secondary Boiler"):
            audit.warn("efficiency", "a choice", target=target, ahj="AHJ-1")
        necb_path._resolve_ahj_conditions(run, audit)
        self.assertEqual([("AHJ-1", 2)],
                         [(e["id"], e["count"])
                          for e in run.report["ahj_applied"]])

    def test_ids_are_ordered_NUMERICALLY_not_lexically(self):
        report = self._report(["AHJ-11 AHJ-2 AHJ-1"])
        self.assertEqual(["AHJ-1", "AHJ-2", "AHJ-11"],
                         [e["id"] for e in report["ahj_applied"]],
                         "AHJ-11 sorts after AHJ-2, not between AHJ-1 and 2")

    def test_a_RULED_or_TOOL_GAP_id_alone_sets_no_CONDITIONAL(self):
        """It is still an unqualified determination — "code", not nothing, and
        never "conditional". A tool gap stays a defect and a ruled question
        stays settled."""
        for citation in ("AHJ-5", "AHJ-6", "AHJ-13", "AHJ-5 AHJ-6"):
            with self.subTest(citation):
                report = self._report([citation])
                self.assertEqual("code", report["compliance_determination"])
                self.assertNotIn("compliance_determination_reason", report)
                self.assertTrue(report["ahj_applied"],
                                "but it is still recorded as applied")

    def test_an_UNKNOWN_id_is_refused_not_dropped(self):
        from btap.codes import ahj

        with self.assertRaises(ahj.UnknownAHJ):
            self._report(["AHJ-9999"])

    def test_a_MALFORMED_citation_is_refused(self):
        from btap.codes import ahj

        for bad in ("ahj-1", "AHJ_1", "AHJ-"):
            with self.subTest(bad), self.assertRaises(ahj.UnknownAHJ):
                self._report([bad])

    def test_a_citation_whose_EDITION_excludes_the_run_is_refused(self):
        from btap.codes import ahj

        original = ahj.by_id
        try:
            narrowed = {k: dict(v) for k, v in original().items()}
            narrowed["AHJ-1"]["editions"] = ["necb2025"]
            ahj.by_id = lambda: narrowed
            with self.assertRaises(ahj.UnknownAHJ):
                self._report(["AHJ-1"], code="necb2020")
        finally:
            ahj.by_id = original

    def test_a_NON_annual_run_keeps_the_citations_but_invents_no_verdict(self):
        report = self._report(["AHJ-1"], annual=False)
        self.assertEqual(["AHJ-1"], [e["id"] for e in report["ahj_applied"]])
        self.assertNotIn("compliance_determination", report,
                         "a run with no determination has none to qualify")


class TestTheDeterminationMATRIX(unittest.TestCase):
    """Every combination of (what fired) x (is this an annual run).

    Two of these were wrong in the first implementation and neither would have
    shown up in the local lanes. `"code"` was not written at all, so an
    unqualified annual determination became an ABSENT key — which the
    dispatch-only parity baseline still carried as `"code"`, so it would have
    gone red in CI rather than here. And a `--quick` run was setting
    `conditional` while its own CLI printed `VERDICT: NO DETERMINATION`.
    """

    CASES = (
        ("nothing cited", (), True, "code"),
        ("a ruled id alone", ("AHJ-5",), True, "code"),
        ("a tool-gap id alone", ("AHJ-6",), True, "code"),
        ("ruled and tool-gap together", ("AHJ-5 AHJ-6",), True, "code"),
        ("an alternative solution", ("AHJ-1",), True, "conditional"),
        ("a referral", ("AHJ-11",), True, "conditional"),
        ("approval-required beside ruled", ("AHJ-1 AHJ-5",), True,
         "conditional"),
        ("a shortened run, nothing cited", (), False, None),
        ("a shortened run WITH an alternative solution", ("AHJ-1",), False,
         None),
        ("a shortened run with a referral", ("AHJ-11",), False, None),
    )

    def _determination(self, citations, annual):
        from btap.audit import AuditLog
        from btap.codes.necb import path as necb_path

        class _Run:
            pass

        run = _Run()
        run.report = {"annual": annual, "code": "necb2020"}
        run.ruleset = type("_R", (), {"code": "necb2020"})()
        audit = AuditLog()
        for citation in citations:
            audit.warn("selection", "a choice was made", target="Z1",
                       article="8.4.4.9.(5)", ahj=citation)
        necb_path._resolve_ahj_conditions(run, audit)
        return run.report.get("compliance_determination")

    def test_the_matrix(self):
        for label, citations, annual, expected in self.CASES:
            with self.subTest(label, annual=annual):
                self.assertEqual(
                    expected, self._determination(citations, annual),
                    "{} on an annual={} run".format(label, annual))

    def test_a_shortened_run_still_records_the_CITATIONS(self):
        """They are provenance even where there is no verdict to qualify —
        losing them would hide that the question was reached at all."""
        from btap.audit import AuditLog
        from btap.codes.necb import path as necb_path

        class _Run:
            pass

        run = _Run()
        run.report = {"annual": False, "code": "necb2020"}
        run.ruleset = type("_R", (), {"code": "necb2020"})()
        audit = AuditLog()
        audit.warn("selection", "a choice", target="Z1", ahj="AHJ-1 AHJ-5")
        necb_path._resolve_ahj_conditions(run, audit)
        self.assertEqual(["AHJ-1", "AHJ-5"],
                         [e["id"] for e in run.report["ahj_applied"]])
        self.assertNotIn("compliance_determination", run.report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
