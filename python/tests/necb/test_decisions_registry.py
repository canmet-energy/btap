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

#: A short decision fragment, ``d-95``. Deliberately NOT matching ``d-95-1``:
#: GitHub's duplicate suffix makes that a different target, so a repeated
#: heading is a registry-sync problem, not a duplicate element id.
SHORT_ID = re.compile(r"d-\d+", re.I)

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




class TestDecisionShortIdsResolve(unittest.TestCase):
    """Every `#d-NN` link into the decision log lands on a real target.

    **This gate is deliberately small, and that is a correction.** Its
    predecessor tried to prove the same thing by modelling what GitHub renders:
    an ATX/Setext/fence/HTML-block grammar with ten patterns and a 149-line rule
    engine, 611 lines in all. Seven review rounds each found the model narrower
    than GitHub — em-dash spacing, level-3 headings, duplicate-source folding,
    commented-out anchors, list-item headings, nested-list Setext, and finally
    HTML blocks, which hid the very false green the design was adopted to kill.
    Every round was a defect in the CHECK, not in the document; the document's
    13 dead links were fixed in the first round and have been correct since.

    So this asks only what can be answered exactly from the source, with no
    model of Markdown at all:

    1. every registry id is declared exactly once, as an explicit anchor or as
       a bare ``## D-NN`` heading whose own slug is already the short id;
    2. every fragment authored into or at the log is the short id of a real
       registry entry.

    What it deliberately does NOT do is enumerate every construct that could
    ALSO render a `d-NN` id — a heading inside a list, a Setext underline, an
    entity. Those produce a duplicate id, which makes a fragment ambiguous
    between two spellings of the same decision; they do not produce a dead
    link. Chasing them exhaustively is what cost seven rounds, and the fix is
    structural rather than a wider regex: generate the document from the
    registry, so a drifting or duplicated anchor cannot be written at all. That
    is proposed separately; this gate is the interim, and it is honest about
    being one.
    """

    DOC = PYTHON_ROOT.parent / "docs" / "necb_decisions.md"
    TREE = PYTHON_ROOT.parent

    #: ``](#x)``, ``[x]: #x`` and ``href="#x"`` all render as links; matching
    #: only the first let a reference-style definition through (Fable, PR #60).
    LINK = re.compile(r'(?:\]\(|\]:[ \t]*|href=")#([^)\s"]+)')

    #: The explicit anchor, and the bare heading whose natural GitHub slug is
    #: already the short id. Fourteen entries use the second form and need no
    #: anchor — which is why adding one to all 95 created fourteen duplicate
    #: element ids (Sol, PR #60).
    ANCHOR = re.compile(r'^<a id="(d-\d+)"></a>$', re.M)
    BARE_HEADING = re.compile(r"^##[ ]+(D-\d+)[ ]*$", re.M)

    @classmethod
    def sources(cls, doc):
        """Where each short id is declared, as a list per id so a duplicate is
        visible. A set would hide the defect this exists to catch."""
        found = {}
        for match in cls.ANCHOR.finditer(doc):
            found.setdefault(match.group(1).upper(), []).append("explicit anchor")
        for match in cls.BARE_HEADING.finditer(doc):
            found.setdefault(match.group(1).upper(), []).append("bare heading slug")
        return found

    def test_every_registry_id_is_declared_exactly_once(self):
        doc = self.DOC.read_text(encoding="utf-8")
        ids = {item["id"] for item in
               json.loads(REGISTRY.read_text(encoding="utf-8"))["decisions"]}
        sources = self.sources(doc)

        self.assertEqual(sorted(ids), sorted(sources),
                         "every registry id must be reachable at #d-NN, and nothing else may be")
        duplicated = {k: v for k, v in sources.items() if len(v) > 1}
        self.assertEqual({}, duplicated,
                         "these ids are declared twice, so the rendered page carries duplicate "
                         f"element ids and the fragment is ambiguous: {duplicated}")

    def test_a_duplicate_declaration_is_caught(self):
        """The negative case. An explicit anchor on top of a bare heading is
        exactly what this PR first shipped, fourteen times over."""
        both = self.sources('<a id="d-81"></a>\n\n## D-81\n')
        self.assertEqual(["explicit anchor", "bare heading slug"], both["D-81"])
        titled = self.sources('<a id="d-93"></a>\n\n## D-93 — a title\n')
        self.assertEqual(["explicit anchor"], titled["D-93"],
                         "a titled heading's own slug is its full title, so the anchor is the "
                         "only source of the short id and is required")

    def test_every_authored_fragment_is_a_real_short_id(self):
        """Links are constrained instead of targets being modelled.

        Every fragment in this document is the short form today, so requiring
        that is exact — and it removes the need to derive a full heading slug,
        which is the derivation that was wrong in six different ways.
        """
        doc = self.DOC.read_text(encoding="utf-8")
        declared = set(self.sources(doc))
        wrong = sorted({f for f in self.LINK.findall(doc)
                        if not re.fullmatch(r"d-\d+", f) or f.upper() not in declared})
        self.assertEqual([], wrong,
                         "fragments in the decision log must be the short `#d-NN` form of a "
                         f"declared entry; a full heading slug breaks when the heading is "
                         f"reworded, which is why the short form exists: {wrong}")

    def test_every_inbound_link_from_the_tree_resolves(self):
        """Links from ANYWHERE tracked, not just the workflow.

        ``main-red``'s incident body is the one that costs most at the worst
        moment, but scoping the check to that file would miss the next one added
        in a doc or a docstring (Fable, PR #60). ``-z`` because splitting
        ``ls-files`` on whitespace drops a tracked path containing a space.
        """
        doc = self.DOC.read_text(encoding="utf-8")
        declared = set(self.sources(doc))
        tracked = [name for name in subprocess.run(
            ["git", "-C", str(self.TREE), "ls-files", "-z"],
            capture_output=True, text=True, check=True).stdout.split("\0") if name]
        offenders = []
        for name in tracked:
            try:
                text = (self.TREE / name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for fragment in re.findall(r'necb_decisions\.md#([^)\s"\']+)', text):
                if not re.fullmatch(r"d-\d+", fragment) or fragment.upper() not in declared:
                    offenders.append(f"{name}: #{fragment}")
        self.assertEqual([], sorted(offenders),
                         "links into the decision log that do not name a declared short id:\n  "
                         + "\n  ".join(sorted(offenders)))


if __name__ == "__main__":
    unittest.main()
