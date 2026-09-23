"""Recompute the NECB 8.4 scanner's per-``(edition, article, kind)`` citation-site
counts, by driving ``python/scripts/generate_necb_8_4_coverage.py``'s own
``CoverageGenerator``/``Inputs`` classes rather than reimplementing its citation
logic.

This backs the no-loss gate in ``tests/test_citation_no_loss.py`` and is kept
importable on its own (``from tests.citation_counts import
compute_citation_counts``) so a deliberate re-baseline can call it directly
without going through the test runner.

``kind`` is exactly the scanner's own classification of a citation call site —
today ``python_call_kind`` in the generator recognises only two values,
``"cited"`` (an ``audit.decision``/``audit.info`` style call) and ``"warn"``
(an ``audit.warn``/``audit.warning`` call). There is no separate "info" vs
"decision" split in the scanner itself, so this module records the two kinds
the scanner actually produces rather than the three-way informal description
("decision / warning / info") used when describing the intent — see the
``kinds`` provenance field below.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "python" / "scripts" / "generate_necb_8_4_coverage.py"
BASELINE_PATH = Path(__file__).with_name("data") / "citation_counts_baseline.json"

#: Editions the scanner resolves citations for today (``edition_part``'s own
#: loop in ``generate_necb_8_4_coverage.py:render``).
EDITIONS = ("2020", "2025")


def load_coverage_module() -> ModuleType:
    """Import ``generate_necb_8_4_coverage.py`` by file path (it is a script, not
    a package member) the same way ``tests/test_generate_necb_8_4_coverage.py``
    already does, so both share one loading convention."""
    spec = importlib.util.spec_from_file_location("generate_necb_8_4_coverage", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def compute_citation_counts(coverage_module: ModuleType | None = None) -> dict:
    """Return ``{edition: {article: {kind: count}}}``.

    Drives the scanner's own ``CoverageGenerator.citations_for(edition,
    articles)`` — the exact citation resolution ``edition_part`` uses to build
    the coverage document — for each edition in ``EDITIONS``. Each citation
    site the scanner records for an article contributes one count to that
    site's ``kind``.
    """
    coverage = coverage_module or load_coverage_module()
    generator = coverage.CoverageGenerator(coverage.Inputs())
    counts: dict[str, dict[str, dict[str, int]]] = {}
    for edition in EDITIONS:
        articles = json.loads(
            generator.inputs.caches[edition].read_text(encoding="utf-8")
        )["articles"]
        citations = generator.citations_for(edition, articles)
        edition_counts: dict[str, dict[str, int]] = {}
        for article, sites in citations.items():
            kind_counts: dict[str, int] = {}
            for site in sites:
                kind = site["kind"]
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
            edition_counts[article] = kind_counts
        counts[edition] = edition_counts
    return counts


def load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


#: Companion baseline for the citations the Section 8.4 scanner cannot see.
FOREIGN_BASELINE_PATH = Path(__file__).with_name("data") / "foreign_citation_counts_baseline.json"

#: The scanner's own token shape, used ONLY to find what is left of a literal
#: once the 8.4 gate's share of it is removed — never to decide whether a site
#: is gated. That decision comes from the gate itself (``_resolved_sites``).
#: Anchored on the left, unlike the scanner's own copy: bare ``8\.4`` also
#: matches inside ``5.2.8.4.``, which would read a Part 5 article as a Section
#: 8.4 one. The scanner has that bug; this must not inherit it, or such a
#: citation would look gated here while resolving to nothing there.
_EIGHT_FOUR = re.compile(r"(?<![\d.])(?:PREFIX|8\.4)(?:\.\d+)*\.?(?:\(\d+\))?")

#: An article-shaped reference, e.g. ``5.2.6.3`` or ``4.2.2.1``.
_ARTICLE_SHAPE = re.compile(r"\d+\.\d+\.\d+")

#: Product source carrying ``article=`` citations. Wider than the 8.4
#: generator's glob (``btap/codes``) because ``btap/costing`` cites articles
#: too, and nothing was watching those at all.
SOURCE_GLOB = "btap/**/*.py"


def _resolved_sites(coverage_module: ModuleType) -> set[tuple[str, int]]:
    """Every ``(file, line)`` the Section 8.4 gate actually counts.

    Asking the gate is not the same as re-deriving its scan-time regex. The
    scanner records a site if the literal yields an 8.4-shaped token, but the
    BASELINE only counts what ``citations_for`` then resolves onto a real
    article id — and nothing guarantees those two sets stay equal. Deriving the
    complement from the gate's own output means no hole can open between them,
    and there is no copied predicate to drift.
    """
    generator = coverage_module.CoverageGenerator(coverage_module.Inputs())
    sites: set[tuple[str, int]] = set()
    for edition in EDITIONS:
        articles = json.loads(
            generator.inputs.caches[edition].read_text(encoding="utf-8")
        )["articles"]
        for entries in generator.citations_for(edition, articles).values():
            for entry in entries:
                sites.add((entry["file"], entry["line"]))
    return sites


def _stable_key(source: str, node: ast.expr) -> str:
    """A key for a dynamically built ``article=`` that is the SAME string on
    every supported Python.

    ``ast.unparse`` cannot be used: it re-renders the expression in the running
    interpreter's syntax, so an f-string key authored on 3.12 (PEP 701 lets a
    nested quote match the outer one) is not the key 3.11 emits, and a baseline
    written on one fails on the other. That shipped, and CI's 3.11 job caught it.

    The source slice has no such problem — it is the file's own bytes — but it
    depends on the node's recorded position, and 3.11 records f-string
    positions less precisely than 3.12. So the slice is USED only when it
    round-trips: re-parsing it must rebuild the same tree. When it does not,
    the structural dump is the fallback, which is uglier to read in a baseline
    but identical across versions because PEP 701 changed the tokenizer, not
    the AST shape.
    """
    segment = ast.get_source_segment(source, node)
    if segment:
        try:
            # Parenthesised because a slice taken from inside a call's argument
            # list can span lines, and those continuations were legal only
            # because of the enclosing parentheses the slice does not include.
            if ast.dump(ast.parse(f"({segment})", mode="eval").body) == ast.dump(node):
                return segment
        except SyntaxError:
            pass
    return ast.dump(node)


def _foreign_content(literal: str) -> bool:
    """Does this literal say anything the 8.4 gate does not account for?

    True when it carries no 8.4 token at all, and also when an article-shaped
    reference SURVIVES removing the 8.4 tokens — ``'8.4.4.12.; 5.2.2.7.(1)'``
    is counted by the 8.4 gate under 8.4.4.12, so deleting the ``5.2.2.7.(1)``
    half used to fire nothing anywhere.
    """
    probe = literal.replace("{prefix}", "PREFIX")
    if not _EIGHT_FOUR.findall(probe):
        return True

    return bool(_ARTICLE_SHAPE.search(_EIGHT_FOUR.sub("", probe)))


def compute_foreign_citation_counts(source_root: Path | None = None) -> dict:
    """Citation sites the Section 8.4 no-loss gate does NOT cover (DF-15).

    That gate counts a citation only if its literal resolves onto an article in
    an edition's ``articles_8_4.json``, and the generator *raises* on non-8.4
    content in those caches — so Part 4, Part 5 and Part 6 citations are dropped
    at scan time and could be deleted without failing anything. Measured when
    this was written, at SITE level: the 8.4 gate covers 105 distinct source
    sites and this one covers 178 — about 62 % of the citation surface was
    ungated. (The 8.4 baseline's total of 213 is a PER-EDITION count of those
    same 105 sites, 96 for 2020 plus 117 for 2025. Comparing it against a
    per-site figure understates the gap, and the first draft of this gate did
    exactly that.) Not all of the 178 are Part 4/5/6: about 20 are variables
    bound to 8.4 f-strings and three are the data-driven coverage emitter in
    ``btap/audit``, so the honest description is "sites the 8.4 scanner cannot
    count".

    Two populations, because they can be keyed with different confidence.

    ``static`` — a plain string literal, keyed by ``{literal: {kind: count}}``.
    Exact and meaningful: ``5.2.6.3.(1)`` losing a site is named in the failure.
    No file path enters the key, so a rename cannot invalidate the baseline —
    the same rule the 8.4 baseline follows.

    ``dynamic`` — everything else, keyed by ``{ast.unparse(node): {kind: count}}``.
    An ``article=`` that is a variable, a subscript or an f-string the scanner
    cannot fold to a name has no literal to key on, but it does have the source
    expression that produced it: ``article``, ``spec['article']``,
    ``f'{article}(4)'``. That is the code's own text, not the scanner's
    truncated rendering of it (``f'{ruleset.article(x)}.(2)(b)'`` renders as the
    fragment ``'.(2)(b)'``, which appears in no audit and would be a dishonest
    key). Keying rather than merely counting matters because a bare total is
    blind to a swap: delete one dynamic citation, add an unrelated one, and the
    total is unchanged — and the 8.4 baseline moved 209 -> 211 -> 213 across two
    consecutive days, so that is ordinary churn here, not a hypothetical.
    """
    coverage = load_coverage_module()
    root = source_root or (REPO_ROOT / "python")
    # The gate's own coverage, asked once. A caller probing a throwaway copy of
    # the source gets the same answer for the paths that still exist, which is
    # what makes the deletion experiment meaningful.
    gated = _resolved_sites(coverage)
    static: dict[str, dict[str, int]] = {}
    dynamic: dict[str, dict[str, int]] = {}

    for path in sorted(root.glob(SOURCE_GLOB)):
        try:
            relative = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:  # a temp-directory copy, used by the mutation tests
            relative = f"python/{path.relative_to(root).as_posix()}"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            for keyword in call.keywords:
                if keyword.arg != "article":
                    continue
                node = keyword.value
                is_literal = isinstance(node, ast.Constant) and isinstance(node.value, str)
                rendered = node.value if is_literal else coverage.python_citation_value(node)

                # Membership in the real gate decides first; content only decides
                # whether a GATED site also needs guarding here. Classifying by
                # content alone discarded every gated dynamic site wholesale, so
                # the foreign half of f'5.2.6.3.(1); {prefix}.1.(2)' — D-38's own
                # clamp citation — could be deleted with nothing moving.
                if (relative, node.lineno) in gated:
                    if rendered is None or not _foreign_content(rendered):
                        continue

                kind = coverage.python_call_kind(call)
                if is_literal:
                    bucket, key = static, node.value
                else:
                    bucket, key = dynamic, _stable_key(source, node)
                bucket.setdefault(key, {}).setdefault(kind, 0)
                bucket[key][kind] += 1

    return {"static": static, "dynamic": dynamic}


def load_foreign_baseline() -> dict:
    return json.loads(FOREIGN_BASELINE_PATH.read_text(encoding="utf-8"))


DATA_BASELINE_PATH = Path(__file__).with_name("data") / "data_citation_counts_baseline.json"

#: Packaged product DATA, wider than either edition snapshot because a family
#: -neutral file that later grows an ``article`` key must land somewhere
#: explicit rather than silently outside the gate.
DATA_GLOB = "btap/**/data/**/*.json"


def _data_scope(relative: str) -> str:
    """Which snapshot OWNS this data file.

    Scoping is the whole point rather than a tidy label: a repository-wide
    total is blind to the commonest real regression here, a value deleted from
    one edition while the other keeps it (or gains an unrelated one). Both
    gates beside this one key by edition for the same reason.
    """
    match = re.search(r"btap/codes/necb/data/([^/]+)/", relative)
    if match:
        return match.group(1)
    if "btap/codes/data/" in relative:
        # decisions.json, the 8.4 disposition, ATTRIBUTION — deliberately
        # code-family-neutral (see btap/codes/CLAUDE.md), so they get one
        # shared scope rather than being attributed to an edition.
        return "shared"
    raise ValueError(
        f"cannot attribute {relative} to a data scope — teach _data_scope "
        "before adding article-bearing data outside the edition snapshots")


#: Data keys whose value is EMITTED as an ``article=`` citation, not merely
#: documented next to one. ``trigger_article`` reaches the audit verbatim from
#: ``checker.py`` and ``energy_recovery.py``; guarding only ``article`` left
#: four of the twenty-four subscript sites open, which is exactly the
#: population this gate exists to close (Fable, PR #56).
#:
#: Deliberately NOT included, because nothing emits them: ``table_article``,
#: ``effectiveness_article``, ``overshoot_article``, ``reference_article``,
#: ``default_category_article``. Guarding documentation would churn this
#: baseline for edits that cannot change a single audit entry.
EMITTED_ARTICLE_KEYS = ("article", "trigger_article")

#: Data keys that LOOK like citations and are not: nothing in product source
#: reads them, and their values are prose rather than article ids. Excluded
#: deliberately, because guarding documentation would churn this baseline on
#: wording edits that cannot move a single audit entry.
#:
#: ``test_the_documentary_key_exclusion_is_still_true`` keeps this list honest.
#: An unchecked exclusion is precisely how the ``trigger_article`` hole opened:
#: a key was assumed not to be emitted, and nothing failed when it was.
DOCUMENTARY_ARTICLE_KEYS = (
    "table_article",
    "effectiveness_article",
    "overshoot_article",
    "reference_article",
    "default_category_article",
)


def _article_values(node, found: list[str], *, where: str = "") -> None:
    """Every data value that reaches an audit as an article citation.

    The key NAME, never the shape of the string: prose that happens to contain
    an article number is not a citation, and an article-shaped string under
    some other key is not one either. Matching on shape instead was measured
    and discarded: excluding docstrings, ``article=`` arguments themselves and
    fragments inside other f-strings, 116 article-shaped constants remain in
    product source, and they are version strings, report prose and headings. A
    gate over those would churn constantly and mean nothing.

    Three shapes, because the product emits three:

    - ``"article": "8.4.5.2."`` — the common case, read by ``spec["article"]``;
    - ``"trigger_article": "5.2.2.9."`` — read the same way, different key;
    - a manifest's ``"articles"`` MAPPING, whose values reach the audit through
      ``ruleset.article(key)``. That registry is the miniature of what DF-16
      ultimately wants everywhere, so leaving it unguarded would be perverse.

    A non-string under an emitted key RAISES rather than being skipped. Skipping
    is a hole that opens quietly: the value stops being counted, the baseline is
    re-recorded without it at the next re-baseline, and it is unguarded forever
    with every test green.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key in EMITTED_ARTICLE_KEYS:
                if not isinstance(value, str):
                    raise TypeError(
                        f"{where}: {key!r} holds {type(value).__name__}, not str — "
                        "teach this gate the new shape rather than letting it "
                        "silently stop counting the value")
                found.append(value)
            elif key == "articles" and where == "manifest.json":
                # A manifest's key -> article-id registry, whose values reach
                # the audit through ``ruleset.article(key)``.
                #
                # Restricted to the manifest by NAME rather than by shape. A
                # bare ``key == "articles" and isinstance(value, dict)`` also
                # matches both ``articles_8_4.json`` caches (52 and 57
                # dict-valued entries), which contribute nothing only because a
                # value-type filter drops them — reintroducing, one branch
                # below the raise, exactly the silent skip that raise exists to
                # forbid (Fable, PR #56).
                if not isinstance(value, dict):
                    raise TypeError(
                        f"{where}: 'articles' holds {type(value).__name__}, not a "
                        "key -> article-id mapping")
                for registry_key, registry_value in value.items():
                    if not isinstance(registry_value, str):
                        raise TypeError(
                            f"{where}: articles[{registry_key!r}] holds "
                            f"{type(registry_value).__name__}, not str — teach this "
                            "gate the new shape rather than letting it silently "
                            "stop counting the value")
                    found.append(registry_value)
            else:
                _article_values(value, found, where=where)
    elif isinstance(node, list):
        for item in node:
            _article_values(item, found, where=where)


