"""No determination when a required ground strip remains unrepresented.

Sol's 286 ruling, and the reason matters: the proposed building is EXEMPT from
3.2.3.3.(3)'s 1.2 m perimeter strip, because 3.4.1.2.(1) carries only Article
3.2.1.1 and Subsection 3.2.4 onto the performance path. So declining the
common ground method is not an omission on the proposed side.

What it costs is the REFERENCE. 8.4.1.1.(1) requires the building energy
target to account for Section 3.2's prescriptive requirements. A floor on the
simple `Ground` boundary has no slab edge on which to put the strip, and a
Kiva-mode floor that fails preparation reaches the same target state. No valid
target means 8.4.1.2.(2) has nothing to compare against, so the run makes NO
determination — not compliant, not non-compliant, and deliberately NOT
conditional, which would launder a known-invalid target into something that
looks approvable.

The ruling is applicability-narrow, which is what the second test pins: where
no strip needs representing, `simple` is an ordinary run.
"""

import tempfile
import unittest

from btap.codes import cli as codes_cli
from btap.codes import compliance
from tests.necb.support import needs_sdk, proposed_with_hvac, zone_types_for

STRIP_HDD = 3890      # Toronto — below full_area_min_hdd (7000)
FULL_AREA_HDD = 8000  # above it: 3.2.3.3.(4) full area, applied by construction


def _run(model, *, ground_model, hdd):
    with tempfile.TemporaryDirectory(prefix="ground-model-") as run_dir:
        return compliance.performance_compliance(
            model, code="necb2020", simulate="none", hdd=hdd,
            ground_model=ground_model,
            building={"storeys": 1, "zone_types": zone_types_for(model)},
            run_dir=run_dir)


def _unknown_massless_floors(model, names):
    import openstudio

    names = set(names)
    floors = [surface for surface in model.getSurfaces()
              if surface.nameString() in names]
    if {surface.nameString() for surface in floors} != names:
        raise AssertionError(f"fixture floors not found: {sorted(names)}")
    material = openstudio.model.MasslessOpaqueMaterial(model)
    material.setName("Unknown Kiva finish")
    material.setThermalResistance(0.2)
    construction = openstudio.model.Construction(model)
    construction.setName("Unsupported Kiva construction")
    construction.setLayers([material])
    for floor in floors:
        floor.setConstruction(construction)


@needs_sdk
class TestGroundModelSimpleMakesNoDetermination(unittest.TestCase):
    def test_simple_establishes_no_target_in_a_perimeter_strip_climate(self):
        result = _run(proposed_with_hvac(), ground_model="simple", hdd=STRIP_HDD)

        self.assertIsNone(result.compliant,
                          "a run with no valid target cannot be compliant OR "
                          "non-compliant")
        self.assertEqual("no_determination",
                         result.report.get("compliance_determination"))
        block = result.report.get("no_determination")
        self.assertIsNotNone(block, "the refusal must state itself in the report")
        self.assertEqual("building energy target not established",
                         block["reason"])
        self.assertEqual("8.4.1.1.(1)", block["article"])
        self.assertEqual("D-32", block["ruling"])
        self.assertIn("ground_strip_unrepresented",
                      block["detail"]["reason"])
        self.assertTrue(block["detail"]["floors"],
                        "the floors that caused it must be named")

    def test_it_is_NOT_a_conditional_result(self):
        """Conditional means an authority can approve it. An invalid target is
        not approvable, so the two must never be confused."""
        result = _run(proposed_with_hvac(), ground_model="simple", hdd=STRIP_HDD)

        self.assertEqual("no_determination",
                         result.report.get("compliance_determination"))
        self.assertNotEqual("conditional",
                            result.report.get("compliance_determination"))
        for key in ("conditions", "ahj_must_approve", "ahj_ids",
                    "if_not_approved"):
            self.assertNotIn(key, result.report,
                             f"{key} belongs to a conditional result, which "
                             f"this is not")

    def test_the_exit_code_is_no_determination_not_a_verdict(self):
        """`cli.verdict_exit` already maps compliant=None to 6, the code
        `--quick` and `--simulate sizing` use. This pins that the refusal
        travels through it rather than printing a pass or a fail."""
        result = _run(proposed_with_hvac(), ground_model="simple", hdd=STRIP_HDD)

        self.assertEqual(codes_cli.EXIT["no_determination"],
                         codes_cli.verdict_exit(result))
        self.assertNotEqual(codes_cli.EXIT["compliant"],
                            codes_cli.verdict_exit(result))
        self.assertNotEqual(codes_cli.EXIT["not_compliant"],
                            codes_cli.verdict_exit(result))


