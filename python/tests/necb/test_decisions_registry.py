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
        "D-11 — 8.4.4.14 Hydronic Pumps implemented (intensity transfer + Table curves)":
            "d-11--84414-hydronic-pumps-implemented-intensity-transfer--table-curves",
        "D-93 — The reference pump's value source: correspondence, then the sentence that governs it":
            "d-93--the-reference-pumps-value-source-correspondence-then-the-sentence-that-governs-it",
        # Non-ASCII, because the other three pin only ASCII punctuation and the
        # em-dash bug proved this rule's weak point is exactly what it does with
        # characters it does not expect (Fable, PR #60).
        "D-58 — The proposed\u2192reference matrix (97 catalog systems): residential compatible-cooling and HP detection go fact-based":
            "d-58--the-proposedreference-matrix-97-catalog-systems-residential-compatible-cooling-and-hp-detection-go-fact-based",
    }

    #: ``](#x)``, ``[x]: #x`` and ``href="#x"`` all render as links; matching
    #: only the first let a reference-style definition through (Fable, PR #60).
    LINK = re.compile(r'(?:\]\(|\]:[ \t]*|href=")#([^)\s"]+)')

    #: Any declared anchor, however spelled. GitHub's sanitiser rewrites BOTH
    #: ``id`` and ``name`` to ``user-content-…``, and browsers resolve a
    #: fragment to ``a[name]`` too, so a gate that reads only ``id="…"`` at
    #: line start misses single quotes, a trailing space, indentation,
    #: ``<a id="d-81"/>`` and ``<a name="d-81">`` — each of which still renders
    #: a live duplicate (Fable, PR #60).
    #: ANY element, not just ``<a>``: GitHub keeps ``<div id="d-81">`` as
    #: ``id="user-content-d-81"`` too, and any rendered element id can collide
    #: with a heading's (Sol, PR #60).
    ANCHOR = re.compile(r'^<a id="([^"]+)"></a>$')

    #: An ``id``/``name`` attribute carrying a short decision id, in ANY
    #: spelling and ANY context — inline code, indented code, a fence, a
    #: comment, a ``<div>``.
    SHORT_ID_ATTR = re.compile(r"""(?:id|name)\s*=\s*["']?(d-\d+)""", re.I)

    #: An ATX heading at column zero: the only heading form this document is
    #: allowed to use. ``ATX_ANYWHERE`` is deliberately looser — it matches the
    #: indented and blockquoted forms GitHub also renders, so the grammar check
    #: can REJECT them rather than the model having to simulate them.
    ATX = re.compile(r"^(#{1,6}) +(.+?) *#* *$")
    #: The REJECTION surface, deliberately broader than any form this gate
    #: models. A heading marker may sit behind any mix of indentation,
    #: blockquote markers and LIST markers — GitHub renders `- ## D-93` inside
    #: an `<li>` as a real heading, and it then owns the natural `d-93` slug
    #: while the explicit anchor declares the same id (Sol, PR #60). The
    #: positive grammar stays column-zero ATX; this only has to be wide enough
    #: that an unmodelled rendered heading cannot take the first slug.
    #:
    #: The trailing `[ \t]+\S` is what keeps prose safe: `- #d-81 resolves` and
    #: `PR #53` have no space after the hashes, so neither is a heading marker.
    ATX_ANYWHERE = re.compile(r"^(?:[ \t]*(?:[-*+]|\d{1,9}[.)]|>)[ \t]*)*[ \t]*#{1,6}[ \t]+\S")
    #: A Setext underline, behind any blockquote nesting. Indentation and `>`
    #: are allowed because they CONTINUE the paragraph above; a LIST marker is
    #: deliberately not, because `- ----` opens a new list item and is a
    #: thematic break rather than an underline for the previous one. The
    #: unprefixed form alone let `> D-93` / `> ----` render a blockquoted
    #: heading that took the short slug (Sol, PR #60).
    #: A dash/equal-only line at ANY indentation, behind any blockquote nesting.
    #: A nested list's continuation indent can be four or more spaces, so the
    #: three-space bound called `- outer` / `  - D-93` / `    ----` clean while
    #: GitHub rendered the nested item as `<h2>D-93</h2>` (Sol, PR #60).
    #:
    #: Deliberately conservative rather than parsing nested lists: an indented
    #: or container-prefixed thematic rule is simply illegal in this document.
    #: The three forms that stay legal are pinned as positive tests — a
    #: TOP-LEVEL rule after a blank line, a quoted rule after a quoted blank,
    #: and a table separator. `- ----` also stays legal, because a list marker
    #: opens a new item and GitHub renders it `<hr>`.
    SETEXT_RULE = re.compile(r"^(?:[ \t]*>)*[ \t]*(=+|-+)[ \t]*$")

    #: Blockquote markers and indentation, stripped to reach a line's content.
    BQ_PREFIX = re.compile(r"^(?:[ \t]{0,3}>)*[ \t]*")

    @classmethod
    def fenced(cls, lines) -> list:
        """Per-line ``True`` inside a fenced code block, by CommonMark's actual
        rule: the closing fence is the same character, at least as long as the
        opener, and carries no info string.

        :return: (per-line inside-a-fence mask, whether a fence was left open)

        The previous version back-referenced the exact opening delimiter, so a
        longer closing fence — which CommonMark permits and GitHub honours —
        left the block open and its contents visible to the scanners (Sol,
        PR #60).
        """
        mask, fence = [], None
        for line in lines:
            match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            if fence is None:
                # An opening backtick fence may not carry a backtick in its
                # info string; that is inline code, not a fence.
                if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
                    fence = match.group(1)
                    mask.append(True)
                    continue
                mask.append(False)
            else:
                if (match and match.group(1)[0] == fence[0]
                        and len(match.group(1)) >= len(fence)
                        and not match.group(2).strip()):
                    fence = None
                mask.append(True)
        return mask, fence is not None

    @classmethod
    def grammar_violations(cls, doc: str) -> list:
        """Where the document leaves the canonical form this gate depends on.

        Three rounds of this review were spent teaching a regex which Markdown
        contexts GitHub does and does not render — fences, comments, inline
        code, indented code, blockquotes, Setext, longer closing fences — and
        each round left the same class open, because the gate was simulating a
        CommonMark parser it does not have (Sol, PR #60).

        So the document is CONSTRAINED instead. Under these three rules there is
        exactly one place a ``d-NN`` target can come from, and correctness stops
        depending on context analysis:

        1. A ``d-NN`` id may appear ONLY as ``<a id="d-nn"></a>`` alone on its
           line at column zero, immediately above its own ``## D-NN`` heading.
           This rule is CONTEXT-FREE — an anchor commented out, put in a fence,
           or wrapped in backticks is a violation, not a silently-dead target,
           which is precisely the false green that survived every earlier fix.
        2. Headings are ATX at column zero. Indented, blockquoted and Setext
           headings are rejected rather than modelled.
        3. Fences are balanced, so the heading walk's exclusions are sound.
        """
        lines = doc.splitlines()
        mask, open_fence = cls.fenced(lines)
        problems = []
        if open_fence:
            # An unterminated fence would silently swallow the tail of the file,
            # so the heading walk's exclusions could not be trusted.
            problems.append("unterminated code fence: the heading walk cannot be trusted")

        for number, line in enumerate(lines, start=1):
            found = cls.SHORT_ID_ATTR.search(line)
            if found:
                canonical = cls.ANCHOR.match(line)
                if not canonical or canonical.group(1) != found.group(1):
                    problems.append(
                        f"line {number}: a d-NN id must be exactly "
                        f'`<a id="{found.group(1)}"></a>` alone on its line; got {line.strip()!r}')
                else:
                    heading = lines[number + 1] if number + 1 < len(lines) else ""
                    blank = lines[number] if number < len(lines) else ""
                    want = found.group(1).upper()
                    if blank.strip() or not heading.startswith(f"## {want}"):
                        problems.append(
                            f"line {number}: anchor {found.group(1)} must be followed by a blank "
                            f"line and then `## {want}`; got {heading.strip()[:40]!r}")
            if mask[number - 1]:
                continue
            if cls.ATX_ANYWHERE.match(line) and not cls.ATX.match(line):
                problems.append(
                    f"line {number}: headings must be ATX at column zero, not indented or "
                    f"blockquoted; got {line.strip()[:40]!r}")
            previous = cls.BQ_PREFIX.sub("", lines[number - 2]) if number >= 2 else ""
            if (number >= 2 and cls.SETEXT_RULE.match(line) and previous.strip()
                    and not mask[number - 2] and not previous.startswith("|")):
                problems.append(
                    f"line {number}: Setext heading; use ATX so the slug model stays exact")
        return problems

    @staticmethod
    def slug(heading: str) -> str:
        """GitHub's heading-anchor rule: lowercase, drop punctuation, then one
        hyphen PER SPACE — an em-dash leaves two spaces and so two hyphens."""
        text = heading.strip().lower()
        text = re.sub(r"[^\w\s-]", "", text)
        return re.sub(r"\s", "-", text)

    @classmethod
    def heading_slugs(cls, doc) -> list:
        """Every heading's rendered slug, in document order, with GitHub's
        ``-1``/``-2`` suffix on a repeat. The single source of truth for what a
        heading resolves to; both ``targets()`` and ``short_id_sources()`` walk
        it rather than each carrying a pattern of its own.

        Only column-zero ATX headings outside fences, which
        ``grammar_violations`` guarantees are the only headings present.
        """
        lines = doc.splitlines()
        mask, _ = cls.fenced(lines)
        seen: dict = {}
        slugs = []
        for number, line in enumerate(lines):
            match = cls.ATX.match(line)
            if match is None or mask[number]:
                continue
            base = cls.slug(match.group(2))
            count = seen.get(base, 0)
            slugs.append(base if count == 0 else f"{base}-{count}")
            seen[base] = count + 1
        return slugs

    @classmethod
    def targets(cls, doc=None) -> set:
        """Every fragment the page offers: heading anchors AND declared ids.

        Headings at all six levels, with GitHub's ``-1``/``-2`` suffix on a
        repeated slug. Modelling only unique ``##`` headings made the gate
        reject VALID links to the 40 level-3 headings here (Sol, PR #60).
        """
        doc = cls.DOC.read_text(encoding="utf-8") if doc is None else doc
        lines = doc.splitlines()
        mask, _ = cls.fenced(lines)
        found = {m.group(1) for number, line in enumerate(lines)
                 if not mask[number] and (m := cls.ANCHOR.match(line))}
        found.update(cls.heading_slugs(doc))
        return found

    def test_the_slug_rule_reproduces_live_github_anchors(self):
        """Non-vacuity, against anchors fetched from the rendered page rather
        than derived here. My first rule collapsed the em-dash's two spaces
        into one hyphen and rewrote every link self-consistently wrong; only a
        comparison with a real anchor caught it."""
        doc = self.DOC.read_text(encoding="utf-8")
        for heading, anchor in self.LIVE_ANCHORS.items():
            with self.subTest(heading=heading[:24]):
                # The fixture must be the REAL heading, not a plausible one.
                # Its D-11 key carried a colon the heading does not have; the
                # slug rule folds case and drops punctuation, so it produced
                # the right anchor from a heading that does not exist and the
                # non-vacuity claim was hollow (Sol, PR #60).
                self.assertIn(f"## {heading}\n", doc,
                              "LIVE_ANCHORS claims a rendered heading; it must be the exact "
                              "heading in the document, or the comparison proves nothing")
                self.assertEqual(anchor, self.slug(heading))

    @classmethod
    def short_id_sources(cls, doc):
        """Where each ``d-NN`` fragment comes from: explicit anchors and the
        natural slugs of bare ``## D-NN`` headings, as a list per id so a
        DUPLICATE is visible.

        A set would hide the defect this models. Fourteen entries (D-76..D-89)
        have bare headings whose own GitHub slug is already ``d-81`` and so on,
        so adding an explicit anchor too put TWO elements with
        ``id="user-content-d-81"`` in the rendered DOM. The links happened to
        land because the two sit adjacent, but a duplicate HTML id makes the
        fragment target ambiguous and undercuts the identity invariant this
        gate exists to assert (Sol, PR #60).
        """
        sources = {}
        lines = doc.splitlines()
        mask, _ = cls.fenced(lines)
        for number, line in enumerate(lines):
            match = cls.ANCHOR.match(line)
            if match and not mask[number] and SHORT_ID.fullmatch(match.group(1)):
                sources.setdefault(match.group(1).upper(), []).append("explicit anchor")
        # The heading side comes from the SAME walk `targets()` uses, not a
        # second narrower pattern. A private `^##\s+(D-\d+)\s*$` model missed
        # every heading that still slugs to a short id by another route — a
        # level-3 `### D-95`, a trailing period (`## D-81.`, punctuation is
        # dropped exactly as `8.4.4.14` becomes `84414`) — and the anchor side
        # missed single quotes, a trailing space, indentation, `<a id="d-81"/>`
        # and `<a name=...>`, all of which the sanitiser still renders as
        # `user-content-d-81`. Seven such edits produced a duplicate rendered id
        # and passed. Three rounds on this branch were each a model narrower
        # than the thing it checks; this is the fourth, so the two models are
        # now one (Fable, PR #60).
        for slug in cls.heading_slugs(doc):
            if SHORT_ID.fullmatch(slug):
                sources.setdefault(slug.upper(), []).append("heading slug")
        return sources

    def test_every_decision_entry_resolves_by_short_id_exactly_once(self):
        """Each registry id is reachable at ``#d-NN`` — and from ONE source.

        Explicit anchors carry the 81 entries whose heading is titled, because
        a titled heading's own slug is the full title and a rewording silently
        invalidates every link to it, including links outside this repository
        that no test can reach. The 14 bare headings already slug to their short
        id, so an explicit anchor there would only duplicate the DOM id.

        Retitling a bare heading later moves its natural slug off the short id.
        This test then fails, which is the point: the same change must add the
        explicit anchor, so the old short URL keeps working.
        """
        doc = self.DOC.read_text(encoding="utf-8")
        ids = {item["id"] for item in
               json.loads(REGISTRY.read_text(encoding="utf-8"))["decisions"]}
        sources = self.short_id_sources(doc)

        self.assertEqual(sorted(ids), sorted(sources),
                         "every registry id must be reachable at #d-NN, and nothing else may be")
        duplicated = {k: v for k, v in sources.items() if len(v) > 1}
        self.assertEqual({}, duplicated,
                         "these ids resolve from more than one source, so the rendered page "
                         f"carries duplicate element ids: {duplicated}")

    def test_a_duplicate_short_id_source_is_caught(self):
        """The negative case, because the set-based predecessor could not see
        it: an explicit anchor ON TOP of a bare heading is exactly the defect
        this PR shipped and must fail loudly."""
        sources = self.short_id_sources('<a id="d-81"></a>\n\n## D-81\n')
        self.assertEqual(["explicit anchor", "heading slug"], sources["D-81"],
                         "both sources are recorded, so the duplicate is visible")
        titled = self.short_id_sources('<a id="d-93"></a>\n\n## D-93 — a title\n')
        self.assertEqual(["explicit anchor"], titled["D-93"],
                         "a titled heading contributes no short-id slug, so its anchor is "
                         "the only source and is required")

    def test_the_log_conforms_to_the_canonical_grammar(self):
        """The keystone. Every other invariant in this class is exact only
        because the document is in this restricted form."""
        self.assertEqual([], self.grammar_violations(self.DOC.read_text(encoding="utf-8")))

    def test_the_grammar_rejects_every_context_a_regex_had_to_simulate(self):
        """Sol, PR #60 — and this is the point of constraining the document
        rather than parsing it.

        Each input below defeated a previous version of this gate. Three of
        them render NO live ``#d-81`` (GitHub removes the comment, escapes both
        code forms) while the raw-source scanners reported a live target; three
        DO render one, duplicating a heading id, while the column-zero scanners
        could not see them. Teaching a regex to tell those apart is writing a
        CommonMark parser badly, and each round left the same class open.

        Under the grammar they are all simply ILLEGAL, which needs no context
        analysis at all: a ``d-NN`` id exists in exactly one place or the
        document is rejected.
        """
        for label, doc in (
            ("commented-out anchor", '<!-- <a id="d-81"></a> -->\n\n## D-81\n'),
            ("fenced anchor", '```\n<a id="d-81"></a>\n```\n\n## D-81\n'),
            ("longer closing fence", '```\n<a id="d-81"></a>\n````\n\n## D-81\n'),
            ("inline-code anchor", '`<a id="d-81"></a>`\n\n## D-81\n'),
            ("indented-code anchor", '    <a id="d-81"></a>\n\n## D-81\n'),
            ("single-quoted anchor", "<a id='d-81'></a>\n\n## D-81\n"),
            ("trailing space", '<a id="d-81"></a> \n\n## D-81\n'),
            ("self-closing", '<a id="d-81"/>\n\n## D-81\n'),
            ("name= instead of id=", '<a name="d-81"></a>\n\n## D-81\n'),
            ("a non-anchor element", '<div id="d-81"></div>\n\n## D-81\n'),
            ("indented heading", '<a id="d-81"></a>\n\n   ## D-81\n'),
            ("blockquoted heading", '<a id="d-81"></a>\n\n> ## D-81\n'),
            ("Setext heading", '<a id="d-81"></a>\n\nD-81\n====\n'),
            # GitHub renders an ATX heading inside a list item, and it then owns
            # the natural short slug while the anchor declares the same id. The
            # rejection surface must cover every container prefix, not the
            # indent-and-blockquote pair I first assumed (Sol, PR #60).
            ("unordered-list heading",
             '- ## D-93\n\n<a id="d-93"></a>\n\n## D-93 — title\n'),
            ("ordered-list heading",
             '1. ## D-93\n\n<a id="d-93"></a>\n\n## D-93 — title\n'),
            ("nested-list heading",
             '  - ## D-93\n\n<a id="d-93"></a>\n\n## D-93 — title\n'),
            ("list inside a blockquote",
             '> - ## D-93\n\n<a id="d-93"></a>\n\n## D-93 — title\n'),
            # Setext behind a blockquote marker. GitHub's POST /markdown
            # returns `<blockquote><h2>D-93</h2></blockquote>`, so the quoted
            # heading owns the natural short slug while the anchor declares the
            # same id. The unprefixed underline rule could not see it, which is
            # the ATX list-prefix gap repeated on the other heading form
            # (Sol, PR #60).
            ("blockquoted Setext",
             '> D-93\n> ----\n\n<a id="d-93"></a>\n\n## D-93 — title\n'),
            ("Setext in a list in a blockquote",
             '> - D-93\n>   ----\n\n<a id="d-93"></a>\n\n## D-93 — title\n'),
            ("doubly nested blockquote Setext",
             '> > D-93\n> > ----\n\n<a id="d-93"></a>\n\n## D-93 — title\n'),
            # A nested list's continuation indent can exceed three spaces, so
            # the earlier bound called these clean while GitHub rendered the
            # nested item as `<h2>D-93</h2>` — verified with POST /markdown
            # (Sol, PR #60).
            ("nested-list Setext",
             '- outer\n  - D-93\n    ----\n\n<a id="d-93"></a>\n\n## D-93 — title\n'),
            ("deeper nested-list Setext",
             '- a\n  - b\n    - D-93\n      ----\n\n<a id="d-93"></a>\n\n## D-93 — t\n'),
            ("ordered nested Setext, six-space underline",
             '1. a\n   1. D-93\n      ------\n\n<a id="d-93"></a>\n\n## D-93 — t\n'),
            ("anchor detached from its heading", '<a id="d-81"></a>\n\ntext\n\n## D-81\n'),
        ):
            with self.subTest(case=label):
                self.assertNotEqual([], self.grammar_violations(doc),
                                    f"{label}: must be rejected by the grammar, not modelled")

    def test_the_canonical_form_itself_is_accepted(self):
        """Non-vacuity: a grammar that rejects everything would pass the test
        above while making the document unwritable."""
        self.assertEqual([], self.grammar_violations(
            '<a id="d-81"></a>\n\n## D-81 — a title\n\n## Not a decision\n'))
        self.assertEqual([], self.grammar_violations(
            "## D-81\n\n```\n# a shell comment inside a fence is not a heading\n```\n"),
            "fenced content is still allowed to contain anything but a d-NN id")
        # The rejection surface must not swallow ordinary prose. A hash with no
        # space after it is not a heading marker in any container.
        self.assertEqual([], self.grammar_violations(
            "## D-81\n\n- see #d-81 and PR #53 for the history\n"),
            "a bare #fragment or issue number in a list item is not a heading")
        # Ordinary horizontal rules must stay legal. Each was checked against
        # POST /markdown: all three render `<hr>` or plain text, never a
        # heading, so rejecting them would make the document unwritable while
        # fixing nothing (Sol, PR #60).
        for label, doc in (
            ("thematic break after a paragraph", "## D-81\n\nsome prose\n\n---\n"),
            ("thematic break inside a quote", "## D-81\n\n> quoted\n>\n> ---\n"),
            ("a new list item of dashes", "## D-81\n\n- item one\n- ----\n"),
            ("a table separator row", "## D-81\n\n| a | b |\n|---|---|\n"),
            # An INDENTED rule after a blank line is a thematic break, not an
            # underline — GitHub returns `<p>prose</p><hr>`. The rejection is
            # scoped to a rule that could underline nonblank content, which is
            # what Sol's wording asks for.
            ("an indented rule after a blank line", "## D-81\n\nprose\n\n  ---\n"),
        ):
            with self.subTest(allowed=label):
                self.assertEqual([], self.grammar_violations(doc), label)

    def test_a_repeated_heading_is_not_reported_as_a_duplicate_id(self):
        """GitHub suffixes a repeated slug, so two ``## D-81`` headings render
        ``d-81`` and ``d-81-1`` — distinct ids, not a collision. Calling that a
        duplicate element id would be the right alarm with the wrong diagnosis
        (Fable, PR #60); a repeated decision heading is the registry sync's
        business, and `test_decisions_registry_sync` is what fails on it."""
        sources = self.short_id_sources("## D-81\n\n## D-81\n")
        self.assertEqual(["heading slug"], sources["D-81"],
                         "only the FIRST resolves at #d-81; the second is #d-81-1")
        self.assertIn("d-81-1", self.targets("## D-81\n\n## D-81\n"),
                      "and the suffixed slug is still offered as a target")

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
        # -z, because plain `ls-files` output split on whitespace drops any
        # tracked path containing a space and mangles the quoted form git uses
        # for non-ASCII names — a real inbound link in such a file would never
        # be read (Fable, PR #60).
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
