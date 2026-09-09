"""Stage 9a (docs/NECB_MULTI_EDITION_PLAN.md, "Stage 9 — independent code
families"): the determination lifecycle is code-family-NEUTRAL, and NECB is
one implementation of it behind ``CodePath``.

Two properties are worth a permanent gate:

* **the boundary** — every registered edition names a ``path`` module in its
  manifest, the registry resolves it the way it resolves ``behaviours``, and
  the neutral pipeline imports no code family (import-linter enforces the
  same thing over the whole graph; the AST check here fails with the offending
  line rather than a contract report).
* **the evidence** — ``compliance._build_reference``, ``._evaluate`` and
  ``._evaluate_unmet`` are the symbols the article-coverage pointers name
  (``necb_rules.json``, ``reference_rules.json``). After Stage 9a they are
  FORWARDING functions, and a forwarder that resolves the pointer without
  ever running would make the evidence technically valid and substantively
  false. These tests prove each one is on the executed call path.

Stage 9a's scope was CORRECTED afterwards (see the plan's "9a scope,
corrected" entry): 9a is an NECB-PRESERVING scaffold. Two properties more are
therefore gated here — the two NECB sentences that moved OFF the neutral
pipeline onto the family, and the inventory of NECB Section 8.4 article paths
still hardcoded in the shared renderer, which 9b/9c must neutralize.
"""

from __future__ import annotations

import ast
import re
import tempfile
import unittest
from pathlib import Path

import btap.codes as codes
from btap.codes import compliance, pipeline
from btap.codes.necb import path as necb_path
from btap.codes.report import sections
from tests.necb.support import load_raw_fixture, needs_sdk, proposed_with_hvac, zone_types_for

#: The protocol's members, by the names the plan fixed, plus ``abort`` — the
#: failure-flush hook the scope correction added so the pipeline stops naming
#: NECB's 8.4.2.1 in its own voice.
HOOKS = ("validate", "climate", "prepare_annual", "consume_annual",
         "determine", "citations", "report_sections", "abort",
         "alternate_path")


class TestCodePathBinding(unittest.TestCase):
    def test_every_edition_names_a_code_path_that_resolves(self):
        for code_id in codes.code_ids():
            with self.subTest(code_id=code_id):
                ruleset = codes.resolve(code_id)
                self.assertTrue(ruleset.code_path,
                                f"{code_id}: manifest declares no 'path'")
                module = ruleset.path()
                self.assertEqual(ruleset.code_path, module.__name__)
                missing = [hook for hook in HOOKS if not callable(getattr(module, hook, None))]
                self.assertEqual([], missing, f"{code_id}: missing hooks {missing}")

    def test_the_same_module_object_comes_back(self):
        """Resolution is cached, like the behaviour modules: a determination
        asks for the path on every phase."""
        ruleset = codes.resolve("necb2020")
        self.assertIs(ruleset.path(), ruleset.path())

    def test_an_edition_without_a_path_raises_naming_the_manifest(self):
        bare = codes.Ruleset(id="necb2020", family="necb", edition="2020",
                             label="NECB 2020")
        with self.assertRaises(ValueError) as ctx:
            bare.path()
        message = str(ctx.exception)
        self.assertIn("necb2020", message)
        self.assertIn("manifest.json", message)

    def test_the_neutral_pipeline_imports_no_code_family(self):
        """Import-linter says the same thing over the whole graph; this names
        the line, and covers a family reached by a string that grimp would
        not see."""
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "btap.codes.necb"):
                offenders.append(f"{node.lineno}: from {node.module} import ...")
            if isinstance(node, ast.Import):
                offenders.extend(f"{node.lineno}: import {alias.name}"
                                 for alias in node.names
                                 if alias.name.startswith("btap.codes.necb"))
        self.assertEqual([], offenders, f"btap/codes/pipeline.py: {offenders}")


