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
import subprocess
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




class TestDecisionLinksResolve(unittest.TestCase):
    """Every link into the decision log must land where it claims.

    GitHub derives a heading's anchor by slugging the WHOLE heading, so
    ``## D-95 — Freeze-carrying PRs …`` renders at
    ``#d-95--freeze-carrying-prs-…``. The document used the bare ``#d-XX``
    form in 14 places and 13 of them resolved nowhere — the exception being
    ``#d-81``, whose heading is a bare id, which is why the defect survived
    (Fable, PR #59/#60).

    The fix is an explicit ``<a id="d-95"></a>`` before each heading, so the
    SHORT form is real. The id is the identity and the title is prose: an entry
    keeps its id forever, while a reworded heading silently invalidates every
    full-slug link — including references outside this repository, which no
    test can reach.

    GitHub's sanitiser rewrites the id to ``user-content-d-95``, which is
    exactly what it does to its own heading permalinks: all 137 in this file
    carry ``id="user-content-X"`` with ``href="#X"``, so the short form
    resolves through the same client-side mapping every heading link uses.
    """

    DOC = PYTHON_ROOT.parent / "docs" / "necb_decisions.md"
    TREE = PYTHON_ROOT.parent

    #: Anchors read from GitHub's own rendered blob, not derived here — a
    #: derivation pinned against itself proves nothing, which is how a
    #: whitespace bug once rewrote 13 links self-consistently wrong.
    LIVE_ANCHORS = {
        "D-95 — Freeze-carrying PRs merge with a merge commit, not a squash or rebase":
            "d-95--freeze-carrying-prs-merge-with-a-merge-commit-not-a-squash-or-rebase",
        "D-11 — 8.4.4.14 Hydronic Pumps: implemented (intensity transfer + table curves)":
            "d-11--84414-hydronic-pumps-implemented-intensity-transfer--table-curves",
        "D-93 — The reference pump's value source: correspondence, then the sentence that governs it":
            "d-93--the-reference-pumps-value-source-correspondence-then-the-sentence-that-governs-it",
    }

    #: ``](#x)``, ``[x]: #x`` and ``href="#x"`` all render as links; matching
    #: only the first let a reference-style definition through (Fable, PR #60).
    LINK = re.compile(r'(?:\]\(|\]:[ \t]*|href=")#([^)\s"]+)')

    @staticmethod
    def slug(heading: str) -> str:
        """GitHub's heading-anchor rule: lowercase, drop punctuation, then one
        hyphen PER SPACE — an em-dash leaves two spaces and so two hyphens."""
        text = heading.strip().lower()
        text = re.sub(r"[^\w\s-]", "", text)
        return re.sub(r"\s", "-", text)

    @classmethod
    def targets(cls, doc=None) -> set:
        """Every fragment the page offers: heading anchors AND declared ids.

        Headings at all six levels, with GitHub's ``-1``/``-2`` suffix on a
        repeated slug. Modelling only unique ``##`` headings made the gate
        reject VALID links to the 40 level-3 headings here (Sol, PR #60).
        """
        doc = cls.DOC.read_text(encoding="utf-8") if doc is None else doc
        seen = {}
        found = set(re.findall(r'^<a id="([^"]+)"></a>$', doc, re.M))
        for match in re.finditer(r"^#{1,6} (.+)$", doc, re.M):
            base = cls.slug(match.group(1))
            count = seen.get(base, 0)
            found.add(base if count == 0 else f"{base}-{count}")
            seen[base] = count + 1
        return found

    def test_the_slug_rule_reproduces_live_github_anchors(self):
        """Non-vacuity, against anchors fetched from the rendered page rather
        than derived here. My first rule collapsed the em-dash's two spaces
        into one hyphen and rewrote every link self-consistently wrong; only a
        comparison with a real anchor caught it."""
        for heading, anchor in self.LIVE_ANCHORS.items():
            with self.subTest(heading=heading[:24]):
                self.assertEqual(anchor, self.slug(heading))

    def test_every_decision_entry_has_an_adjacent_anchor(self):
        """One anchor per registry entry, immediately before its heading —
        otherwise the short form silently stops resolving for that entry
        alone, which is the failure this gate exists to prevent."""
        doc = self.DOC.read_text(encoding="utf-8")
        ids = {item["id"] for item in
               json.loads(REGISTRY.read_text(encoding="utf-8"))["decisions"]}
        adjacent = {m.group(1).upper() for m in
                    re.finditer(r'^<a id="(d-\d+)"></a>\n\n## \1', doc, re.M | re.I)}
        self.assertEqual(sorted(ids), sorted(adjacent),
                         "every D-XX heading needs an <a id> on the line above it")

    def test_every_fragment_link_in_the_log_resolves(self):
        doc = self.DOC.read_text(encoding="utf-8")
        targets = self.targets(doc)
        dangling = sorted({f for f in self.LINK.findall(doc) if f not in targets})
        self.assertEqual(
            [], dangling,
            "decision-log links point at fragments the page does not offer:\n  "
            + "\n  ".join(
                f"#{d} -> try #{next((s for s in sorted(targets) if s.startswith(d + '--')), '(no match)')}"
                for d in dangling))

    def test_every_inbound_link_from_the_tree_resolves(self):
        """Links from ANYWHERE tracked, not just the workflow.

        ``main-red``'s incident body is the one that costs most at the worst
        moment, but scoping the check to that single file would miss the next
        one someone adds in a doc or a docstring (Fable, PR #60). Tracked
        files only — and via ``git ls-files`` rather than a walk, which also
        keeps this off ``.venv`` and the frozen baselines.
        """
        targets = self.targets()
        tracked = subprocess.run(["git", "-C", str(self.TREE), "ls-files"],
                                 capture_output=True, text=True, check=True).stdout.split()
        offenders = []
        for name in tracked:
            try:
                text = (self.TREE / name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for fragment in re.findall(r'necb_decisions\.md#([^)\s"\']+)', text):
                if fragment not in targets:
                    offenders.append(f"{name}: #{fragment}")
        self.assertEqual([], sorted(offenders),
                         "links into the decision log that resolve nowhere:\n  "
                         + "\n  ".join(sorted(offenders)))

    def test_the_target_model_covers_deeper_headings_and_duplicates(self):
        doc = ('<a id="custom"></a>\n\n## Same heading\n\n### Detail\n\n'
               "## Same heading\n\n## Other\n")
        targets = self.targets(doc)
        self.assertIn("detail", targets, "level-3 headings get anchors too")
        self.assertIn("same-heading", targets, "first occurrence keeps the bare slug")
        self.assertIn("same-heading-1", targets, "a repeat gets GitHub's -1 suffix")
        self.assertIn("custom", targets, "a declared <a id> is a target too")
        self.assertNotIn("other-1", targets, "a unique slug must not gain a suffix")


if __name__ == "__main__":
    unittest.main()
