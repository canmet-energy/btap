"""The Python half of the two-sided runtime-citation invariant (R3, D-81).

While both implementations exist (until R6), every ``kind: runtime``
decision must be cited by a ``ruling`` literal in BOTH of them — the Ruby
gem's ``test_decisions_registry.rb`` enforces its side over gem ``lib/``;
THIS file enforces the Python side over ``python/btap``, reading the
CANONICAL registry (``python/btap/codes/data/decisions.json``).

Discovery is AST-BASED, deliberately: a line-regex scan counted the
``ruling='D-14'`` EXAMPLE in a module docstring as a citation, so a future
runtime decision mentioned only in documentation could falsely satisfy the
invariant. ``ast.parse`` sees only real ``ast.Call`` keywords — comments,
docstrings, assignments, and ``ruling=None`` parameter DEFAULTS never
reach the walker. There is NO nonliteral escape hatch: every ``ruling=``
call keyword must be a single-line string constant matching the grammar
(a variable pass-through would evade grammar, resolution, and the
cited-id inventory), and it must sit on the shared audit surface
(``.decision(...)``/``.info(...)``/``.warn(...)``) so an unrelated API
reusing the keyword name cannot masquerade as audit evidence.

The audit-surface check is deliberately SYNTACTIC: any attribute call
named decision/info/warn counts — the scanner enforces the project's
audit-call convention, it does not resolve receiver types (a stdlib-only
test cannot, and Leg B verifies the actual audit output anyway). An
expanded keyword dictionary (``**{"ruling": ...}``) on an audit-surface
call is REFUSED outright: the AST sees it as an anonymous keyword that
would bypass grammar, resolution, and the inventory.

No SDK import — bare-runner safe, like the sync gate beside it.
"""

import ast
import json
import re
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = PYTHON_ROOT / "btap" / "codes" / "data" / "decisions.json"

ID_TOKEN = re.compile(r"\bD-\d{2}\b")
LITERAL_GRAMMAR = re.compile(r"\AD-\d{2}( D-\d{2})*\Z")
AUDIT_METHODS = frozenset({"decision", "info", "warn"})

#: A future forwarding call that legitimately passes a variable would be
#: allowed HERE, by exact (file, method) pair — never by a general rule.
NONLITERAL_EXCEPTIONS = frozenset()


def _registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["decisions"]


