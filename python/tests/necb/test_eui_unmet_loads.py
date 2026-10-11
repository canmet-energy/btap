"""8.4.1.2.(3) and (4)(a) on the archetype-EUI path — AHJ-21's closure.

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
import tempfile
import unittest
from unittest import mock

from btap.audit import AuditLog
from btap.codes.necb import path
from tests.necb.support import DDY, EPW, needs_engine, proposed_with_hvac


def report(heating_h, cooling_h, *, mechanical_cooling=True):
    """The shape `_eui_compliance` has after its annual run."""
    return {"proposed": {"unmet_occupied_hours": {"heating": heating_h,
                                                  "cooling": cooling_h},
                         "mechanical_cooling": mechanical_cooling},
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
        self.assertTrue(
            any(e["level"] == "warning" for e in audit.entries),
            "and the run must SAY it could not determine them")

    def test_the_criteria_are_AUDITED_against_their_own_sentences(self):
        audit = AuditLog()
        path.evaluate_unmet_8_4_4(report(10.0, 10.0), audit)
        articles = [e.get("article") for e in audit.entries]
        self.assertIn("8.4.1.2.(3)", articles)
        self.assertIn("8.4.1.2.(4)", articles)
        self.assertTrue(
            all(e.get("ruling") == "AHJ-21" for e in audit.entries
                if e.get("article", "").startswith("8.4.1.2")),
            "each entry cites the register id that recorded the gap")

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

    def test_the_criteria_reach_the_audit_on_a_real_run(self):
        result = self.run_eui()
        articles = [e.get("article") for e in result.audit.entries]
        for sentence in ("8.4.1.2.(3)", "8.4.1.2.(4)"):
            self.assertIn(
                sentence, articles,
                f"{sentence} must be determined on the EUI path, not skipped")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
