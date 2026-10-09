"""Every ``ahj=`` citation in product Python resolves, and nothing smuggles one.

The AST sibling of ``test_decisions_registry.py``. D-100 moved applicability
to the deciding rule site, which buys the removal of a duplicated predicate at
the price of a NEW failure mode: a site that forgets ``ahj=`` discloses
nothing, silently, which is the class of defect AHJ-5 was. Sol's `127` required
these gates before the design could be called enforceable.

Discovery is AST-BASED for the same reason the D-XX walker is: a line-regex
scan would count an ``ahj='AHJ-1'`` example in a docstring, so a question
mentioned only in prose could falsely satisfy the invariant. There is no
nonliteral escape hatch — a variable pass-through would evade grammar,
resolution and the inventory.
"""

from __future__ import annotations

import ast
import json
import pathlib
import unittest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
REPO_ROOT = PYTHON_ROOT.parent
PRODUCT = PYTHON_ROOT / "btap"
REGISTRY = PRODUCT / "codes" / "data" / "ahj.json"

#: The shared audit surface. An unrelated API reusing the keyword name must not
#: masquerade as audit evidence.
AUDIT_METHODS = {"decision", "info", "warn"}

#: Helper functions a citation may be built by, instead of a bare literal.
#:
#: A site-level AST walk CANNOT see the ids when a helper builds the string —
#: they are literals in the helper's body, not in the call expression. That is
#: a real consequence of the one-helper design, so the inventory scans these
#: functions' bodies as well. The set is deliberately tiny and explicit: every
#: id must still be a literal SOMEWHERE the walker reaches, or the grammar and
#: resolution gates would have nothing to check.
CITATION_HELPERS = {"_disclosure_ahj", "_boiler_class_ahj", "_dispatch_ahj",
                    # AHJ-3 left `_disclosure_ahj` with D-101: its scope is
                    # the PLANT, not the service set (Sol, `143`).
                    "_plant_cardinality_ahj"}


def _registry() -> dict:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in data["entries"]}


def _citation_sites():
    """``[(path, line, method, value_node)]`` for every ``ahj=`` keyword."""
    sites, star_kwargs = [], []
    for path in sorted(PRODUCT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method = (node.func.attr if isinstance(node.func, ast.Attribute)
                      else getattr(node.func, "id", None))
            for keyword in node.keywords:
                if keyword.arg is None and method in AUDIT_METHODS:
                    star_kwargs.append((path.relative_to(PYTHON_ROOT),
                                        keyword.value.lineno, method))
                if keyword.arg != "ahj":
                    continue
                sites.append((path.relative_to(PYTHON_ROOT),
                              keyword.value.lineno, method, keyword.value))
    return sites, star_kwargs


class TestAHJCitationSites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sites, cls.star_kwargs = _citation_sites()
        cls.registry = _registry()

    def test_the_scan_is_not_vacuous(self):
        """A broken walker must not go green-silent. Two sites at D-100: the
        generic and specific multi-energy disclosure branches."""
        self.assertGreaterEqual(
            len(self.sites), 2,
            "no ahj= citation sites found — the walker or the design broke")
        self.assertTrue(self.registry, "the generated register is empty")

    def test_every_citation_sits_on_the_AUDIT_surface(self):
        """`ahj=` on some unrelated call is not audit evidence."""
        wrong = [f"{path}:{line} — ahj= on .{method}(), not an audit method"
                 for path, line, method, _ in self.sites
                 if method not in AUDIT_METHODS]
        self.assertEqual([], wrong, "\n".join(wrong))

    def test_no_kwargs_expansion_on_the_audit_surface(self):
        problems = [f"{path}:{line} — **kwargs on .{method}(): a dict could "
                    "smuggle a citation past every gate"
                    for path, line, method in self.star_kwargs]
        self.assertEqual([], problems, "\n".join(problems))

    def test_every_citation_RESOLVES_in_the_generated_register(self):
        """A citation resolving to nothing would turn a missing disclosure into
        a clean non-conditional success."""
        unknown = []
        for path, line, _method, value in self.sites:
            for ident in self._ids(value):
                if ident not in self.registry:
                    unknown.append(f"{path}:{line} — {ident} is not in "
                                   f"{REGISTRY.name}")
        for ident in sorted(_helper_ids()):
            if ident not in self.registry:
                unknown.append(f"a citation helper builds {ident}, which is "
                               f"not in {REGISTRY.name}")
        self.assertEqual([], unknown, "\n".join(unknown))
        self.assertTrue(
            _helper_ids() or any(self._ids(v) for *_r, v in self.sites),
            "no literal id reached the walker at all")

    def test_a_dynamic_citation_is_refused(self):
        """A literal, or a call to the ONE helper that builds one.

        `_disclosure_ahj` is admitted by name because the ids it can return are
        literals inside it, which this walker still sees; anything else would
        evade the grammar and the inventory.
        """
        allowed_helpers = CITATION_HELPERS
        bad = []
        for path, line, method, value in self.sites:
            if self._is_literal_citation(value):
                continue
            if (isinstance(value, ast.Call)
                    and getattr(value.func, "id", None) in allowed_helpers):
                continue
            bad.append(f"{path}:{line} — ahj= on .{method}() is neither a "
                       f"literal citation nor {sorted(allowed_helpers)}")
        self.assertEqual([], bad, "\n".join(bad))

    @staticmethod
    def _is_literal_citation(value) -> bool:
        """A string literal, or a conditional whose BOTH branches are one.

        `ahj='AHJ-16' if in_scope else None` is admitted because every id in it
        is still a visible literal this walker reads — which is the property
        the gate exists to protect — and a narrowing that applies at the site
        is exactly what Sol's `127` asked for. It is NOT a loophole for
        `ahj=some_variable`: both branches must be a `str` or `None`
        constant, so a pass-through still fails.
        """
        if isinstance(value, ast.Constant):
            return isinstance(value.value, (str, type(None)))
        if isinstance(value, ast.IfExp):
            return all(
                isinstance(branch, ast.Constant)
                and isinstance(branch.value, (str, type(None)))
                for branch in (value.body, value.orelse))
        return False

    def test_no_COVERAGE_entry_carries_a_citation(self):
        """Sol's `127`: "A static coverage warning emitted on every run is not
        evidence that a building reached the question." Only an executed choice
        may cite one."""
        coverage = [f"{path}:{line}" for path, line, _m, _v in self.sites
                    if "coverage" in str(path).lower()]
        self.assertEqual([], coverage, "\n".join(coverage))

    @staticmethod
    def _ids(value) -> list:
        """Literal ids visible in a citation NODE itself."""
        import re

        found = []
        for node in ast.walk(value):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found += re.findall(r"\bAHJ-\d+\b", node.value)
        return found


def _helper_ids() -> set:
    """Literal ids inside the bodies of the admitted citation helpers."""
    import re

    found = set()
    for path in sorted(PRODUCT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name in CITATION_HELPERS):
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Constant)
                            and isinstance(inner.value, str)):
                        found.update(re.findall(r"\bAHJ-\d+\b", inner.value))
    return found


