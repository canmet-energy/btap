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

from tests.citation_counts import compute_citation_counts, load_baseline


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


if __name__ == "__main__":
    unittest.main()