class TestTheRefusalIsRenderedHonestly(unittest.TestCase):
    """Every surface a human reads must give the REAL reason.

    All three said "no annual simulation" / "no annual run" for a run that
    simulated a full year, because each inferred the cause from
    `compliant is None` instead of reading the recorded reason. The real one
    lived only in `report.json` and nothing rendered it. Found by Fable on
    PR #133; no SDK needed, these are renderers.
    """

    REPORT = {
        "annual": True, "simulate": "annual",
        "compliance_determination": "no_determination",
        "compliant": None,
        "no_determination": {
            "reason": "building energy target not established",
            "article": "8.4.1.1.(1)",
            "ruling": "D-32",
            "what_would_fix_it": (
                "use kiva and resolve each listed floor's representation"),
        },
    }

    def _result(self):
        from types import SimpleNamespace

        return SimpleNamespace(compliant=None, report=self.REPORT)

    def test_the_one_line_determination_names_the_target(self):
        from btap.codes import cli

        line = cli.determination(self._result(), self.REPORT)
        self.assertIn("building energy target not established", line)
        self.assertNotIn("no annual simulation", line)

    def test_the_verdict_block_names_the_target_and_the_real_fix(self):
        from btap.codes import cli

        block = cli.verdict_block(self._result(), self.REPORT)
        self.assertIn("building energy target not established".capitalize(),
                      block)
        self.assertIn("8.4.1.1.(1)", block)
        self.assertIn("resolve each listed floor", block)
        self.assertIn("DIAGNOSTIC only", block)
        self.assertNotIn("Run with --simulate annual", block)

    def test_the_html_badge_names_the_target(self):
        """The report is the AHJ-facing artifact, so the badge beside the
        verdict is where a wrong reason does the most damage."""
        from btap.codes.report import sections

        html = str(sections.verdict_banner({"report": self.REPORT}))
        self.assertIn("building energy target not established", html)
        self.assertNotIn("no annual run", html)

    def test_the_html_badge_still_says_no_annual_run_when_that_is_why(self):
        """Control: the default survives for the case it describes."""
        from btap.codes.report import sections

        html = str(sections.verdict_banner(
            {"report": {"compliant": None, "simulate": "none"}}))
        self.assertIn("no annual run", html)

    def test_a_CONDITIONAL_building_does_not_ship_a_contradictory_appendix(self):
        """The AHJ appendix is the fourth surface, and the one that mattered.

        `"no_determination"` is a TRUTHY string, so the appendix's
        "no determination to be conditional on" branch — added for Fable's
        earlier finding, which guarded `--simulate none` — was walked straight
        past, and the row fell through to "YES — this run's determination is
        conditional on it". Meanwhile the badge beside it said UNDETERMINED.
        The report is the AHJ-facing artifact and it contradicted itself, for
        AHJ-1, AHJ-2 and AHJ-14, on any building that would have been
        conditional — four of the six frozen determinations.

        The sibling tests could not see this: their fixture is never
        conditional, so `conditional_ids` was always empty and the fall-through
        was unreachable. This one supplies the conditional state the others
        lack, which is the whole point of it.
        """
        from btap.codes.report import sections

        report = dict(self.REPORT)
        # Exactly what a conditional run writes, left in place beside the
        # refusal — the state the override now clears.
        report["compliance_determination_reason"] = {
            "ahj_ids": ["AHJ-1", "AHJ-2", "AHJ-14"],
            "condition": "approval by the authority having jurisdiction",
            "ahj_must_approve": ["AHJ-1: ...", "AHJ-2: ...", "AHJ-14: ..."],
        }
        # AHJ-1 is `alternative-solution` and AHJ-2 is `referral`, so both are
        # approval-required and reach the bearing branch. Entries that actually
        # CITE them are required or `fired` is empty and no row renders at all,
        # which would make this assertion vacuous.
        ctx = {"report": report,
               "audit_entries": [{"ahj": "AHJ-1"}, {"ahj": "AHJ-2"}]}
        html = str(sections.ahj_appendix(ctx))

        self.assertIn("AHJ-1", html, "the row must exist for its bearing to "
                                     "be worth asserting")
        self.assertNotIn("conditional on it", html,
                         "a run that established no target cannot be "
                         "conditional on anything")
        self.assertIn("reached no determination", html)

    def test_the_refusal_clears_a_REAL_conditional_reason_block(self):
        """Defence in depth, and the half that was unwitnessed.

        Asserting the absence of the block after an ordinary run proves
        nothing, because every available fixture is unconditional and the block
        was never written. So this builds one with the REAL `_set_conditional`
        and hands it to the refusal, which is the only way to see the clearing
        happen.
        """
        from btap.audit import AuditLog
        from btap.codes.necb import path as necb_path
        from tests.necb.support import real_conditional_report

        report = real_conditional_report(
            [{"id": "AHJ-1", "status": "alternative-solution",
              "title": "t", "article": "8.4.1.2.(2)", "target": "Boiler",
              "account": "a"}])
        self.assertIn("compliance_determination_reason", report,
                      "the fixture must START conditional or this test is "
                      "vacuous")

        class _Run:
            pass

        run = _Run()
        run.report = report
        run.audit = AuditLog()
        run.compliant = True
        necb_path._refuse_determination(run, {"reason": "x", "floors": ["F"]})

        self.assertIsNone(run.compliant)
        self.assertEqual("no_determination",
                         report["compliance_determination"])
        self.assertNotIn("compliance_determination_reason", report)
        self.assertIn("no_determination", report)

    def test_an_ordinary_unsized_run_still_says_no_annual_simulation(self):
        """The CONTROL: the old message is still right when it IS the reason,
        so the fix reads the report rather than replacing the default."""
        from types import SimpleNamespace

        from btap.codes import cli

        rep = {"annual": True, "simulate": "none", "compliant": None}
        line = cli.determination(SimpleNamespace(compliant=None, report=rep), rep)
        self.assertIn("no annual simulation", line)