class TestForwardingFunctionsAreExecuted(unittest.TestCase):
    """The three evidence-bearing symbols that moved must still RUN."""

    def test_evaluate_forwards_to_the_family(self):
        calls = []
        ruleset = codes.resolve("necb2020")
        original = necb_path.evaluate
        necb_path.evaluate = lambda *a: calls.append(a) or "verdict"
        try:
            self.assertEqual("verdict",
                             compliance._evaluate({}, ruleset, None, "audit"))
        finally:
            necb_path.evaluate = original
        self.assertEqual([({}, ruleset, None, "audit")], calls)

    def test_evaluate_unmet_forwards_to_the_family(self):
        calls = []
        ruleset = codes.resolve("necb2020")
        original = necb_path.evaluate_unmet
        necb_path.evaluate_unmet = lambda *a: calls.append(a) or "unmet"
        try:
            self.assertEqual("unmet",
                             compliance._evaluate_unmet({}, ruleset, "audit"))
        finally:
            necb_path.evaluate_unmet = original
        self.assertEqual([({}, ruleset, "audit")], calls)

    def test_the_determination_calls_the_evaluate_forwarder(self):
        """Not the family function directly — the source is the contract."""
        source = Path(necb_path.__file__).read_text(encoding="utf-8")
        self.assertIn("compliance._evaluate(", source)
        self.assertIn("compliance._evaluate_unmet(", source)
        self.assertIn("compliance._build_reference(run)", source)
        self.assertIn("compliance._run_annual(", source)

    @needs_sdk
    def test_build_reference_forwarder_runs_in_a_real_determination(self):
        seen = []
        original = compliance._build_reference

        def counted(run):
            seen.append(run.ruleset.id)
            return original(run)

        compliance._build_reference = counted
        try:
            result = compliance.performance_compliance(
                proposed_with_hvac(), code="necb2020", simulate="none",
                hdd=3890,
                building={"storeys": 1,
                          "zone_types": zone_types_for(load_raw_fixture()),
                          "winter_design_temp_c": -20},
                run_dir=tempfile.mkdtemp(prefix="stage9a-forward-"))
        finally:
            compliance._build_reference = original
        self.assertEqual(["necb2020"], seen,
                         "compliance._build_reference must be ON the executed "
                         "call path, not a stub that resolves the pointer")
        self.assertIsNotNone(result.reference_model)


class TestRenderHooks(unittest.TestCase):
    def test_citations_are_the_editions_article_map(self):
        for code_id in codes.code_ids():
            ruleset = codes.resolve(code_id)
            self.assertEqual(dict(ruleset.articles),
                             ruleset.path().citations(ruleset))

    def test_report_sections_list_what_the_run_produced(self):
        run = pipeline._Run(report={"proposed": {"total_site_kwh": 1.0},
                                    "reference": {}, "tier": "Tier 1"})
        self.assertEqual(["proposed", "tier"], necb_path.report_sections(run))

    def test_report_sections_of_an_empty_run(self):
        self.assertEqual([], necb_path.report_sections(pipeline._Run(report={})))


class TestTheFamilySpeaksForTheCode(unittest.TestCase):
    """The two NECB sentences the neutral pipeline used to speak itself.

    Both moved to ``btap.codes.necb.path`` with their text, article, level,
    inputs and ORDER unchanged (verified against a captured audit trail: the
    unsized warning stays index 3 of a ``simulate="none"`` run, the abort
    stays the last entry of a flushed failure). These tests keep them on the
    family side — a second family must not inherit NECB's citations."""

    #: audit-surface call names, matching the decisions registry's walker.
    AUDIT_CALLS = {"warn", "warning", "info", "decision"}

    def test_the_pipeline_cites_no_code_article_on_any_audit_surface(self):
        """The narrow, load-bearing property: nothing the NEUTRAL pipeline
        writes into an audit trail names a NECB article or section. (Prose
        about NECB in a comment is documentation, not an emission; the
        PreflightError texts in ``_validate_input_model`` still name 8.4.4.7
        and 8.4.1.2 and are recorded as deferred to 9b/9c.)"""
        tree = ast.parse(Path(pipeline.__file__).read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in self.AUDIT_CALLS):
                continue
            literals = [value.value for value in
                        [*node.args, *(k.value for k in node.keywords)]
                        if isinstance(value, ast.Constant)
                        and isinstance(value.value, str)]
            if any(re.search(r"\b[58]\.\d+\.\d+", text) for text in literals):
                offenders.append(f"line {node.lineno}: {node.func.attr}()")
            if any(keyword.arg == "article" for keyword in node.keywords):
                offenders.append(f"line {node.lineno}: article=")
        self.assertEqual(
            [], offenders,
            "btap/codes/pipeline.py is code-family-neutral: an audit entry "
            "that cites a code article belongs to the family's CodePath — "
            f"{offenders}")

    def test_the_unsized_warning_is_the_familys(self):
        self.assertIn("5.2.10.1 energy-recovery determination needs",
                      Path(necb_path.__file__).read_text(encoding="utf-8"))

    def test_the_abort_hook_carries_the_necb_citation(self):
        class Recorder:
            def __init__(self):
                self.calls = []

            def warn(self, step, action, **keywords):
                self.calls.append((step, action, keywords))

        audit = Recorder()
        necb_path.abort(audit, ValueError("weather['ddy'] is required"))
        self.assertEqual(1, len(audit.calls))
        step, action, keywords = audit.calls[0]
        self.assertEqual("compliance", step)
        self.assertEqual(
            "run ABORTED before completion: ValueError: weather['ddy'] is "
            "required", action)
        self.assertEqual("8.4.2.1.", keywords["article"])
        self.assertEqual({"error_class": "ValueError"}, keywords["inputs"])

    def test_the_failure_flush_delegates_to_the_family(self):
        """Ordering is the pipeline's: the abort is the LAST entry written."""
        events = []

        class Path_:
            def abort(self, audit, error):
                events.append(("abort", type(error).__name__))

        original = pipeline._write_outputs
        pipeline._write_outputs = lambda *a: events.append(("write", ))
        try:
            pipeline._flush_on_failure("/nonexistent", {}, None,
                                       ValueError("boom"), Path_())
        finally:
            pipeline._write_outputs = original
        self.assertEqual([("abort", "ValueError"), ("write", )], events)


