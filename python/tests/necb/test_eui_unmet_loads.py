"""8.4.1.2.(3) and (4)(a) on the archetype-EUI path — AHJ-21 NARROWED.

Not closed: sentence (5) remains a settled, implementable `tool-gap`, so the
register entry stays open and this is the narrowing Sol approved in `212`, not
its closure.

Until 2026-10-11 `path="eui"` reached an annual verdict with NO unmet-load
determination at all. `_eui_compliance` builds no reference model and never
called `_unmet_status`, `_iterate_capacities` or `evaluate_unmet`, so a model
could be declared COMPLIANT with any number of unmet thermal-block hours —
and sentence (4)(a) is the branch of (4) written FOR a building complying
under Subsection 8.4.4, i.e. for exactly the path that omitted it.

The class below exercises the criterion directly, which is NOT enough on its
own and must not be described as if it were: reverting the wiring in
`_eui_compliance` to `compliant = energy_ok` leaves every one of those tests
green, because they call `evaluate_unmet_8_4_4` rather than the path. The
defect was never in the arithmetic — it was that nothing called it — so
`TestTheVerdictActuallyComposesIt` below drives the real path and is the test
that would have caught the original gap.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from btap.audit import AuditLog
from btap.codes.necb import path
from tests.necb.support import (
    DDY,
    EPW,
    needs_engine,
    needs_sdk,
    proposed_with_hvac,
)

SAMPLES = Path(os.environ.get(
    "BTAP_SAMPLES_DIR",
    Path(__file__).resolve().parents[1] / "generated" / "samples"))


def sample(test, slug):
    """A corpus model, following `test_reference_rules.py`'s idiom — including
    its flag discipline, so a missing corpus fails rather than passing
    vacuously where the lane requires one."""
    path_ = SAMPLES / f"{slug}.osm"
    if not path_.exists():
        msg = (f"sample {slug} not generated: run python3 "
               "scripts/generate_samples.py tests/generated/samples "
               "(or set BTAP_SAMPLES_DIR)")
        if os.environ.get("BTAP_SAMPLES_REQUIRED") == "1":
            test.fail(msg)
        test.skipTest(msg)
    return str(path_)


def report(heating_h, cooling_h, *, mechanical_cooling=True, blocks=None,
           cooled=None, facility=None, unplaceable=None):
    """The shape `_eui_compliance` has after its annual run.

    One block by default, because (3) and (4)(a) are written per thermal
    block. `facility` sets the Facility union independently, so a test can
    prove the determination does NOT read it.
    """
    if blocks is None:
        blocks = {"THERMAL ZONE 1": {"heating": heating_h,
                                     "cooling": cooling_h}}
    if cooled is None:
        cooled = {name: mechanical_cooling for name in blocks}
    return {"proposed": {"zone_unmet_occupied_hours": blocks,
                         "zone_mechanical_cooling": cooled,
                         "mechanical_cooling": mechanical_cooling,
                         "unplaceable_cooling": unplaceable or [],
                         "unmet_occupied_hours": facility},
            "reference": {"method": "archetype EUI (Table 8.4.4.1)"}}


class TestTheEuiPathAppliesTheUnmetLoadCriteria(unittest.TestCase):

    def test_an_hour_over_either_limit_FAILS(self):
        """100 h is the limit in both sentences; 100.5 h is over it."""
        for kind, h, c in (("heating", 100.5, 10.0), ("cooling", 10.0, 100.5)):
            with self.subTest(over=kind):
                ok = path.evaluate_unmet_8_4_4(report(h, c), AuditLog())
                self.assertFalse(
                    ok, f"{kind} at {max(h, c)} h exceeds the 100 h limit, so "
                        "the EUI determination must not pass")

    def test_at_the_limit_it_PASSES(self):
        """The Code says "shall not exceed", so 100 h itself conforms."""
        self.assertTrue(
            path.evaluate_unmet_8_4_4(report(100.0, 100.0), AuditLog()),
            "exactly 100 h does not EXCEED 100 h")

    def test_the_cooling_limit_is_ABSOLUTE_not_a_reference_comparison(self):
        """(4)(a) against (4)(b) — the distinction this path turns on.

        On the 8.4.5 reference path the cooling test is +10% of the
        reference's hours, or this edition's floor, whichever is greater. Here
        there IS no reference, and 2025 supplies an absolute 100 h instead. If
        someone wires (4)(b)'s allowance in here it will admit far more than
        100 h whenever the (absent) reference logs many, so pin the constant.
        """
        self.assertEqual(100.0, path.COOLING_UNMET_LIMIT_H_8_4_4)
        self.assertFalse(
            path.evaluate_unmet_8_4_4(report(0.0, 101.0), AuditLog()),
            "101 h of unmet cooling fails (4)(a) outright, whatever a "
            "reference building would have logged")

    def test_no_mechanical_cooling_makes_sentence_4_VACUOUS(self):
        """A building with no cooling accrues passive-overheating hours.

        Those are not a cooling-capacity shortfall, and (4) is scoped to
        thermal blocks "for which mechanical cooling is provided". The
        reference path already reasons this way; this path must agree or an
        uncooled building fails on hours no cooling equipment could have met.
        """
        self.assertTrue(
            path.evaluate_unmet_8_4_4(
                report(0.0, 5000.0, mechanical_cooling=False), AuditLog()),
            "with no mechanical cooling the clause is vacuous, however many "
            "overheating hours the model logs")
        self.assertFalse(
            path.evaluate_unmet_8_4_4(
                report(0.0, 5000.0, mechanical_cooling=True), AuditLog()),
            "and WITH mechanical cooling the same hours must fail — if both "
            "pass, the vacuity branch is swallowing the criterion")

    def test_missing_hours_are_INDETERMINATE_not_a_pass(self):
        """A sizing-only or failed run has no unmet hours to judge."""
        audit = AuditLog()
        self.assertFalse(
            path.evaluate_unmet_8_4_4(report(None, None), audit),
            "absent unmet hours cannot satisfy a criterion")
        # The warning must say it could not DETERMINE them. Accepting any
        # warning let `indeterminate` be forced False and still pass, and the
        # mutated audit then said "unmet heating hours EXCEED 100 h" with
        # `proposed_h=None` — a confident verdict on a number it did not have
        # (Fable, `212`, M5).
        said = [e for e in audit.entries
                if e["level"] == "warning" and "UNAVAILABLE" in e["action"]]
        self.assertEqual(
            1, len(said),
            "exactly one warning must say the hours are UNAVAILABLE, not that "
            "a limit was exceeded — audit was:\n  "
            + "\n  ".join(f"[{e['level']}] {e['action'][:88]}"
                           for e in audit.entries))
        self.assertFalse(
            [e for e in audit.entries if "EXCEED" in e["action"]],
            "and nothing may claim a limit was exceeded on absent data")

    def test_the_criteria_are_AUDITED_against_their_own_sentences(self):
        audit = AuditLog()
        path.evaluate_unmet_8_4_4(report(10.0, 10.0), audit)
        articles = [e.get("article") for e in audit.entries]
        self.assertIn("8.4.1.2.(3)", articles)
        self.assertIn("8.4.1.2.(4)(a)", articles)
        # The `ahj` axis, not `ruling`: D-100 keeps three separate axes and
        # `ruling` is for an adjudicated D-XX decision, while a register
        # disposition belongs in `ahj`. I used `ruling` and
        # test_every_ruling_value_is_a_literal_on_the_audit_surface caught it.
        self.assertTrue(
            all(e.get("ahj") == "AHJ-21" for e in audit.entries
                if e.get("article", "").startswith("8.4.1.2")),
            "each entry cites the register id on the AHJ axis")

    def test_sentence_5_is_DECLARED_unimplemented_when_the_limits_fail(self):
        """(5) applies here — Sol's `191` — and is not implemented.

        It requires the capacities to be incrementally increased until the
        loads are met. Raising the capacities of the user's OWN design is a
        different act from raising a reference's and its mechanics are
        unadjudicated, so the verdict is NOT COMPLIANT rather than remediated.
        That has to be said out loud on every run it affects.
        """
        audit = AuditLog()
        self.assertFalse(path.evaluate_unmet_8_4_4(report(500.0, 0.0), audit))
        said = [e for e in audit.entries
                if e["level"] == "warning"
                and "8.4.1.2.(5)" in (e.get("article") or "")]
        self.assertEqual(
            1, len(said),
            "exactly one warning must name (5) as requiring an increase this "
            "path does not perform")

    def test_a_PASSING_run_does_not_warn_about_sentence_5(self):
        """The control: (5) is only reached where (3)/(4) are not met."""
        audit = AuditLog()
        self.assertTrue(path.evaluate_unmet_8_4_4(report(1.0, 1.0), audit))
        self.assertFalse(
            [e for e in audit.entries
             if "8.4.1.2.(5)" in (e.get("article") or "")],
            "(5) must not be mentioned when the limits are met")


@needs_engine
class TestTheCriteriaArePerThermalBlock(unittest.TestCase):
    """The scope of (3) and (4)(a), which the Facility row cannot stand in for.

    The first version of this change read `unmet_occupied_hours` — EnergyPlus's
    `Facility` row — for both sentences. Facility time is a UNION over blocks,
    so disjoint unmet periods sum past 100 h with no single block near it. Sol
    (`212`) gave that version a facility result of 150 h with two blocks at
    75 h each and it returned not-compliant on a building where every block
    conformed.
    """

    def test_a_facility_union_over_the_limit_with_every_block_under_it_PASSES(self):
        """Sol's probe, as a test. 150 h of facility time, no block over 75."""
        status = path._unmet_status_8_4_4(report(
            None, None,
            blocks={"ZONE 1": {"heating": 75.0, "cooling": 75.0},
                    "ZONE 2": {"heating": 75.0, "cooling": 75.0}},
            facility={"heating": 150.0, "cooling": 150.0}))
        self.assertTrue(
            status["all_ok"],
            "every block is within 100 h, so (3) and (4)(a) are met — a "
            "facility union of 150 h is not a block over the limit")

    def test_one_failing_block_FAILS_whatever_the_others_do(self):
        status = path._unmet_status_8_4_4(report(
            None, None,
            blocks={"GOOD": {"heating": 1.0, "cooling": 1.0},
                    "BAD": {"heating": 101.0, "cooling": 1.0}}))
        self.assertFalse(status["heating_ok"])
        self.assertEqual({"BAD": 101.0}, status["heating_failures"],
                         "and the audit must be able to NAME the block")

    def test_4a_does_not_reach_an_UNCOOLED_block(self):
        """Sol's second hostile control.

        (4) is scoped to "each thermal block ... for which mechanical cooling
        is provided". An uncooled block's passive-overheating hours are not a
        capacity shortfall, and a single building-wide flag made them one as
        soon as any other block was cooled.
        """
        status = path._unmet_status_8_4_4(report(
            None, None,
            blocks={"COOLED": {"heating": 10.0, "cooling": 50.0},
                    "PASSIVE": {"heating": 10.0, "cooling": 900.0}},
            cooled={"COOLED": True, "PASSIVE": False}))
        self.assertEqual(1, status["cooled_blocks"])
        self.assertTrue(
            status["all_ok"],
            "900 h of passive overheating in an UNCOOLED block is outside "
            "(4)(a) — the cooled block is within its limit")

    def test_but_a_genuinely_failing_COOLED_block_still_fails(self):
        """The control for the control: the exclusion above must not be a
        blanket pass once any block is uncooled."""
        status = path._unmet_status_8_4_4(report(
            None, None,
            blocks={"COOLED": {"heating": 10.0, "cooling": 150.0},
                    "PASSIVE": {"heating": 10.0, "cooling": 900.0}},
            cooled={"COOLED": True, "PASSIVE": False}))
        self.assertFalse(status["cooling_ok"])
        self.assertEqual({"COOLED": 150.0}, status["cooling_failures"])

    def test_a_cooled_building_with_NO_cooled_block_is_indeterminate(self):
        """Silence about applicability is not applicability.

        `08-vrf` reached a verdict with the audit line "within 100 h for every
        one of 0 mechanically cooled thermal block(s)" and `compliant: True`,
        because no block could be identified as cooled in a building the
        building-wide flag calls cooled. The resolution is fixed, and this is
        the guard that stops the next unresolvable equipment type passing
        (4)(a) over an empty set the same way (Fable, `214`).
        """
        status = path._unmet_status_8_4_4(report(
            None, None,
            blocks={"Z1": {"heating": 1.0, "cooling": 900.0}},
            cooled={"Z1": False}, mechanical_cooling=True,
            unplaceable=["Unplaceable Cooling Coil"]))
        self.assertFalse(status["cooling_known"])
        self.assertFalse(status["cooling_vacuous"])
        self.assertFalse(
            status["all_ok"],
            "a building with cooling whose applicability cannot be "
            "established must not PASS (4)(a) over zero blocks")
        # And (3) is STILL decided: 1.0 h is known and passes. A combined
        # flag reported both unknown and cited the wrong sentence (Sol,
        # `220`).
        self.assertTrue(status["heating_known"])
        self.assertTrue(status["heating_ok"])

    def test_a_COOLED_block_with_no_result_row_is_indeterminate(self):
        """The other direction of the same gap, one level earlier.

        The model says Z1 is cooled; EnergyPlus produced a row only for
        uncooled Z2. `cooled_blocks` was counted while iterating the ROWS, so
        Z1 was never seen: the count reached zero, the sentence went vacuous,
        and the run PASSED (Sol, `224`).

        The cooled set now comes from the applicability map, and the two maps
        are compared in both directions. Neither gap is vacuity — a row with
        no applicability entry has unknown applicability, and a cooled block
        with no row has no measurement.
        """
        status = path._unmet_status_8_4_4(report(
            None, None,
            blocks={"Z2": {"heating": 1.0, "cooling": 1.0}},
            cooled={"Z1": True, "Z2": False}, mechanical_cooling=True))
        self.assertEqual(
            1, status["cooled_blocks"],
            "the cooled count comes from the applicability map, so a block "
            "with no result row is still counted")
        self.assertEqual(["Z1"], status["unmeasured_cooled_blocks"])
        self.assertFalse(
            status["cooling_vacuous"],
            "a building with a cooled block is not one the sentence fails to "
            "reach")
        self.assertFalse(status["cooling_known"])
        self.assertFalse(
            status["all_ok"],
            "a cooled block with no measured hours cannot pass (4)(a)")

    def test_sentence_5_is_claimed_ONLY_when_a_limit_is_known_exceeded(self):
        """(5) applies to loads that are not met, not to missing evidence.

        Reaching it on `not all_ok` told a run whose heating was 1 h and
        whose cooling applicability was unresolved to increase capacities
        that nothing had shown to be short (Sol, `224`). The indeterminate
        verdict stands on its own.
        """
        from btap.audit import AuditLog

        unknown = report(
            None, None,
            blocks={"Z1": {"heating": 1.0, "cooling": 900.0}},
            cooled={"Z1": False}, mechanical_cooling=True,
            unplaceable=["Unplaceable Cooling Coil"])
        audit = AuditLog()
        self.assertFalse(path.evaluate_unmet_8_4_4(unknown, audit))
        self.assertNotIn(
            "8.4.1.2.(5)", [e["article"] for e in audit.entries],
            "nothing is known to be unmet here, so a required capacity "
            "increase has not been established")

        exceeded = report(
            None, None,
            blocks={"Z1": {"heating": 150.0, "cooling": 1.0}},
            cooled={"Z1": True})
        audit = AuditLog()
        self.assertFalse(path.evaluate_unmet_8_4_4(exceeded, audit))
        self.assertIn(
            "8.4.1.2.(5)", [e["article"] for e in audit.entries],
            "and a block genuinely over its limit must still carry the "
            "sentence-(5) disclosure — the gate narrowed, it did not close")

    def test_a_block_missing_from_the_cooling_map_is_indeterminate(self):
        """Not an uncooled block — a block whose applicability is unknown.

        Defaulting a missing entry to uncooled let 900 h of unmet cooling
        pass (Fable, `214`).
        """
        status = path._unmet_status_8_4_4(report(
            None, None,
            blocks={"Z1": {"heating": 1.0, "cooling": 900.0},
                    "Z2": {"heating": 1.0, "cooling": 1.0}},
            cooled={"Z2": True}, mechanical_cooling=True))
        self.assertEqual(["Z1"], status["unattributed_blocks"])
        self.assertFalse(status["cooling_known"])
        self.assertFalse(status["all_ok"])
        self.assertTrue(status["heating_known"],
                        "heating is readable here and must stay decided")

    def test_the_wholly_uncooled_fast_path_still_PASSES(self):
        """The control for both guards above: they must not turn an uncooled
        building into an indeterminate one. `01-baseboard-gas` is that
        building, and it is a frozen parity scenario."""
        status = path._unmet_status_8_4_4(report(
            None, None,
            blocks={"Z1": {"heating": 10.0, "cooling": 1422.0}},
            cooled={}, mechanical_cooling=False))
        self.assertTrue(status["cooling_vacuous"])
        self.assertTrue(status["cooling_known"])
        self.assertTrue(status["heating_known"])
        self.assertTrue(status["all_ok"])

    def test_absent_block_rows_are_INDETERMINATE_and_the_union_is_not_used(self):
        status = path._unmet_status_8_4_4(report(
            None, None, blocks={},
            facility={"heating": 1.0, "cooling": 1.0}))
        self.assertFalse(status["heating_known"])
        self.assertFalse(
            status["all_ok"],
            "a conforming FACILITY union must not be substituted for block "
            "rows that are absent")

    def test_per_block_cooling_applicability_comes_from_the_MODEL(self):
        """`_zone_mechanical_cooling` must agree with the building-wide flag on
        real models, and must not miss a coil held INSIDE zone equipment.

        Matching a zone's own equipment types reported a fully cooled PTAC
        building as having no cooled block at all — the direction that makes
        (4)(a) wrongly vacuous — because the zone carries the PTAC and the DX
        coil is its child.
        """
        import openstudio

        # The WHOLE corpus, because the two models a three-model sample left
        # out are where it broke. `08-vrf` came out 0 of 5 cooled with the
        # building-wide flag True — the 3.11 SDK resolves a VRF coil to
        # neither an air loop, nor a containing zone component, nor a
        # containing component — so (4)(a) was evaluated over ZERO blocks and
        # passed (Fable, `214`).
        expected_any = {"01-baseboard-gas": False, "06-unit-heaters-gas": False,
                        "07-furnace-forced-air": False,
                        "05-ptac-electric": True, "02-psz-gas-dx": True,
                        "03-vav-reheat-chiller": True,
                        "04-fancoil-chiller": True,
                        "08-vrf": True, "09-water-source-hp": True}
        for name, cooled_expected in expected_any.items():
            with self.subTest(model=name):
                loaded = openstudio.osversion.VersionTranslator().loadModel(
                    openstudio.toPath(sample(self, name)))
                self.assertTrue(loaded.is_initialized(), f"{name} must load")
                model = loaded.get()
                per_zone, unplaceable = path._zone_mechanical_cooling(model)
                self.assertEqual(
                    [], unplaceable,
                    f"{name}: every cooling object must be placeable; an "
                    "unplaceable one leaves (4)(a)'s applicability unknown")
                self.assertTrue(per_zone, "every thermal block gets an answer")
                self.assertEqual(
                    len(model.getThermalZones()), len(per_zone),
                    "one answer per thermal block, not per cooled block")
                self.assertEqual(
                    cooled_expected, any(per_zone.values()),
                    f"{name}: expected any-block-cooled {cooled_expected}")
                self.assertEqual(
                    path._mechanical_cooling(model), any(per_zone.values()),
                    f"{name}: per-block cooling must agree with the "
                    "building-wide flag about whether ANY block is cooled")
                if cooled_expected:
                    self.assertTrue(
                        all(per_zone.values()),
                        f"{name}: every block is served, so a coil held "
                        "INSIDE zone equipment must still be found — "
                        f"got {per_zone}")


