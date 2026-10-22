"""`--ground-model simple` makes no determination where the strip applies.

Sol's 286 ruling, and the reason matters: the proposed building is EXEMPT from
3.2.3.3.(3)'s 1.2 m perimeter strip, because 3.4.1.2.(1) carries only Article
3.2.1.1 and Subsection 3.2.4 onto the performance path. So declining the
common ground method is not an omission on the proposed side.

What it costs is the REFERENCE. 8.4.1.1.(1) requires the building energy
target to account for Section 3.2's prescriptive requirements, and a floor on
the simple `Ground` boundary has no slab edge on which to put the strip. No
valid target means 8.4.1.2.(2) has nothing to compare against, so the run makes
NO determination — not compliant, not non-compliant, and deliberately NOT
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
        self.assertIn("ground_model_simple_on_perimeter_strip",
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
        """The control for the first test: same model, same climate, default
        mode, and the refusal does not fire."""
        result = _run(proposed_with_hvac(), ground_model="kiva", hdd=STRIP_HDD)

        self.assertNotIn("no_determination", result.report)
        self.assertNotEqual("no_determination",
                            result.report.get("compliance_determination"))

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


if __name__ == "__main__":
    unittest.main()
