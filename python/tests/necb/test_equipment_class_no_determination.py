"""D-108/AHJ-23: a reference COPIED from the proposed on an inference does not
support a determination.

Table 8.4.4.7.-A makes the residential reference identical to the proposed only
for a closed list of cooling equipment. Where the model carries no
equipment-class fact, the selector infers one from a bare DX coil. That prior is
sound far more often than not, and it is still not evidence about THIS
equipment — so a built-up DX residential system would have its reference copied
from itself, making the 8.4.1.2 comparison compare the proposed against itself.

Sol ruled (`327`, `329`) that disclosure does not establish the target. The run
still prepares both models and reports what it computed; the VERDICT is
withheld. This is NOT a conditional result and NOT a preflight refusal: the OSM
is valid, and no authority's approval would change the answer.
"""

import tempfile
import unittest

from btap.codes import compliance
from btap.modeling import build_system
from tests.necb.hvac_helpers import load_fixture, sorted_zones

#: Cold enough to take the ordinary perimeter branch without a ground defect.
HDD = 4000


def _residential(system):
    model = load_fixture()
    build_system(model, system, sorted_zones(model))
    return model


def _run(model):
    zone_types = {z.nameString(): 'Hotel/Motel' for z in model.getThermalZones()}
    with tempfile.TemporaryDirectory(prefix='equipment-class-') as run_dir:
        return compliance.performance_compliance(
            model, code='necb2020', simulate='none', hdd=HDD,
            building={'storeys': 1, 'zone_types': zone_types},
            run_dir=run_dir)


class TestTheInferredRouteWithholdsTheVerdict(unittest.TestCase):
    def setUp(self):
        self.result = _run(
            _residential('Shared furnace with DX cooling and no outdoor air'))

    def test_no_determination_is_reported_and_compliant_is_null(self):
        self.assertIsNone(self.result.compliant)
        self.assertEqual('no_determination',
                         self.result.report['compliance_determination'])

    def test_it_cites_the_right_ruling_and_NOT_the_ground_method_one(self):
        """The refusal mechanism is shared with D-32's ground case; the
        CITATION is not. Attributing this to D-32/8.4.1.1 would send a reader
        to an unrelated ruling (Sol, `329`)."""
        block = self.result.report['no_determination']
        self.assertEqual('D-108', block['ruling'])
        self.assertEqual('8.4.4.7.(1)', block['article'])
        self.assertEqual('AHJ-23', block['ahj'])
        self.assertIn('residential', block['reason'])
        self.assertIn('unitary', block['what_would_fix_it'],
                      'it says what would establish the class')

    def test_it_is_NOT_a_conditional_result(self):
        """AHJ-23 is a tool gap. No authority's approval changes the answer, so
        the conditional machinery must stay out of it."""
        self.assertNotIn('compliance_determination_reason', self.result.report)
        self.assertNotEqual('conditional',
                            self.result.report['compliance_determination'])

    def test_the_diagnostic_run_still_COMPLETED(self):
        """Withholding a verdict is not refusing to run — both models were
        prepared, which is what distinguishes this from preflight exit 3."""
        self.assertIsNotNone(self.result.proposed_model)
        self.assertIsNotNone(self.result.reference_model)


class TestObservedEquipmentStillGetsAVerdict(unittest.TestCase):
    """The divergent control. Same `copy_proposed` action, observed basis.

    Without this, the test above would pass equally if the refusal fired for
    EVERY residential block, which would refuse most ordinary submissions.
    """

    def test_a_PTAC_block_is_not_refused(self):
        result = _run(_residential('PSZ MAU Hot Water with water-heated PTAC'))
        self.assertNotIn('no_determination', result.report)
        self.assertNotEqual(
            'no_determination',
            result.report.get('compliance_determination'),
            'packaged-terminal units are named in Table 8.4.4.7.-A, so the '
            'class is observed and the determination stands')


if __name__ == '__main__':
    unittest.main()