@needs_sdk
class TestCoolingIsAttributedToTheRightBLOCKS(unittest.TestCase):
    """Configurations the nine-model corpus cannot see.

    Every one of these was found by review, not by the corpus, and the corpus
    is why: it has no unitary system on an air loop, no VRF terminal unit on
    one, and no air terminal carrying its own cooling coil. So the nine-model
    agreement check is necessary and nowhere near sufficient, and these
    models are built with the SDK instead (Fable, `223`).
    """

    @staticmethod
    def _blank(zones=2):
        import openstudio

        model = openstudio.model.Model()
        built = []
        for index in range(zones):
            zone = openstudio.model.ThermalZone(model)
            zone.setName(f"Z{index + 1}")
            built.append(zone)
        return model, built

    @staticmethod
    def _serve(model, loop, zones):
        import openstudio

        for zone in zones:
            terminal = (openstudio.model
                        .AirTerminalSingleDuctConstantVolumeNoReheat(
                            model, model.alwaysOnDiscreteSchedule()))
            loop.addBranchForZone(zone,
                                  terminal.to_StraightComponent().get())

    def test_a_unitary_system_ON_AN_AIR_LOOP_cools_its_loops_blocks(self):
        """The regression I introduced, and the one that cost most.

        `AirLoopHVACUnitarySystem` is a `ZoneHVACComponent` subclass, so
        `to_ZoneHVACComponent()` succeeds — but on an air loop its
        `thermalZone()` is EMPTY. Treating that as "placed with nothing
        attributed" reported no cooled block in a fully cooled building, so
        (4)(a) went vacuous and 500 h of unmet cooling per block PASSED. The
        product's own `modeling/hvac/psz.py` builds exactly this shape.
        """
        import openstudio

        model, zones = self._blank()
        loop = openstudio.model.AirLoopHVAC(model)
        unitary = openstudio.model.AirLoopHVACUnitarySystem(model)
        coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
        unitary.setCoolingCoil(coil.to_HVACComponent().get())
        unitary.addToNode(loop.supplyOutletNode())
        self._serve(model, loop, zones)

        per_block, unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual([], unplaceable)
        self.assertEqual(
            {"Z1": True, "Z2": True}, per_block,
            "every block the loop serves is cooled; reporting none of them "
            "makes (4)(a) vacuous over a fully cooled building")

    def test_a_VRF_terminal_unit_ON_AN_AIR_LOOP_does_too(self):
        """Same shape, different class — so the fix is not DX-specific."""
        import openstudio

        model, zones = self._blank()
        loop = openstudio.model.AirLoopHVAC(model)
        openstudio.model.AirConditionerVariableRefrigerantFlow(model)
        unit = openstudio.model.ZoneHVACTerminalUnitVariableRefrigerantFlow(
            model,
            openstudio.model.CoilCoolingDXVariableRefrigerantFlow(model),
            openstudio.model.CoilHeatingDXVariableRefrigerantFlow(model),
            openstudio.model.FanOnOff(model,
                                      model.alwaysOnDiscreteSchedule()))
        unit.addToNode(loop.supplyOutletNode())
        self._serve(model, loop, zones)

        per_block, unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual([], unplaceable)
        self.assertEqual({"Z1": True, "Z2": True}, per_block)

    def test_an_air_TERMINALS_own_coil_cools_only_ITS_block(self):
        """The over-attribution my reorder did not fix, and I said it had.

        An air terminal is not a `ZoneHVACComponent`, so narrowest-first
        ordering could not reach it: a four-pipe induction unit's chilled-
        water coil fell through to `airLoopHVAC()` and claimed every block on
        an otherwise heating-only loop. Terminals are placed through
        `thermalZone.airLoopHVACTerminal()`, the only direction the SDK
        offers (Fable, `223`).
        """
        import openstudio

        model, zones = self._blank(3)
        loop = openstudio.model.AirLoopHVAC(model)
        heat = openstudio.model.CoilHeatingElectric(
            model, model.alwaysOnDiscreteSchedule())
        heat.addToNode(loop.supplyOutletNode())

        plant = openstudio.model.PlantLoop(model)
        plant.setName("Chilled Water Loop")
        plant.addSupplyBranchForComponent(
            openstudio.model.ChillerElectricEIR(model))
        beam_cooling = openstudio.model.CoilCoolingWater(
            model, model.alwaysOnDiscreteSchedule())
        plant.addDemandBranchForComponent(beam_cooling)
        beam = (openstudio.model
                .AirTerminalSingleDuctConstantVolumeFourPipeInduction(
                    model, openstudio.model.CoilHeatingWater(
                        model, model.alwaysOnDiscreteSchedule())))
        beam.setCoolingCoil(beam_cooling)
        loop.addBranchForZone(zones[0], beam.to_StraightComponent().get())
        self._serve(model, loop, zones[1:])

        per_block, unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual([], unplaceable)
        self.assertEqual(
            {"Z1": True, "Z2": False, "Z3": False}, per_block,
            "only the block with the cooled terminal is inside (4)(a); the "
            "other two are heated-only and their passive hours are not a "
            "capacity shortfall")

    def test_a_DETACHED_coil_serves_no_block_and_is_not_unplaceable(self):
        """Detached is a KNOWN answer, not an unknown one.

        A `CoilCoolingDXSingleSpeed` connected to nothing provides cooling to
        no thermal block, so (4)(a)'s scope is known: this object is not in
        it. Reporting it unplaceable made the sentence's applicability
        unknown for a model whose only fault is a stray object, and failed a
        run the Code does not reach (Sol, `224`).

        It may deserve an input-model warning. That is a different concern
        from this one, and this test says nothing about it.
        """
        import openstudio

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        zone.setName("Z1")
        openstudio.model.CoilCoolingDXSingleSpeed(model).setName("ORPHAN")

        per_block, unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual(
            [], unplaceable,
            "a detached coil is connected to no topology at all, which is "
            "what distinguishes 'serves no block' from 'could not be "
            "attributed'")
        self.assertEqual({"Z1": False}, per_block)
        self.assertEqual({}, path.cooling_attribution_disagreement(model))

    def test_a_DOAS_cooling_coil_cools_every_block_its_loops_serve(self):
        """A dedicated outdoor-air system is shared between air loops.

        Its cooling coil answered `airLoopHVAC`,
        `containingZoneHVACComponent`, `containingHVACComponent` AND
        `plantLoop` all empty, so it came back unplaceable while genuinely
        cooling both blocks (Sol, `224`).

        Both directions had to learn it, and the invariant is how I know:
        teaching only the outward walk made the two halves disagree
        immediately, and my first attempt at the inward half looked for the
        DOAS in the loop's own OA system — which is not where it is. A loop
        reaches it through `airLoopHVACDedicatedOutdoorAirSystem()`.
        """
        import openstudio

        model = openstudio.model.Model()
        zones = []
        for index in (1, 2):
            zone = openstudio.model.ThermalZone(model)
            zone.setName(f"Z{index}")
            zones.append(zone)
        loops = []
        for index, zone in enumerate(zones, 1):
            loop = openstudio.model.AirLoopHVAC(model)
            loop.setName(f"AL{index}")
            terminal = (openstudio.model
                        .AirTerminalSingleDuctConstantVolumeNoReheat(
                            model, model.alwaysOnDiscreteSchedule()))
            loop.addBranchForZone(zone,
                                  terminal.to_StraightComponent().get())
            loops.append(loop)
        oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(
            model, openstudio.model.ControllerOutdoorAir(model))
        doas = openstudio.model.AirLoopHVACDedicatedOutdoorAirSystem(
            oa_system)
        for loop in loops:
            doas.addAirLoop(loop)
        coil = openstudio.model.CoilCoolingWater(
            model, model.alwaysOnDiscreteSchedule())
        coil.setName("DOAS COOLING COIL")
        coil.addToNode(oa_system.outboardOANode().get())

        per_block, unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual([], unplaceable)
        self.assertEqual(
            {"Z1": True, "Z2": True}, per_block,
            "the DOAS coil cools every block its air loops serve")
        self.assertEqual(
            {}, path.cooling_attribution_disagreement(model),
            "and both directions must reach it, or the invariant is "
            "reporting a bug in one of them")

    def test_a_CONNECTED_but_unresolvable_object_stays_indeterminate(self):
        """Sol's control for the two above.

        Relaxing 'unplaceable' must not relax it into silence. An object that
        IS connected to topology but cannot be attributed leaves (4)(a)'s
        scope unknown, and the determination must say so.
        """
        import openstudio

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        zone.setName("Z1")
        # A chilled-water coil on a plant loop that reaches no block: it is
        # connected, so it is not detached, and nothing attributes it.
        plant = openstudio.model.PlantLoop(model)
        plant.setName("Process Chilled Water")
        plant.addSupplyBranchForComponent(
            openstudio.model.ChillerElectricEIR(model))
        coil = openstudio.model.CoilCoolingWater(
            model, model.alwaysOnDiscreteSchedule())
        plant.addDemandBranchForComponent(coil)

        per_block, unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual(
            {"Z1": False}, per_block,
            "the plant reaches no thermal block")
        # Placed via the plant rung, so not unplaceable — and the status
        # function then decides vacuous, which the next test pins.
        self.assertEqual([], unplaceable)
        self.assertEqual({}, path.cooling_attribution_disagreement(model))

    def test_cooling_that_reaches_NO_block_is_vacuous_not_unknown(self):
        """A chiller serving only a process loop.

        Forcing this INDETERMINATE failed a building the Code does not
        reach: it has no thermal block "for which mechanical cooling is
        provided", so (4) is vacuous (Fable, `219`).
        """
        import openstudio

        model, _zones = self._blank()
        plant = openstudio.model.PlantLoop(model)
        plant.setName("Process Chilled Water")
        plant.addSupplyBranchForComponent(
            openstudio.model.ChillerElectricEIR(model))
        plant.addDemandBranchForComponent(
            openstudio.model.CoilCoolingWater(
                model, model.alwaysOnDiscreteSchedule()))

        per_block, unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual(
            [], unplaceable,
            "every object is PLACED — the plant simply reaches no block")
        self.assertEqual({"Z1": False, "Z2": False}, per_block)
        status = path._unmet_status_8_4_4(report(
            None, None,
            blocks={"Z1": {"heating": 1.0, "cooling": 900.0},
                    "Z2": {"heating": 1.0, "cooling": 900.0}},
            cooled=per_block, mechanical_cooling=True,
            unplaceable=unplaceable))
        self.assertTrue(status["cooling_vacuous"])
        self.assertTrue(status["all_ok"])