def compute_data_citation_counts(source_root: Path | None = None) -> dict:
    """Article citations that live in packaged DATA, not in Python (DF-16).

    Both gates beside this one scan ``article=`` keyword arguments in Python.
    Neither reads the rule files, so the ~24 sites that cite through a
    subscript (``spec["article"]``, ``rule['article']``) are keyed by the
    EXPRESSION, and the value they actually emit can be edited or deleted with
    nothing moving anywhere. Measured on this tree: 311 ``article`` values
    across 14 files, 213 distinct — and a mutation of any one of them was
    invisible to the 8.4 gate, the foreign gate, the generated coverage
    document and all 45 frozen scenario baselines.

    Keyed ``{scope: {article value: count}}``. No file path enters the key, so
    a rename inside a snapshot cannot invalidate the baseline — the rule the
    other two gates follow — while the scope keeps edition ownership, so a
    2020 deletion masked by a 2025 addition still fails.

    This closes the DATA half of DF-16 and nothing else. DF-16 stays open for
    Python value flow: every citation whose ``article=`` expression is guarded
    while the value reaching it can change upstream.

    That residual is NOT "values the scanner cannot resolve". An earlier
    version of this docstring said so, on a measurement that folded only
    ``ast.Constant`` and resolved 1 of the 38 variable sites. Folding to the
    assignment's SOURCE EXPRESSION instead — the key shape the foreign gate
    already uses — resolves 13 of 38 with no interprocedural work, and most of
    the 18 parameter sites have a same-module caller passing an f-string
    (Fable, PR #56). So a narrower static approach is tractable; it is simply
    not this increment, and the honest reason to defer it is blast radius, not
    impossibility.
    """
    root = source_root or (REPO_ROOT / "python")
    counts: dict[str, dict[str, int]] = {}
    for path in sorted(root.glob(DATA_GLOB)):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        found: list[str] = []
        _article_values(blob, found, where=path.name)
        if not found:
            # Scope is resolved only for files that actually cite, so an
            # unrelated data directory never has to be taught to this gate.
            continue
        try:
            relative = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:  # a temp-directory copy, used by the mutation tests
            relative = f"python/{path.relative_to(root).as_posix()}"
        scope = _data_scope(relative)
        for value in found:
            counts.setdefault(scope, {}).setdefault(value, 0)
            counts[scope][value] += 1
    return counts


def article_named_data_keys(source_root: Path | None = None) -> set[str]:
    """Every key in product DATA that is ``article`` or ends ``_article``.

    The taxonomy the two fixed tuples are checked against. Listing keys as
    emitted or documentary proves something about the keys ALREADY listed; it
    proves nothing about a key nobody has thought about yet, which is exactly
    how ``trigger_article`` went unguarded — a key was never classified, so
    nothing failed when it turned out to be emitted (Sol, PR #56).

    The manifest ``articles`` registry is deliberately outside this set: it is
    a separately named container, handled by its own branch, and its key is
    neither ``article`` nor ``*_article``.
    """
    root = source_root or (REPO_ROOT / "python")
    keys: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "article" or key.endswith("_article"):
                    keys.add(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in sorted(root.glob(DATA_GLOB)):
        try:
            walk(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return keys


def load_data_baseline() -> dict:
    return json.loads(DATA_BASELINE_PATH.read_text(encoding="utf-8"))