class TestTheRefusalCLEARSABooleanVerdict(unittest.TestCase):
    """The witness the integration test above cannot be.

    Those tests run `simulate='none'`, where `compliant` is ALREADY None and
    the CLI already exits 6 — so they prove the reason block is present, not
    that a verdict gets cleared. Sol called that vacuous (`331`) and he is
    right: the assertion passes whether or not the refusal does anything.

    This starts from `compliant=True` with a conditional determination already
    set, which is the state an annual run reaches, and proves the refusal
    overrides it.
    """

    @staticmethod
    def _run_with_a_verdict():
        from types import SimpleNamespace

        from btap.audit import AuditLog
        return SimpleNamespace(
            compliant=True,
            report={"proposed": {"total_site_kwh": 120.0},
                    "reference": {"total_site_kwh": 100.0},
                    "compliance_determination": "conditional",
                    "compliance_determination_reason": {"ahj_ids": ["AHJ-1"]}},
            audit=AuditLog())

    def test_a_TRUE_verdict_becomes_null_and_the_energies_survive(self):
        from btap.codes.necb import path as necb_path

        run = self._run_with_a_verdict()
        necb_path._refuse_determination(
            run, {"equipment_class_not_established": {
                "reason": "equipment_class_not_established",
                "blocks": ["Zone 1"], "action": "copy_proposed"}},
            "necb2020")

        self.assertIsNone(run.compliant, 'the boolean verdict is CLEARED')
        self.assertEqual("no_determination",
                         run.report["compliance_determination"])
        self.assertNotIn("compliance_determination_reason", run.report,
                         'a target never established cannot be conditional')
        self.assertEqual(120.0, run.report["proposed"]["total_site_kwh"])
        self.assertEqual(100.0, run.report["reference"]["total_site_kwh"])

        # The exit code, which Sol asked for in `331` and I left out: a null
        # verdict has to reach the SHELL as 6, not merely be null in the report.
        from btap.codes import cli
        self.assertEqual(6, cli.verdict_exit(run),
                         'a withheld determination exits 6')

    def test_necb2025_cites_its_OWN_article_and_table(self):
        """The same requirement is 8.4.4.7.(1) in 2020 and 8.4.5.7.(1) in 2025.
        A hardcoded citation is wrong for every edition but the one it was
        written against (Sol, `331`)."""
        from btap.codes.necb import path as necb_path

        expected = {"necb2020": ("8.4.4.7.(1)", "Table 8.4.4.7.-A"),
                    "necb2025": ("8.4.5.7.(1)", "Table 8.4.5.7.-A")}
        for code, (article, table) in expected.items():
            with self.subTest(code=code):
                run = self._run_with_a_verdict()
                necb_path._refuse_determination(
                    run, {"equipment_class_not_established": {
                        "reason": "equipment_class_not_established",
                        "blocks": ["Zone 1"], "action": "copy_proposed"}},
                    code)
                block = run.report["no_determination"]
                self.assertEqual(article, block["article"])
                self.assertIn(table, block["what_would_fix_it"])
                self.assertIn(table, run.audit.entries[-1]["action"])
                self.assertEqual(article, run.audit.entries[-1]["article"])