class TestTheModeIsValidatedAtTheBoundary(unittest.TestCase):
    """Everything downstream asks `!= "kiva"`, so an unvalidated value makes a
    typo, a None or a capitalised "Kiva" silently select `simple` — and refuse
    to determine. A wrong mode is an argument error, not a verdict.

    The CLI cannot deliver a bad value (argparse `choices=` rejects it first),
    so the API is the only route that had the bug and the only route this
    pins. Fable flagged the validator as fixed-but-untested.
    """

    def test_the_two_modes_are_accepted(self):
        from btap.codes import pipeline

        for mode in ("kiva", "simple"):
            self.assertEqual(mode, pipeline._ground_model(mode))

    def test_anything_else_raises_rather_than_meaning_simple(self):
        from btap.codes import pipeline

        for bad in (None, "Kiva", "KIVA", "", "nonsense", 0, True):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError) as caught:
                    pipeline._ground_model(bad)
                self.assertIn("ground_model must be one of",
                              str(caught.exception))


@needs_sdk
class TestGroundModelSimpleStillRunsWhereNoStripApplies(unittest.TestCase):
    def test_simple_is_an_ordinary_run_in_a_full_area_climate(self):
        """At or above 7000 HDD the floor takes 3.2.3.3.(4)'s FULL-AREA value,
        applied as an ordinary construction change with no Kiva involved. The
        target is established either way, so `simple` must not refuse here —
        the ruling is applicability-narrow, not a global rejection.
        """
        result = _run(proposed_with_hvac(), ground_model="simple",
                      hdd=FULL_AREA_HDD)

        self.assertNotIn("no_determination", result.report)
        self.assertNotEqual("no_determination",
                            result.report.get("compliance_determination"))

    def test_kiva_establishes_a_target_in_the_same_strip_climate(self):
        """A confirmed zero-edge interior tile needs no strip and does not
        invalidate the four exposed floors that were prepared successfully."""
        result = _run(proposed_with_hvac(), ground_model="kiva", hdd=STRIP_HDD)

        self.assertNotIn("no_determination", result.report)
        self.assertNotEqual("no_determination",
                            result.report.get("compliance_determination"))
        self.assertTrue(any(
            entry.get("step") == "prepare"
            and "could NOT take a Kiva foundation" in entry.get("action", "")
            and entry.get("inputs", {}).get("floors") == 1
            for entry in result.audit.entries
        ), "the control must retain its one zero-perimeter refusal")

    def test_simple_leaves_the_proposed_model_untouched(self):
        """Declining the method must also decline the construction surgery."""
        model = proposed_with_hvac()
        floor = next(s for s in model.getSurfaces()
                     if s.surfaceType() == "Floor"
                     and s.outsideBoundaryCondition() == "Ground")
        name = floor.nameString()

        result = _run(model, ground_model="simple", hdd=STRIP_HDD)

        prepared = result.proposed_model.getSurfaceByName(name).get()
        self.assertEqual("Ground", prepared.outsideBoundaryCondition())
        self.assertFalse(prepared.adjacentFoundation().is_initialized())
        self.assertEqual(0, len(result.proposed_model.getFoundationKivas()))