def _citation_sites():
    """[(path, line, method_name, value_node)] for every ``ruling=``
    keyword on any ``ast.Call`` under python/btap."""
    sites = []
    star_kwargs = []
    for path in sorted((PYTHON_ROOT / "btap").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            method = (node.func.attr if isinstance(node.func, ast.Attribute)
                      else getattr(node.func, "id", None))
            for keyword in node.keywords:
                if keyword.arg is None and method in AUDIT_METHODS:
                    # **kwargs expansion on the audit surface could smuggle a
                    # ruling past every gate — refused, not ignored.
                    star_kwargs.append(
                        (path.relative_to(PYTHON_ROOT), keyword.value.lineno, method))
                if keyword.arg != "ruling":
                    continue
                sites.append((path.relative_to(PYTHON_ROOT), keyword.value.lineno,
                              method, keyword.value))
    return sites, star_kwargs


def _cited_ids(sites):
    cited = set()
    for _, _, _, value in sites:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            cited.update(ID_TOKEN.findall(value.value))
    return cited


class TestRuntimeCitations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sites, cls.star_kwargs = _citation_sites()
        cls.decisions = _registry()

    def test_no_kwargs_expansion_on_the_audit_surface(self):
        problems = [f"{path}:{line} — **kwargs expansion on .{method}(): a "
                    "dict could smuggle a ruling past grammar, resolution, "
                    "and the inventory; pass keywords explicitly"
                    for path, line, method in self.star_kwargs]
        self.assertEqual([], problems, "\n".join(problems))

    def test_scan_is_not_vacuous(self):
        # 135 sites at R3; a broken walker must not go green-silent.
        self.assertGreaterEqual(
            len(self.sites), 100,
            "the citation walker found suspiciously few ruling= call sites — "
            "it is broken, not the codebase clean")

    def test_every_ruling_value_is_a_literal_on_the_audit_surface(self):
        problems = []
        for path, line, method, value in self.sites:
            if (str(path), method) in NONLITERAL_EXCEPTIONS:
                continue
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                problems.append(
                    f"{path}:{line} — ruling= must be a string LITERAL (a "
                    "variable would evade grammar, resolution, and the "
                    "cited-id inventory); add a narrow NONLITERAL_EXCEPTIONS "
                    "entry only for a real forwarding call")
                continue
            if not LITERAL_GRAMMAR.match(value.value):
                problems.append(
                    f"{path}:{line} — ruling literal {value.value!r} must "
                    "match 'D-NN( D-NN)*'")
            if method not in AUDIT_METHODS:
                problems.append(
                    f"{path}:{line} — ruling= on {method!r}, not the audit "
                    f"surface {sorted(AUDIT_METHODS)}; audit citations are "
                    "evidence and must flow through AuditLog")
        self.assertEqual([], problems, "\n".join(problems))

    def test_every_cited_id_resolves(self):
        known = {d["id"] for d in self.decisions}
        unknown = sorted(_cited_ids(self.sites) - known)
        self.assertEqual([], unknown,
                         f"code cites unregistered decision id(s): {unknown}")

    def test_every_runtime_entry_is_cited(self):
        cited = _cited_ids(self.sites)
        uncited = sorted(d["id"] for d in self.decisions
                         if d["kind"] == "runtime" and d["id"] not in cited)
        self.assertEqual(
            [], uncited,
            f"kind:runtime but no ruling literal cites them in python/btap: "
            f"{uncited} (tag the call site, or re-classify the entry) — a "
            "runtime decision must be cited in BOTH implementations while "
            "both exist (until R6)")

    def test_non_runtime_entries_are_not_cited(self):
        cited = _cited_ids(self.sites)
        stray = sorted(d["id"] for d in self.decisions
                       if d["kind"] != "runtime" and d["id"] in cited)
        self.assertEqual([], stray,
                         f"cited at runtime but not kind:runtime: {stray}")


if __name__ == "__main__":
    unittest.main()


class TestDecisionCrossReferencesResolve(unittest.TestCase):
    """Every `#fragment` link into the decision log must hit a real heading.

    GitHub derives a heading's anchor by slugging the WHOLE heading, so
    ``## D-95 — Freeze-carrying PRs merge …`` is reachable at
    ``#d-95--freeze-carrying-prs-merge-…`` and NOT at ``#d-95``. The document
    used the short form in 13 places and none of them resolved: the link
    silently opened a 6,000-line file at the top (Fable, PR #59).

    Two properties, and the second is the one that keeps this from rotting:
    every link resolves TODAY, and the `main-red` incident body's link into
    this document resolves too. A heading retitled later changes its slug, and
    this fails rather than leaving a dead pointer in the one place nobody
    looks until an incident.
    """

    DOC = PYTHON_ROOT.parent / "docs" / "necb_decisions.md"
    WORKFLOW = PYTHON_ROOT.parent / ".github" / "workflows" / "test.yml"

    @staticmethod
    def slug(heading: str) -> str:
        """GitHub's heading-anchor rule: lowercase, drop punctuation, hyphens."""
        text = heading.strip().lower()
        text = re.sub(r"[^\w\s-]", "", text)
        return re.sub(r"\s", "-", text)

    def heading_slugs(self) -> set:
        doc = self.DOC.read_text(encoding="utf-8")
        return {self.slug(m.group(1)) for m in re.finditer(r"^## (.+)$", doc, re.M)}

    def test_every_in_document_fragment_link_resolves(self):
        doc = self.DOC.read_text(encoding="utf-8")
        slugs = self.heading_slugs()
        dangling = sorted({f for f in re.findall(r"\]\(#([^)]+)\)", doc) if f not in slugs})
        self.assertEqual(
            [], dangling,
            "decision-log links point at anchors GitHub does not generate. The "
            "anchor is the slug of the WHOLE heading, not the bare id:\n  "
            + "\n  ".join(f"#{d} -> try #{next((s for s in slugs if s.startswith(d)), '?')}"
                          for d in dangling))

    def test_the_incident_body_links_a_real_anchor(self):
        """`main-red` tells whoever merged where the recovery path is. A dead
        fragment there costs most at the worst moment, and nothing else would
        notice it."""
        workflow = self.WORKFLOW.read_text(encoding="utf-8")
        found = re.findall(r"necb_decisions\.md#([a-z0-9-]+)", workflow)
        self.assertTrue(found, "the main-red body no longer links the decision log")
        slugs = self.heading_slugs()
        for fragment in found:
            self.assertIn(fragment, slugs,
                          f"main-red links #{fragment}, which is not a heading anchor")

    def test_the_slug_rule_matches_a_known_heading(self):
        """Non-vacuity: the rule must actually reproduce a live anchor, or both
        tests above would pass by agreeing with a broken derivation."""
        self.assertEqual(
            "d-95--freeze-carrying-prs-merge-with-a-merge-commit-not-a-squash-or-rebase",
            self.slug("D-95 — Freeze-carrying PRs merge with a merge commit, "
                      "not a squash or rebase"))
