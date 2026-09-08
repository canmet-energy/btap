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
"""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

import btap.codes as codes
from btap.codes import compliance, pipeline
from btap.codes.necb import path as necb_path
from tests.necb.support import load_raw_fixture, needs_sdk, proposed_with_hvac, zone_types_for

#: The protocol's members, by the names the plan fixed.
HOOKS = ("validate", "climate", "prepare_annual", "consume_annual",
         "determine", "citations", "report_sections", "alternate_path")


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