class TestTheVerdictActuallyComposesIt(unittest.TestCase):
    """The call site, not the helper.

    AHJ-21 was not a wrong calculation; it was a calculation nobody invoked.
    So the guard that matters is that the EUI verdict DEPENDS on the unmet
    criteria — and the only way to show dependence is to change the criterion
    and watch the verdict move. Patching `evaluate_unmet_8_4_4` does exactly
    that: with the wiring in place the verdict follows it, and with the wiring
    reverted to `compliant = energy_ok` the patch has no effect and this test
    fails. The direct tests above cannot distinguish those two states.
    """

    def run_eui(self):
        from btap.codes import performance_compliance

        return performance_compliance(
            proposed_with_hvac(), code="necb2025", path="eui",
            archetypes_map={"Office": "all"},
            weather={"epw": str(EPW), "ddy": str(DDY)},
            run_dir=tempfile.mkdtemp(prefix="osnecb-eui-unmet-"),
            run_period={"begin_month": 1, "begin_day": 1, "end_month": 1,
                        "end_day": 7})

    def test_the_verdict_follows_the_unmet_criteria(self):
        for verdict, expected in ((False, False), (True, None)):
            with self.subTest(criteria_return=verdict):
                with mock.patch.object(path, "evaluate_unmet_8_4_4",
                                       return_value=verdict) as spy:
                    result = self.run_eui()
                self.assertTrue(
                    spy.called,
                    "the EUI path must CALL the unmet-load criteria; if this "
                    "fails, 8.4.1.2.(3) and (4)(a) are unapplied again")
                if expected is False:
                    self.assertFalse(
                        result.compliant,
                        "failing unmet hours must make the EUI determination "
                        "NOT COMPLIANT, whatever the energy comparison says")

    def test_a_failing_ENERGY_comparison_still_dominates(self):
        """The converse operand, which the test above did not pin.

        `compliant = energy_ok and unmet_ok` has two operands and the test
        above only ever asserted the verdict when the unmet result was False.
        So `compliant = unmet_ok` — deleting the energy comparison outright —
        satisfied every assertion in it: Sol made exactly that one-line change
        and the engine-backed test stayed green (`212`, blocker 3).

        Here the unmet criteria PASS and the energy target is driven below the
        proposed consumption, so only `energy_ok` can carry the verdict.
        """
        from btap.codes.necb.editions.necb2025 import eui_archetypes

        real_target = eui_archetypes.eui_building_energy_target

        def impossible_target(*args, **kwargs):
            target = dict(real_target(*args, **kwargs))
            target["bet_kwh"] = 1.0        # no real building meets 1 kWh/year
            return target

        with mock.patch.object(path, "evaluate_unmet_8_4_4",
                               return_value=True) as spy:
            with mock.patch.object(eui_archetypes,
                                   "eui_building_energy_target",
                                   side_effect=impossible_target):
                result = self.run_eui()
        self.assertTrue(spy.called, "the unmet criteria are still consulted")
        self.assertFalse(
            result.compliant,
            "the unmet criteria PASSED and the energy target is 1 kWh, so an "
            "EUI verdict that is still COMPLIANT means the energy comparison "
            "no longer reaches it")

    def test_BOTH_operands_passing_is_what_makes_it_compliant(self):
        """The positive control for the two tests above: with both operands
        satisfied the verdict is COMPLIANT, so neither of them is proving its
        point by way of a run that could never pass."""
        with mock.patch.object(path, "evaluate_unmet_8_4_4",
                               return_value=True):
            result = self.run_eui()
        self.assertTrue(
            result.compliant,
            "unmet criteria passing and the real archetype target met must "
            "give a COMPLIANT determination — if this fails, the two "
            "dominance tests above are vacuous")

    def test_the_path_SETS_the_mechanical_cooling_flag(self):
        """(4)'s vacuity rule needs a flag this path does not inherit.

        `prepare_annual` sets `mechanical_cooling`, but it runs inside
        `pipeline._proposed_annual` — the REFERENCE flow. This path calls
        `compliance._run_annual` directly and rejoins the pipeline only at
        `_finalize`, so it has to set the flag itself.

        If it does not, the lookup returns None rather than False, the clause
        stops being vacuous, and a building with no mechanical cooling is
        judged on passive-overheating hours no cooling equipment could have
        met. Deleting that one line left all ten tests green before this one
        existed, which is why it is asserted on the REPORT and not on the
        helper's branch.
        """
        result = self.run_eui()
        self.assertIn(
            "mechanical_cooling", result.report["proposed"],
            "the EUI path must set this itself — it never runs "
            "`prepare_annual`, which is where the reference flow gets it")
        self.assertIsInstance(
            result.report["proposed"]["mechanical_cooling"], bool,
            "it must be a real boolean; None makes (4) non-vacuous for an "
            "uncooled building instead of vacuous")

    def test_the_path_SETS_the_PER_BLOCK_cooling_map(self):
        """The sibling of the flag above, and it needs its own assertion.

        Deleting the `zone_mechanical_cooling` line left all nineteen tests
        green: the engine fixture is an UNCOOLED building, so `(4)(a)` is
        vacuous through the building-wide fast path and the per-block map is
        never consulted on that model. A mutation that survives because the
        fixture cannot reach the code is not a passing test, so this asserts
        the map on the REPORT, where its absence shows regardless of what the
        fixture is cooled by.
        """
        result = self.run_eui()
        section = result.report["proposed"]
        self.assertIn(
            "zone_mechanical_cooling", section,
            "the EUI path must set the per-block cooling map; without it a "
            "MIXED cooled/uncooled building is INDETERMINATE at best and "
            "judged on an uncooled block's passive hours at worst")
        per_block = section["zone_mechanical_cooling"]
        self.assertIsInstance(per_block, dict)
        self.assertTrue(per_block, "one entry per thermal block, not empty")
        self.assertEqual(
            sorted(k.upper() for k in
                   (section.get("zone_unmet_occupied_hours") or {})),
            sorted(k.upper() for k in per_block),
            "the cooling map and the unmet-hours rows must cover the SAME "
            "blocks — (4)(a) joins them by name, so a key that appears in "
            "one and not the other silently drops a block from the sentence")
        for name, cooled in per_block.items():
            self.assertIsInstance(
                cooled, bool, f"{name}: a real boolean, not None")

    def test_the_criteria_reach_the_audit_on_a_real_run(self):
        result = self.run_eui()
        articles = [e.get("article") for e in result.audit.entries]
        for sentence in ("8.4.1.2.(3)", "8.4.1.2.(4)(a)"):
            self.assertIn(
                sentence, articles,
                f"{sentence} must be determined on the EUI path, not skipped")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
