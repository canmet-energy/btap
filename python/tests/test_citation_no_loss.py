"""Scanner no-loss gate: no ``(edition, article, kind)`` citation-site count may
drop below the recorded baseline (new keys and higher counts are fine).

Keying by article alone would let a 2025 site vanish while 2020 keeps the
article visible, or five of six sites vanish while one remains — see
``docs/NECB_MULTI_EDITION_PLAN.md`` Stage 0 item 0.3. No file path enters the
key, so a later path-only rename cannot invalidate this baseline.

A deliberate count change (for example, the ``compliance.py:346``
``lighting_prefix`` -> ``prefix`` fix that made that citation newly
scanner-visible) is re-baselined explicitly in the same commit as the change
that causes it, with the reason recorded in the baseline's ``_provenance``.
"""

from __future__ import annotations

import unittest

from tests.citation_counts import (
    compute_citation_counts,
    compute_foreign_citation_counts,
    load_baseline,
    load_foreign_baseline,
)


class TestCitationNoLoss(unittest.TestCase):
    def test_no_citation_count_drops_below_baseline(self):
        baseline = load_baseline()
        current = compute_citation_counts()

        regressions = []
        for edition, articles in baseline.items():
            if edition == "_provenance":
                continue
            for article, kinds in articles.items():
                for kind, expected_count in kinds.items():
                    actual_count = current.get(edition, {}).get(article, {}).get(kind, 0)
                    if actual_count < expected_count:
                        regressions.append(
                            f"{edition}/{article}/{kind}: baseline {expected_count}, "
                            f"now {actual_count}"
                        )
        self.assertEqual(
            [], regressions,
            "citation site(s) lost relative to tests/data/citation_counts_baseline.json:\n"
            + "\n".join(regressions),
        )

    def test_baseline_editions_match_scanner_editions(self):
        baseline = load_baseline()
        current = compute_citation_counts()
        baseline_editions = {key for key in baseline if key != "_provenance"}
        self.assertEqual(set(current.keys()), baseline_editions)


class TestForeignCitationNoLoss(unittest.TestCase):
    """DF-15: the same no-loss guarantee for the citations the Section 8.4
    scanner cannot see.

    Its universe is ``articles_8_4.json`` and the generator raises on anything
    else in those caches, so a Part 4/5/6 citation is dropped at scan time.
    Measured when this gate was written, at site level: the 8.4 gate covers 105
    distinct source sites and this one covers 178 — about 62 % of the citation
    surface was ungated. ``5.2.6.3.(1)``, ``5.2.2.8.``, the Part 4 lighting set
    and the ``btap/costing`` citations could all be deleted without failing
    anything. (The 8.4 baseline's 213 is a per-EDITION count of its 105 sites;
    reading it as a site count understates the gap.)

    This does NOT widen the coverage attestation, which is a Section 8.4
    document and should stay one. It only stops citations disappearing unnoticed.
    """

    def test_no_static_foreign_citation_drops_below_baseline(self):
        baseline = load_foreign_baseline()
        current = compute_foreign_citation_counts()

        regressions = []
        for literal, kinds in baseline["static"].items():
            for kind, expected in kinds.items():
                actual = current["static"].get(literal, {}).get(kind, 0)
                if actual < expected:
                    regressions.append(f"{literal!r}/{kind}: baseline {expected}, now {actual}")
        self.assertEqual(
            [], regressions,
            "non-8.4 citation site(s) lost relative to "
            "tests/data/foreign_citation_counts_baseline.json:\n" + "\n".join(regressions),
        )

    def test_no_dynamic_citation_drops_below_baseline(self):
        """An ``article=`` built from a variable has no literal to key on, but it
        does have the expression that produced it — ``spec['article']``,
        ``f'{article}(4)'``. Keyed by that rather than merely counted, because a
        bare total cannot see a swap: delete one and add an unrelated one and
        the total is unchanged."""
        baseline = load_foreign_baseline()
        current = compute_foreign_citation_counts()

        regressions = []
        for expression, kinds in baseline["dynamic"].items():
            for kind, expected in kinds.items():
                actual = current["dynamic"].get(expression, {}).get(kind, 0)
                if actual < expected:
                    regressions.append(f"{expression}/{kind}: baseline {expected}, now {actual}")
        self.assertEqual(
            [], regressions,
            "dynamically built article= citation site(s) lost relative to "
            "tests/data/foreign_citation_counts_baseline.json:\n" + "\n".join(regressions),
        )


if __name__ == "__main__":
    unittest.main()