@needs_sdk
class TestTheTargetDependsOnRepresentationNotTheMode(unittest.TestCase):
    def test_one_exposed_floor_refused_by_kiva_makes_no_determination(self):
        model = proposed_with_hvac()
        _unknown_massless_floors(model, ["Surface 7"])

        result = _run(model, ground_model="kiva", hdd=STRIP_HDD)

        self.assertIsNone(result.compliant)
        block = result.report.get("no_determination")
        self.assertIsNotNone(
            block, "an unrepresented required strip invalidates the target "
                   "even when other floors prepared successfully")
        self.assertEqual("ground_strip_unrepresented",
                         block["detail"]["reason"])
        self.assertEqual(["Surface 7"], block["detail"]["floors"])
        self.assertEqual("kiva", block["detail"]["ground_model"])

    def test_all_exposed_floors_refused_by_kiva_make_no_determination(self):
        model = proposed_with_hvac()
        _unknown_massless_floors(
            model, ["Surface 1", "Surface 7", "Surface 13", "Surface 19"])

        result = _run(model, ground_model="kiva", hdd=STRIP_HDD)

        self.assertIsNone(result.compliant)
        block = result.report.get("no_determination")
        self.assertIsNotNone(block)
        self.assertCountEqual(
            ["Surface 1", "Surface 7", "Surface 13", "Surface 19"],
            block["detail"]["floors"])
        self.assertTrue(all(
            surface["exposed_perimeter_m"] > 0
            for surface in block["detail"]["surfaces"]))

    def test_f_factor_floor_without_kiva_also_leaves_the_target_unestablished(self):
        model = proposed_with_hvac()
        floor = model.getSurfaceByName("Surface 7").get()
        self.assertTrue(
            floor.setOutsideBoundaryCondition("GroundFCfactorMethod"))

        result = _run(model, ground_model="kiva", hdd=STRIP_HDD)

        self.assertIsNone(result.compliant)
        block = result.report.get("no_determination")
        self.assertIsNotNone(block)
        self.assertEqual(["Surface 7"], block["detail"]["floors"])
        self.assertEqual(
            "GroundFCfactorMethod",
            block["detail"]["surfaces"][0]["boundary_condition"])


if __name__ == "__main__":
    unittest.main()