class TestDeferredRendererInventory(unittest.TestCase):
    """9a delivered an NECB-PRESERVING scaffold: the shared HTML renderer
    still writes NECB Section 8.4 article paths as literals, and neutralizing
    them is deferred to 9b/9c, where a second family makes the neutral shape
    testable rather than speculative.

    This pins the inventory so a later edit to ``report/sections.py`` is
    DELIBERATE — a new hardcoded citation fails here, and so does a removal
    that has not been recorded as 9b/9c progress."""

    #: ``{function: lines mentioning an 8.4.x article path}`` in
    #: ``btap/codes/report/sections.py`` at the 9a scope correction.
    DEFERRED_8_4_SITES = {
        "verdict_banner": 6,
        "path_declaration": 2,
        "energy": 3,
        "hvac_building_block": 2,
    }

    @staticmethod
    def _sites_by_function():
        source = Path(sections.__file__).read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source)
        tops = sorted(
            (node.lineno, node.name) for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)))
        counts = {}
        for number, line in enumerate(lines, 1):
            if "8.4" not in line:
                continue
            owner = None
            for start, name in tops:
                if start <= number:
                    owner = name
                else:
                    break
            counts[owner] = counts.get(owner, 0) + 1
        return counts

    def test_the_hardcoded_8_4_inventory_is_unchanged(self):
        self.assertEqual(self.DEFERRED_8_4_SITES, self._sites_by_function())

    def test_thirteen_sites_remain_for_9b_9c(self):
        self.assertEqual(13, sum(self.DEFERRED_8_4_SITES.values()))

    def test_the_render_hooks_have_no_product_call_site_yet(self):
        """``citations`` and ``report_sections`` are declared and tested but
        NOT wired: the renderer takes a report dict, not a run or a ruleset,
        so wiring either today would add or move a report leaf. Recorded as
        deferred rather than claimed as delivered."""
        product = sorted(Path(sections.__file__).parents[2].rglob("*.py"))
        self.assertIn(Path(pipeline.__file__), product,
                      "product source glob went stale")
        callers = [f"{p}:{n}" for p in product
                   for n, line in enumerate(
                       p.read_text(encoding="utf-8").splitlines(), 1)
                   if re.search(r"\.(citations|report_sections)\(", line)]
        self.assertEqual(
            [], callers,
            "a product call site appeared for a hook the plan records as "
            f"deferred to 9b/9c — update the narrowed claim: {callers}")


class TestAlternatePath(unittest.TestCase):
    def test_an_unknown_path_name_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            necb_path.alternate_path(
                None, "step-code", ruleset=codes.resolve("necb2025"),
                weather={}, hdd=None, run_dir=".", simulate="none",
                run_period=None, archetypes_map=None, process_loads_kwh=0.0,
                costing=False, city=None, province_state=None, costs_csv=None,
                necb_loads=None, report_html=False, report_options={},
                audit=None)
        self.assertIn("step-code", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
