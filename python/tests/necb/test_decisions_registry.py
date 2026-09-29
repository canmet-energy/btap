"""The runtime-citation invariant (R3, D-81): every ``kind: runtime``
decision is cited by a ``ruling`` literal in product Python.

This was once two-sided, enforced here over ``python/btap`` and in the Ruby
gem's ``test_decisions_registry.rb`` over gem ``lib/``. D-84 retired the gems
at R6, so the Python side is the whole invariant now.

The registry it reads, ``python/btap/codes/data/decisions.json``, is
GENERATED from the canonical per-decision sources in ``docs/decisions/``
(D-81, amended 2026-09-29). This file is therefore checking citations against
a projection; ``test_decisions_registry_sync.py`` is what holds that
projection to its sources.

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
test cannot, and the frozen scenarios in ``verification/scenarios/`` compare
the actual audit output). An
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
            f"{uncited} (tag the call site, or re-classify the entry)")

    def test_non_runtime_entries_are_not_cited(self):
        cited = _cited_ids(self.sites)
        stray = sorted(d["id"] for d in self.decisions
                       if d["kind"] != "runtime" and d["id"] in cited)
        self.assertEqual([], stray,
                         f"cited at runtime but not kind:runtime: {stray}")




class TestDecisionShortIdsResolve(unittest.TestCase):
    """Every `#d-NN` link into the decision log lands on a real target.

    **The declaration half of this gate is gone, because generation replaced
    it.** Its predecessor tried to prove that every id was declared exactly
    once by modelling what GitHub renders: an ATX/Setext/fence/HTML-block
    grammar with ten patterns and a 149-line rule engine, 611 lines in all.
    Seven review rounds each found the model narrower than GitHub -- em-dash
    spacing, level-3 headings, duplicate-source folding, commented-out anchors,
    list-item headings, nested-list Setext, and finally HTML blocks, which hid
    the very false green the design was adopted to kill. One class was a true
    dead link that no amount of widening closed: a declaration that does not
    RENDER -- inside a code fence or a multi-line HTML comment -- was counted
    as live by every raw-source scan.

    `docs/decisions/D-NN.md` closed the dead-link half structurally. Every
    anchor is emitted by `generate_decisions.py`, one per decision, OUTSIDE
    every authored body, and `--check` refuses a hand-edited document. So
    commenting a body out can no longer orphan a fragment, and "one generated
    anchor per decision" is a property of the generator, asserted against the
    generated document in `test_decisions_registry_sync.py` with no Markdown
    model at all.

    What is NOT closed: an authored body could still introduce a second owner
    of the same `d-NN` target -- `<a name="d-01">`, `### **D-01**`, an escaped
    `D\-01`, and others. A rule refusing those was built and cut from PR #64
    after five review rounds each found a further spelling, at a cost out of
    proportion to the consequence: a duplicate id makes a fragment AMBIGUOUS
    between two spellings of the same decision, it does not break the link.
    No committed body does this. If the rule returns it will be its own
    change.

    What generation does NOT establish is that an authored `[D-XX](#d-99)`, or
    an inbound link from elsewhere in the tree, names a decision that exists.
    That is what remains here, and it is answered exactly from the source with
    no model of Markdown at all: every fragment is checked against the registry
    id set.
    """

    DOC = PYTHON_ROOT.parent / "docs" / "necb_decisions.md"
    TREE = PYTHON_ROOT.parent

    #: ``](#x)``, ``[x]: #x`` and ``href="#x"`` all render as links; matching
    #: only the first let a reference-style definition through (Fable, PR #60).
    #: The link spellings this gate recognises — ENUMERATED, not complete.
    #: Each was verified against POST /markdown to render a real link:
    #: `](#d)`, `](<#d>)`, `]( #d)`, `]: <#d>`, and an `href` quoted with
    #: either quote, unquoted, or spaced. HTML attribute names are
    #: case-INSENSITIVE, so `<a HREF="#d">` renders too and the previous
    #: case-sensitive arm missed it (Sol, PR #60).
    #:
    #: The earlier comment claimed "every spelling GitHub renders as a link".
    #: A finite regex cannot model every rendering route, and asserting it did
    #: is the same false-green class the widening exists to close.
    LINK = re.compile(
        r'(?:\]\([ \t]*<?|\]:[ \t]*<?|(?i:href)\s*=\s*[\x22\x27]?)'
        r'#([^)>\s\x22\x27]+)')

    @classmethod
    def declared(cls):
        """The ids a `#d-NN` fragment may name.

        Read from the registry rather than scanned out of the document. The
        generator emits exactly one anchor per registry entry and
        `test_decisions_registry_sync` asserts that, so the registry IS the
        declared set -- where the previous version had to infer it from the
        rendered shape of hand-authored prose.
        """
        return {item["id"] for item in
                json.loads(REGISTRY.read_text(encoding="utf-8"))["decisions"]}

    @classmethod
    def bad_fragments(cls, doc, declared):
        """Fragments in `doc` that are not the short id of a declared entry.

        Shared deliberately. The negative test below first carried its own copy
        of this expression, so mutating the production one left it green — a
        test agreeing with its own reimplementation rather than with the code
        (found while re-running Fable's PR #60 mutation matrix against my own
        fix for it).
        """
        # A previous comment here called the short-form `re.fullmatch` clause
        # DEAD. That was wrong: `.upper()` is many-to-one, so `#D-93` passes
        # membership while failing the fullmatch — the clause was live and
        # case-sensitive. Dropping it is safe for a different reason, which Fable
        # established: GitHub's own client lowercases the fragment before looking
        # up `user-content-<id>`, so a case variant still lands. Case variants
        # are the only inputs whose acceptance changed (Fable, PR #60).
        return sorted({f for f in cls.LINK.findall(doc) if f.upper() not in declared})

    def test_every_authored_fragment_is_a_real_short_id(self):
        """Links are constrained instead of targets being modelled.

        Every fragment in this document is the short form today, so requiring
        that is exact — and it removes the need to derive a full heading slug,
        which is the derivation that was wrong in six different ways.
        """
        doc = self.DOC.read_text(encoding="utf-8")
        wrong = self.bad_fragments(doc, self.declared())
        self.assertEqual([], wrong,
                         "fragments in the decision log must be the short `#d-NN` form of a "
                         f"declared entry; a full heading slug breaks when the heading is "
                         f"reworded, which is why the short form exists: {wrong}")

    def test_the_link_scan_can_fail(self):
        """F1, Fable PR #60. The link side was UNFALSIFIABLE.

        Making `LINK` never match left all ten tests green, as did dropping the
        inbound-tree regex and the short-form `fullmatch`. Two of the three
        remaining patterns therefore had no test that could fail, and the
        reference-definition alternative credited to an earlier review was never
        exercised at all. A scan satisfied by matching nothing is not a scan.
        """
        doc = ('[a](#d-93) and [b]: #d-01\n'
               '<a href="#d-02">c</a>\n'
               '[bad](#not-a-decision)\n'
               '[long](#d-93--a-full-heading-slug)\n')
        self.assertEqual(["d-93", "d-01", "d-02", "not-a-decision",
                          "d-93--a-full-heading-slug"], self.LINK.findall(doc),
                         "all three link spellings must be seen: `](#x)`, `[x]: #x`, `href=\"#x\"`")
        wrong = self.bad_fragments(doc, {"D-93", "D-01", "D-02"})
        self.assertEqual(["d-93--a-full-heading-slug", "not-a-decision"], wrong,
                         "a non-decision fragment AND a full heading slug must both be "
                         "rejected — the full slug is the form that breaks on a reword")

    def test_link_sees_every_spelling_github_renders(self):
        """F8, Fable PR #60 — and a test I should have written with the widening.

        Narrowing `LINK` back to its previous form survived the whole suite: I
        widened the pattern and added nothing that exercises the new spellings.
        Each of these renders a real link (verified against POST /markdown), so
        a dead fragment in any of them previously passed silently.
        """
        cases = {
            "](#d-01)": "plain",
            "](<#d-02>)": "angle-bracketed destination",
            "]( #d-03)": "leading space before the destination",
            "]: <#d-04>": "angle-bracketed reference definition",
            "href=\x22#d-05\x22": "double-quoted href",
            "href='#d-06'": "single-quoted href",
            "href = #d-07": "spaced, unquoted href",
            # HTML attribute names are case-insensitive; GitHub renders
            # `<a HREF="#d">` as a real link and the case-sensitive arm missed
            # it (Sol, PR #60).
            'HREF="#d-08"': "uppercase HREF",
            'HrEf="#d-09"': "mixed-case href",
        }
        for spelling, label in cases.items():
            with self.subTest(spelling=label):
                found = self.LINK.findall(f"text {spelling} more")
                self.assertEqual(1, len(found),
                                 f"{label}: GitHub renders this as a link, so a dead fragment "
                                 f"spelled this way must not pass unseen — got {found}")

    def test_the_scans_are_not_vacuous(self):
        """Floors, so a broken scanner cannot go green-silent — the same
        protection `TestRuntimeCitations.test_scan_is_not_vacuous` already gives
        the citation walker in this file (Fable, PR #60)."""
        doc = self.DOC.read_text(encoding="utf-8")
        self.assertGreaterEqual(
            len(self.LINK.findall(doc)), 10,
            "the decision log carries 14 fragment links today; finding almost none means "
            "the LINK pattern is broken, not that the cross-references went away")
        tracked = [name for name in subprocess.run(
            ["git", "-C", str(self.TREE), "ls-files", "-z"],
            capture_output=True, text=True, check=True).stdout.split("\0") if name]
        inbound = 0
        for name in tracked:
            try:
                text = (self.TREE / name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            inbound += len(self.inbound_fragments(text))
        self.assertGreaterEqual(
            inbound, 1,
            "main-red's incident body links into the decision log; finding zero inbound "
            "links means the tree scan is broken")

    @classmethod
    def inbound_fragments(cls, text):
        """Every inbound decision-log fragment in `text`.

        The ONE extraction. Both `unresolved_inbound` and the vacuity floor call
        it: the floor previously carried its own copy of this expression, so
        changing the helper's regex left the floor passing on its copy while the
        live tree scan inspected zero links — the whole file green with the
        inbound gate silently disabled. That is the THIRD instance of a test
        agreeing with a duplicate implementation in this file (Fable, PR #60).
        """
        return re.findall(r"necb_decisions\.md#([^)\s\x22\x27]+)", text)

    @classmethod
    def unresolved_inbound(cls, text, declared):
        """Inbound decision-log fragments that name no declared id.

        The tree scan calls this, so the negative below pins production
        behaviour. Dropping the membership test survived 15/15 before this
        existed: the vacuity floor proved the regex finds a link, not that a bad
        one is rejected (Fable, PR #60).

        Case policy, stated because a duplicate copy of this predicate had
        already drifted from it: a case variant such as `#D-95` is ACCEPTED,
        because GitHub's client lowercases the fragment before looking up
        `user-content-<id>` (Sol, PR #60).
        """
        return sorted({f for f in cls.inbound_fragments(text)
                       if f.upper() not in declared})

    def test_a_bad_inbound_link_is_rejected(self):
        # The document name and the `#` are joined at RUNTIME so this file does
        # not itself become an inbound link the tree scan then reports. Writing
        # the literal here made the scan flag its own fixture.
        doc = "necb_decisions" ".md"
        text = " ".join(f"see {doc}#{f}" for f in
                        ("d-95", "d-99", "d-95--full-slug", "D-95"))
        self.assertEqual(["d-95--full-slug", "d-99"],
                         self.unresolved_inbound(text, {"D-95"}),
                         "an unknown id and a full heading slug are rejected; a case variant "
                         "is accepted, because GitHub's client lowercases the fragment")

    def test_every_inbound_link_from_the_tree_resolves(self):
        """Links from ANYWHERE tracked, not just the workflow.

        ``main-red``'s incident body is the one that costs most at the worst
        moment, but scoping the check to that file would miss the next one added
        in a doc or a docstring (Fable, PR #60). ``-z`` because splitting
        ``ls-files`` on whitespace drops a tracked path containing a space.
        """
        declared = self.declared()
        tracked = [name for name in subprocess.run(
            ["git", "-C", str(self.TREE), "ls-files", "-z"],
            capture_output=True, text=True, check=True).stdout.split("\0") if name]
        offenders = []
        for name in tracked:
            try:
                text = (self.TREE / name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            # Through the SHARED helper. This loop previously carried its own
            # copy of both the regex and the predicate, and they had already
            # drifted: the copy's `re.fullmatch` rejected `#D-95` while the
            # helper accepts it. So the synthetic negative pinned behaviour the
            # live scan did not have (Sol, PR #60).
            offenders.extend(f"{name}: #{f}" for f in self.unresolved_inbound(text, declared))
        self.assertEqual([], sorted(offenders),
                         "links into the decision log that do not name a declared short id:\n  "
                         + "\n  ".join(sorted(offenders)))


if __name__ == "__main__":
    unittest.main()
