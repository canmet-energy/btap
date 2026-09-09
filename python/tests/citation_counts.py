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

import importlib.util
import json
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
