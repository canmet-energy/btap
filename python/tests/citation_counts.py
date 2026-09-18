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

#: The scanner's own token shape. A citation matching it belongs to the 8.4
#: gate; everything else is this module's business.
_EIGHT_FOUR = re.compile(r"(?:PREFIX|8\.4)(?:\.\d+)*\.?(?:\(\d+\))?")

#: Product source carrying ``article=`` citations. Wider than the 8.4
#: generator's glob (``btap/codes``) because ``btap/costing`` cites articles
#: too, and nothing was watching those at all.
SOURCE_GLOB = "btap/**/*.py"


def compute_foreign_citation_counts(source_root: Path | None = None) -> dict:
    """Citation sites the Section 8.4 no-loss gate does NOT cover (DF-15).

    That gate counts a citation only if its literal resolves onto an article in
    an edition's ``articles_8_4.json``, and the generator *raises* on non-8.4
    content in those caches — so Part 4, Part 5 and Part 6 citations are dropped
    at scan time and could be deleted without failing anything. Measured when
    this was written: 213 sites inside the gate, 173 outside it.

    Two populations, because they can be keyed with different confidence.

    ``static`` — a plain string literal, keyed by ``{literal: {kind: count}}``.
    Exact and meaningful: ``5.2.6.3.(1)`` losing a site is named in the failure.
    No file path enters the key, so a rename cannot invalidate the baseline —
    the same rule the 8.4 baseline follows.

    ``dynamic_sites`` — one integer for everything else: an ``article=`` whose
    value is a variable, or an f-string interpolating anything the scanner
    cannot fold to a name. These cannot be keyed honestly (the scanner renders
    ``f'{ruleset.article(x)}.(2)(b)'`` as the fragment ``'.(2)(b)'``, which is an
    extraction artefact, not text that appears in any audit), but they can still
    be COUNTED, so deleting one drops the total and the gate fires.
    """
    coverage = load_coverage_module()
    root = source_root or (REPO_ROOT / "python")
    static: dict[str, dict[str, int]] = {}
    dynamic = 0

    for path in sorted(root.glob(SOURCE_GLOB)):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            for keyword in call.keywords:
                if keyword.arg != "article":
                    continue
                kind = coverage.python_call_kind(call)
                node = keyword.value
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    literal = node.value
                    if _EIGHT_FOUR.findall(literal.replace("{prefix}", "PREFIX")):
                        continue
                    static.setdefault(literal, {}).setdefault(kind, 0)
                    static[literal][kind] += 1
                    continue
                rendered = coverage.python_citation_value(node)
                if rendered is not None and _EIGHT_FOUR.findall(
                        rendered.replace("{prefix}", "PREFIX")):
                    continue
                dynamic += 1

    return {"static": static, "dynamic_sites": dynamic}


def load_foreign_baseline() -> dict:
    return json.loads(FOREIGN_BASELINE_PATH.read_text(encoding="utf-8"))