class TestTheRegisterAndTheSitesAgree(unittest.TestCase):
    """Sol's guard 2, the other direction: an entry the register says is
    runtime-wired must have a real call site."""

    @classmethod
    def setUpClass(cls):
        cls.sites, _ = _citation_sites()
        cls.registry = _registry()
        cls.cited = set(_helper_ids())
        for _p, _l, _m, value in cls.sites:
            cls.cited.update(TestAHJCitationSites._ids(value))

    def test_the_cited_set_is_not_empty(self):
        self.assertTrue(self.cited, "no ids cited — the inventory is vacuous")

    def test_the_REGISTER_declares_which_entries_are_wired(self):
        """The register's own conditional column is the claim; this holds it to
        the code. An entry marked `yes` with no call site would be a promise
        the product does not keep.
        """
        import re

        text = (REPO_ROOT / "docs" / "NECB_AHJ_QUESTIONS.md").read_text(
            encoding="utf-8")
        rows = re.findall(
            r"^\| (AHJ-\d+) \|(?:[^|]*\|){3}([^|]*)\|", text, re.M)
        self.assertTrue(rows, "the status table did not parse")
        promised = {ident for ident, sets in rows
                    if sets.strip().lower().startswith("yes")}
        missing = sorted(promised - self.cited)
        self.assertEqual(
            [], missing,
            "the register says these set a run conditional, but no product "
            "ahj= call site cites them: {}".format(missing))

    def test_a_cited_id_is_not_marked_NO(self):
        """The converse: citing an id the register says never affects a run is
        either a wrong citation or a stale row."""
        import re

        text = (REPO_ROOT / "docs" / "NECB_AHJ_QUESTIONS.md").read_text(
            encoding="utf-8")
        rows = dict(re.findall(
            r"^\| (AHJ-\d+) \|(?:[^|]*\|){3}([^|]*)\|", text, re.M))
        for ident in sorted(self.cited):
            sets = (rows.get(ident) or "").strip().lower()
            status = self.registry[ident]["status"]
            if status in ("ruled", "tool-gap"):
                continue      # cited for traceability; never conditional
            # The FIRST TOKEN, not a prefix: `"not yet".startswith("no")` is
            # True, so a prefix test conflated "this question does not affect a
            # run" with "its wiring is still being established" — opposite
            # meanings, and the gate reported the wrong one.
            first = sets.split(None, 1)[0] if sets else ""
            with self.subTest(ident, status=status, column=sets[:24]):
                # "no" AND "not yet" both fail now. Fable's `131` F4: letting
                # "not yet" through meant a WIRED referral could sit on a stale
                # row, and `TestTheREADMEMatchesTheRegister` then held the
                # README to that same stale row — two prose surfaces vouching
                # for each other and neither for the code. A cited
                # approval-required id is wired BY DEFINITION, so its row must
                # say so.
                self.assertNotIn(
                    first, ("no", "not"),
                    "{} is cited in product code and is a {}, but the register "
                    "column says {!r} — a cited id is wired, so the row must "
                    "say what it does".format(ident, status, sets[:28]))


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
