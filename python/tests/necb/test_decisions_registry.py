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




class TestDecisionShortIdsResolve(unittest.TestCase):
    """Every `#d-NN` link into the decision log lands on a real target.

    **This gate is deliberately small, and that is a correction.** Its
    predecessor tried to prove the same thing by modelling what GitHub renders:
    an ATX/Setext/fence/HTML-block grammar with ten patterns and a 149-line rule
    engine, 611 lines in all. Seven review rounds each found the model narrower
    than GitHub — em-dash spacing, level-3 headings, duplicate-source folding,
    commented-out anchors, list-item headings, nested-list Setext, and finally
    HTML blocks, which hid the very false green the design was adopted to kill.
    The document reached its present form at `3ad8602` — 81 explicit anchors
    beside the 14 bare headings — and has not changed since. The SEVEN rounds
    after that changed only the check. Rounds one to three were not: round one
    rewrote the links to full heading slugs, and round two put an anchor on all
    95 entries, which created 14 duplicate element ids on the bare headings.
    That was a document defect, and earlier wording here and in a commit message
    claimed the document had been correct from the first round. It had not
    (Fable, PR #60).

    So this asks only what can be answered exactly from the source, with no
    model of Markdown at all:

    1. every registry id is declared exactly once, as an explicit anchor or as
       a bare ``## D-NN`` heading whose own slug is already the short id;
    2. every fragment authored into or at the log is the short id of a real
       registry entry.

    What it deliberately does NOT do is enumerate every construct that could
    ALSO render a `d-NN` id — a heading inside a list, a Setext underline, an
    entity, an INLINE `<a id="d-NN"></a>`, or a `### D-NN` heading, both of
    which render and own the short slug just as the conventional forms do.
    Those produce a duplicate id, which makes a fragment ambiguous between two
    spellings of the same decision; they do not produce a dead link.

    **And one class IS a dead link, which an earlier version of this docstring
    failed to say while presenting itself as the complete statement.** A
    declaration that does not RENDER — inside a code fence, a multi-line HTML
    comment, or any other HTML block — is still counted here as live. Wrap an
    entry's anchor and heading in `<!-- … -->` and every test in this file and in
    `test_decisions_registry_sync` stays green while `#d-NN` resolves nowhere,
    because both scan raw source. Nothing else in the repository catches it
    (Fable, PR #60).

    `test_no_declaration_is_hidden_in_a_comment` closes the realistic route —
    commenting an entry out — with a literal whitelist of the two TOC markers,
    which needs no Markdown model. The fence route stays open and is accepted:
    the document has one four-line fence, and the structural fix is to generate
    the document from the registry so a hidden or duplicated declaration cannot
    be written at all. That is proposed separately; this gate is the interim and
    is honest about being one.
    """

    DOC = PYTHON_ROOT.parent / "docs" / "necb_decisions.md"
    TREE = PYTHON_ROOT.parent

    #: ``](#x)``, ``[x]: #x`` and ``href="#x"`` all render as links; matching
    #: only the first let a reference-style definition through (Fable, PR #60).
    #: Every spelling GitHub renders as a link. Verified against POST
    #: /markdown: `[x](<#d>)`, `[x]( #d)`, `[x]: <#d>` and a
    #: single-quoted href all become real links, and the previous
    #: pattern saw none of them — so a dead fragment in any of those
    #: spellings passed silently (Fable, PR #60).
    LINK = re.compile(
        r'(?:\]\([ \t]*<?|\]:[ \t]*<?|href\s*=\s*[\x22\x27]?)'
        r'#([^)>\s\x22\x27]+)')

    #: The explicit anchor, and the bare heading whose natural GitHub slug is
    #: already the short id. Fourteen entries use the second form and need no
    #: anchor — which is why adding one to all 95 created fourteen duplicate
    #: element ids (Sol, PR #60).
    ANCHOR = re.compile(r'^<a id="(d-\d+)"></a>$', re.M)
    BARE_HEADING = re.compile(r"^##[ ]+(D-\d+)[ ]*$", re.M)

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

    @classmethod
    def comment_markers(cls, doc):
        """Every line carrying an HTML comment delimiter."""
        return [ln.strip() for ln in doc.splitlines() if "<!--" in ln or "-->" in ln]

    @classmethod
    def hidden_declaration_risk(cls, doc):
        """Why `doc`'s HTML comments could hide a declaration from every scan
        here, or [] if they cannot.

        Shared by the live assertion and its synthetic negative, so mutating the
        rule fails both. Asserting only against the live document left each
        clause unfalsifiable.
        """
        markers = cls.comment_markers(doc)
        problems = []
        if len(markers) != 2:
            problems.append(f"expected only the TOC's two comment markers, got {markers}")
        else:
            if "TOC BEGIN" not in markers[0] or "TOC END" not in markers[1]:
                problems.append(f"the two comment markers are not the TOC's: {markers}")
        problems.extend(f"a comment that does not close on its own line can span a "
                        f"declaration: {m!r}"
                        for m in markers if not (m.startswith("<!--") and m.endswith("-->")))
        return problems

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

    def test_only_a_line_start_declaration_counts(self):
        """`sources()` had no synthetic case, so loosening either pattern was
        invisible: the live document has no inline anchor and no `### D-NN`, so
        accepting them changed nothing it could show (mutation matrix, PR #60).

        Both forms are ignored because this gate recognises only the
        repository's source CONVENTIONS — a standalone anchor and a level-2
        heading — **and not because GitHub fails to render them.** Both render,
        and both own the short id:

            text <a id="d-81"></a> more text
            -> <p>text <a id="user-content-d-81"></a> more text</p>

            ### D-81
            -> a level-3 heading, slugged from its text like any other, so it
               owns `d-81` exactly as `## D-81` would

        So each is an ACCEPTED RENDERER BLIND SPOT of this interim gate, listed
        alongside the fence and HTML-block routes in the class docstring: either
        could duplicate a declared id without this gate seeing it. Earlier
        versions of this comment claimed an inline anchor does not render and
        that a level-3 heading's slug differs — both false, and both the
        renderer-modelling mistake the reduction exists to stop making (Sol,
        PR #60).
        """
        self.assertEqual({}, self.sources('text <a id="d-81"></a> more text\n'),
                         "only a standalone anchor is a declaration by this convention")
        self.assertEqual({}, self.sources("### D-81\n"),
                         "only a level-2 heading declares a decision by this convention — a "
                         "level-3 heading renders and owns the same short slug, and is an "
                         "accepted blind spot")
        self.assertEqual({}, self.sources("## D-81 — a title\n"),
                         "a titled heading's own slug is its full title, not the short id")
        self.assertEqual({"D-81": ["bare heading slug"]}, self.sources("## D-81\n"))
        self.assertEqual({"D-81": ["explicit anchor"]}, self.sources('<a id="d-81"></a>\n'))

    def test_every_authored_fragment_is_a_real_short_id(self):
        """Links are constrained instead of targets being modelled.

        Every fragment in this document is the short form today, so requiring
        that is exact — and it removes the need to derive a full heading slug,
        which is the derivation that was wrong in six different ways.
        """
        doc = self.DOC.read_text(encoding="utf-8")
        wrong = self.bad_fragments(doc, set(self.sources(doc)))
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
            inbound += len(re.findall(r'necb_decisions\.md#([^)\s"\']+)', text))
        self.assertGreaterEqual(
            inbound, 1,
            "main-red's incident body links into the decision log; finding zero inbound "
            "links means the tree scan is broken")

    def test_no_declaration_is_hidden_in_a_comment(self):
        """F2's realistic route, closed by a literal whitelist.

        A declaration inside a multi-line HTML comment is counted as live by
        every raw-source scan here and by the sync test, so commenting out an
        entry leaves `#d-NN` dead with all tests green. Rather than model HTML
        blocks — the modelling that cost seven rounds — this asserts the only
        comment markers in the document are the TOC's two (Fable, PR #60).
        """
        # Matched by SHAPE, not by the marker's prose: the generator owns that
        # string and may reword it (it still says `.rb`, from before the port).
        self.assertEqual([], self.hidden_declaration_risk(
            self.DOC.read_text(encoding="utf-8")))

    def test_a_third_comment_marker_is_caught(self):
        """The marker guard's own negative. Read against the live document only,
        its clauses could not fail — mutating the count to a tautology left every
        test green, because the other clauses still held."""
        hidden = ('<!-- TOC BEGIN -->\n<!-- TOC END -->\n\n'
                  '<!--\n<a id="d-81"></a>\n\n## D-81\n-->\n')
        self.assertNotEqual([], self.hidden_declaration_risk(hidden),
                            "a comment hiding a declaration adds markers, and that is what "
                            "the live-document guard refuses")
        self.assertEqual([], self.hidden_declaration_risk(
            "<!-- TOC BEGIN (x) -->\n<!-- TOC END -->\n"),
            "and the TOC's own two markers stay legal, or the document is unwritable")
        # Isolates the COUNT clause. The multi-line case above is also caught by
        # the well-formedness clause, so on its own it could not falsify the
        # count; three tidy single-line comments can only fail on the count.
        self.assertNotEqual([], self.hidden_declaration_risk(
            "<!-- TOC BEGIN -->\n<!-- TOC END -->\n<!-- a stray note -->\n"),
            "a third well-formed comment is still a place a declaration could be hidden")
        # Isolates the WELL-FORMEDNESS clause, which guards a real dead link.
        # Exactly two markers, both TOC-named, so the count and name clauses
        # both pass — while GitHub renders the whole span as `<p>after</p>` and
        # `sources()` still reports D-81 from inside it. Only this clause caught
        # it, and nothing could tell if it were deleted (Fable, PR #60).
        spanning = '<!-- TOC BEGIN\n<a id="d-81"></a>\n\n## D-81\nTOC END -->\n\nafter\n'
        self.assertEqual(2, len(self.comment_markers(spanning)),
                         "the count and name clauses cannot see this one")
        self.assertNotEqual([], self.hidden_declaration_risk(spanning),
                            "a comment opening on one line and closing on another spans the "
                            "declaration between them, which renders as nothing")
        # Isolates the NAME clause.
        self.assertNotEqual([], self.hidden_declaration_risk(
            "<!-- something else -->\n<!-- and another -->\n"),
            "two well-formed comments that are not the TOC's are not this document's")
        self.assertEqual(["D-81"], sorted(self.sources(hidden)),
                         "and the raw scan still counts the hidden declaration as live, which "
                         "is exactly the dead link the guard exists to prevent")

    @classmethod
    def unresolved_inbound(cls, text, declared):
        """Inbound decision-log fragments that name no declared id.

        A classmethod so the negative below exercises the SAME predicate the
        tree scan uses. Dropping the membership test survived 15/15 before this
        existed: the vacuity floor proved the regex finds a link, not that a bad
        one is rejected (Fable, PR #60).
        """
        found = re.findall(r"necb_decisions\.md#([^)\s\x22\x27]+)", text)
        return sorted({f for f in found if f.upper() not in declared})

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
