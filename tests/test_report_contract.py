"""report.json's public fields are declared, and the real pipeline output obeys them.

``btap/codes/data/report_contract.json`` ships in the wheel and names the
fields a user may depend on. The frozen scenarios already catch an ACCIDENTAL
change to report.json, but a deliberate re-freeze accepts any change, and has
no notion of which fields are a promise. This test is what makes removing or
renaming a public field a decision rather than a side effect: it holds every
frozen report.json — real output of the real pipeline — to the contract, so a
re-freeze that drops a promised field still fails here.

Adding a field is deliberately NOT a break: reports may carry more than the
contract lists.

The corpus alone cannot prove the contract's value lists are complete — its
annual scenarios run shortened weeks, so the unqualified
``compliance_determination: "code"`` never appears in it. Those lists are
therefore also held to the SOURCE: every value the code can assign, and every
``--simulate`` choice the CLI accepts.

SDK-free: it reads JSON and source text, and imports nothing that loads
OpenStudio.
"""

from __future__ import annotations

import ast
import copy
import json
import re
import unittest
from importlib.resources import files
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "btap"
BASELINES = REPO_ROOT / "verification" / "scenarios" / "baselines"

_TYPES = {"string": str, "boolean": bool, "object": dict, "array": list, "null": type(None)}


def contract() -> dict:
    """The contract AS SHIPPED: read through the package, not the source path."""
    return json.loads(files("btap.codes").joinpath("data/report_contract.json")
                      .read_text(encoding="utf-8"))


def _type_ok(value, spec) -> bool:
    kinds = spec if isinstance(spec, list) else [spec]
    for kind in kinds:
        if kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if kind in _TYPES and isinstance(value, _TYPES[kind]):
            return True
    return False


def _field_problems(name, value, rule) -> list[str]:
    if "enum" in rule and value not in rule["enum"]:
        return [f"{name}={value!r} is not one of {rule['enum']}"]
    if "type" in rule and not _type_ok(value, rule["type"]):
        return [f"{name} has type {type(value).__name__}, contract says {rule['type']}"]
    if rule.get("items") and isinstance(value, list):
        return [f"{name}[{i}] is not {rule['items']}"
                for i, item in enumerate(value) if not _type_ok(item, rule["items"])]
    return []


def problems(report: dict, spec: dict) -> list[str]:
    """Every way a completed run's report breaks the contract."""
    found = []
    for name, rule in spec["always"].items():
        if name not in report:
            found.append(f"missing always-present field {name!r}")
        else:
            found += _field_problems(name, report[name], rule)
    for name, rule in spec["when_present"].items():
        if name in report:
            found += _field_problems(name, report[name], rule)
    sections = spec["simulated_sections"]["fields"]
    if report.get("proposed") and "path" not in report:
        for side in ("proposed", "reference"):
            for name, rule in sections.items():
                where = f"{side}.{name}"
                if name not in report.get(side, {}):
                    found.append(f"missing {where}")
                else:
                    found += _field_problems(where, report[side][name], rule)
    return found


def frozen_reports() -> dict[str, dict]:
    return {path.parent.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(BASELINES.glob("*/report.json"))}


class TestTheContractShips(unittest.TestCase):

    def test_it_is_package_data(self):
        self.assertEqual(1, contract()["contract"])

    def test_it_says_what_it_governs(self):
        self.assertIn("COMPLETED run", contract()["applies_to"])


class TestTheRealPipelineObeysIt(unittest.TestCase):

    def test_every_frozen_report_satisfies_the_contract(self):
        reports = frozen_reports()
        # Non-vacuity: a glob that found nothing would pass every report.
        self.assertGreaterEqual(len(reports), 40, "the frozen corpus went missing")
        spec = contract()
        for scenario, report in reports.items():
            with self.subTest(scenario=scenario):
                self.assertEqual([], problems(report, spec))

    def test_the_corpus_reaches_the_simulated_sections(self):
        # ...or the simulated_sections rule would be checked against nothing.
        simulated = [s for s, r in frozen_reports().items()
                     if r.get("proposed") and "path" not in r]
        self.assertGreaterEqual(len(simulated), 5, simulated)


class TestTheCheckerRefuses(unittest.TestCase):
    """The checker must say no, on a REAL report, for each kind of break."""

    @classmethod
    def setUpClass(cls):
        reports = frozen_reports()
        cls.spec = contract()
        cls.simulated = next(r for r in reports.values()
                             if r.get("proposed") and "path" not in r)

    def _broken(self, change):
        report = copy.deepcopy(self.simulated)
        self.assertEqual([], problems(report, self.spec), "the control must pass")
        change(report)
        return problems(report, self.spec)

    def test_a_renamed_field(self):
        def rename(r):
            r["is_compliant"] = r.pop("compliant")
        self.assertIn("missing always-present field 'compliant'", self._broken(rename))

    def test_a_changed_type(self):
        def stringify(r):
            r["hdd"] = str(r["hdd"])
        self.assertTrue(any(p.startswith("hdd has type str") for p in self._broken(stringify)))

    def test_an_unknown_determination_value(self):
        def invent(r):
            r["compliance_determination"] = "probably"
        self.assertTrue(any("compliance_determination='probably'" in p
                            for p in self._broken(invent)))

    def test_a_missing_verdict_quantity(self):
        def drop(r):
            del r["reference"]["total_site_kwh"]
        self.assertIn("missing reference.total_site_kwh", self._broken(drop))

    def test_an_ADDED_field_is_not_a_break(self):
        def add(r):
            r["something_new"] = 1
        self.assertEqual([], self._broken(add))


class TestTheValueListsMatchTheCode(unittest.TestCase):

    def test_compliance_determination_lists_every_value_the_code_assigns(self):
        assigned = set()
        for path in SRC.rglob("*.py"):
            assigned |= set(re.findall(
                r"""\[["']compliance_determination["']\]\s*=\s*["']([a-z_]+)["']""",
                path.read_text(encoding="utf-8")))
        self.assertTrue(assigned, "no assignment found — the pattern went stale")
        self.assertEqual(
            assigned, set(contract()["when_present"]["compliance_determination"]["enum"]),
            "the code assigns a value the contract does not list, or the contract "
            "lists one the code never assigns")

    def test_simulate_lists_exactly_the_cli_choices(self):
        tree = ast.parse((SRC / "codes" / "cli.py").read_text(encoding="utf-8"))
        choices = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "--simulate"):
                for kw in node.keywords:
                    if kw.arg == "choices":
                        choices = ast.literal_eval(kw.value)
        self.assertIsNotNone(choices, "--simulate choices not found in cli.py")
        self.assertEqual(set(choices), set(contract()["always"]["simulate"]["enum"]))


class TestItIsDocumented(unittest.TestCase):

    def test_the_readme_names_every_public_field(self):
        readme = (REPO_ROOT / "src" / "README.md").read_text(encoding="utf-8")
        spec = contract()
        names = [*spec["always"], *spec["when_present"], *spec["simulated_sections"]["fields"]]
        for name in names:
            with self.subTest(field=name):
                self.assertIn(f"`{name}`", readme)


if __name__ == "__main__":
    unittest.main()