class TestTwoCausesAreBOTHReported(unittest.TestCase):
    """A model can fail to establish its target in more than one way.

    Both sites used to assign the same scalar key and `build_reference` runs
    after `prepare_model`, so the ground-method cause was silently replaced:
    the report cited only D-108, the fix text named only the equipment class,
    and a submitter who fixed that re-ran into a refusal nobody mentioned.
    Found independently by Sol (`331`) and Fable, who witnessed the repro.
    """

    def test_both_causes_appear_with_their_own_citations_and_warnings(self):
        from types import SimpleNamespace

        from btap.audit import AuditLog
        from btap.codes.necb import path as necb_path

        run = SimpleNamespace(compliant=True, report={}, audit=AuditLog())
        necb_path._refuse_determination(
            run,
            {"ground_method_not_supported": {
                "reason": "ground_method_not_supported",
                "ground_model": "kiva", "floors": ["Floor 1"]},
             "equipment_class_not_established": {
                 "reason": "equipment_class_not_established",
                 "blocks": ["Zone 1"], "action": "copy_proposed"}},
            "necb2020")

        causes = run.report["no_determination"]["causes"]
        self.assertEqual(2, len(causes), 'neither cause is dropped')
        self.assertEqual({"D-32", "D-108"}, {c["ruling"] for c in causes})
        self.assertEqual({"8.4.1.1.(1)", "8.4.4.7.(1)"},
                         {c["article"] for c in causes})

        fixes = " ".join(c["what_would_fix_it"] for c in causes)
        self.assertIn("foundation method", fixes)
        self.assertIn("equipment", fixes,
                      'the submitter is told about BOTH, not just one')

        warnings = [w for w in run.audit.warnings
                    if "NO DETERMINATION" in str(w.get("action"))]
        self.assertEqual(2, len(warnings), 'one warning per cause')
        self.assertEqual({"D-32", "D-108"},
                         {w.get("ruling") for w in warnings})

    def test_recording_TWO_DIFFERENT_causes_keeps_BOTH(self):
        """The accumulator's actual job, and the one its first test missed.

        That test recorded the SAME reason twice and asserted one entry — which
        a last-writer-wins assignment satisfies just as well, so reverting
        `record_target_not_established` to the overwrite it replaced left the
        whole module GREEN (Fable, third review of PR #153). The defect both
        reviewers found was two DIFFERENT causes, and nothing exercised that.
        """
        from types import SimpleNamespace

        from btap.codes.necb import path as necb_path

        run = SimpleNamespace(state={})
        necb_path.record_target_not_established(
            run, {"reason": "ground_method_not_supported",
                  "ground_model": "kiva", "floors": ["Floor 1"]})
        necb_path.record_target_not_established(
            run, {"reason": "equipment_class_not_established",
                  "blocks": ["Zone 1"], "action": "copy_proposed"})

        causes = run.state["target_not_established"]
        self.assertEqual(
            {"ground_method_not_supported", "equipment_class_not_established"},
            set(causes),
            'the SECOND cause must not replace the first — that replacement is '
            'the defect this function exists to prevent')
        self.assertEqual(["Floor 1"],
                         causes["ground_method_not_supported"]["floors"],
                         'and the first cause keeps its own detail intact')

    def test_recording_the_same_cause_twice_does_not_duplicate_it(self):
        """Kept as the dedupe contract, but it cannot stand alone: an overwrite
        passes it too, which is exactly how the gap above went unnoticed."""
        from types import SimpleNamespace

        from btap.codes.necb import path as necb_path

        run = SimpleNamespace(state={})
        for _ in range(2):
            necb_path.record_target_not_established(
                run, {"reason": "equipment_class_not_established",
                      "blocks": ["Zone 1"], "action": "copy_proposed"})
        self.assertEqual(1, len(run.state["target_not_established"]))


class TestTheTERMINALNamesEveryCause(unittest.TestCase):
    """`report.json` and the audit carried both causes; the terminal did not.

    `verdict_block` printed `causes[0]`, and the causes sort alphabetically, so
    `equipment_class_not_established` came first and the ground-method cause was
    the invisible one — the exact ambush the accumulation exists to prevent, at
    the surface a submitter actually reads (Fable, third review of PR #153).
    """

    @staticmethod
    def _block(*causes):
        return {"no_determination": {
            "reason": causes[0]["reason"], "article": causes[0]["article"],
            "what_would_fix_it": causes[0]["what_would_fix_it"],
            "causes": list(causes)}}

    GROUND = {"reason": "building energy target not established",
              "article": "8.4.1.1.(1)",
              "what_would_fix_it": "a validated NECB reference applier"}
    EQUIP = {"reason": "reference system not established for a residential block",
             "article": "8.4.4.7.(1)",
             "what_would_fix_it": "declare the cooling equipment's class"}

    def test_both_reasons_and_both_fixes_reach_the_terminal(self):
        from types import SimpleNamespace

        from btap.codes import cli

        rep = self._block(self.EQUIP, self.GROUND)
        text = cli.verdict_block(SimpleNamespace(compliant=None), rep)

        for cause in (self.EQUIP, self.GROUND):
            self.assertIn(cause["article"], text)
            self.assertIn(cause["what_would_fix_it"], text)
        self.assertIn("NO DETERMINATION", text)

    def test_a_report_with_NO_causes_key_still_prints(self):
        """Backward compatibility: a report written before `causes` existed has
        only the top-level block, and must not lose its one cause."""
        from types import SimpleNamespace

        from btap.codes import cli

        rep = {"no_determination": dict(self.GROUND)}
        text = cli.verdict_block(SimpleNamespace(compliant=None), rep)
        self.assertIn("8.4.1.1.(1)", text)
        self.assertIn(self.GROUND["what_would_fix_it"], text)
