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

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.citation_counts import (
    _foreign_content,
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


class TestForeignGateCatchesRealRegressions(unittest.TestCase):
    """The scanner's contracts, exercised by MUTATING a throwaway copy of the
    source rather than by reading the baseline back to itself.

    Every case here was first run by hand and reported as evidence — and the
    very next revision of this gate shipped a cross-version key bug and kept a
    mixed-dynamic hole, because hand-run evidence guards nothing. A gate whose
    failure modes are not themselves tested is a gate nobody can trust twice.
    """

    def mutate(self, relative, old, new):
        """Copy ``btap`` to a temp tree, apply one edit, return the new counts."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copytree(Path(__file__).resolve().parents[1] / "btap", tmp / "btap")
        target = tmp / relative
        text = target.read_text(encoding="utf-8")
        self.assertIn(old, text, f"anchor missing in {relative} — the fixture has moved")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        return compute_foreign_citation_counts(source_root=tmp)

    @staticmethod
    def count(counts, bucket, key, kind="cited"):
        return counts[bucket].get(key, {}).get(kind, 0)

    def test_deleting_a_wholly_foreign_citation_is_caught(self):
        before = load_foreign_baseline()
        after = self.mutate("btap/codes/necb/hvac/efficiency.py",
                            "article='5.2.6.3.(1)',", "")
        self.assertLess(self.count(after, "static", "5.2.6.3.(1)"),
                        self.count(before, "static", "5.2.6.3.(1)"),
                        "a deleted Part 5 citation must drop its own key")

    def test_deleting_the_foreign_half_of_a_mixed_literal_is_caught(self):
        """``'8.4.4.12.; 5.2.2.7.(1)'`` is counted by the 8.4 gate under
        8.4.4.12, so its Part 5 half once fired nothing in either gate."""
        key = "8.4.4.12.; 5.2.2.7.(1)"
        before = load_foreign_baseline()
        after = self.mutate("btap/codes/necb/hvac/reference.py",
                            "article='8.4.4.12.; 5.2.2.7.(1)'", "article='8.4.4.12.'")
        self.assertLess(self.count(after, "static", key), self.count(before, "static", key),
                        "the foreign half of a mixed literal must be guarded")

    def test_deleting_the_foreign_half_of_a_mixed_DYNAMIC_citation_is_caught(self):
        """D-38's own clamp entry, ``f'5.2.6.3.(1); {prefix}.1.(2)'``. Gated
        dynamic sites used to be discarded wholesale, so this half was
        deletable with nothing moving anywhere."""
        key = "f'5.2.6.3.(1); {prefix}.1.(2)'"
        before = load_foreign_baseline()
        self.assertGreater(self.count(before, "dynamic", key), 0,
                           "precondition: the mixed dynamic citation is in the baseline")
        after = self.mutate("btap/codes/necb/hvac/efficiency.py",
                            "article=f'5.2.6.3.(1); {prefix}.1.(2)'",
                            "article=f'{prefix}.1.(2)'")
        self.assertLess(self.count(after, "dynamic", key), self.count(before, "dynamic", key))

    def test_a_dynamic_swap_is_caught_where_a_bare_total_would_not_be(self):
        """Delete one dynamic citation and add an unrelated one: the site TOTAL
        is unchanged, which is why these are keyed rather than counted."""
        key = 'f"{article}(1)"'
        before = load_foreign_baseline()
        after = self.mutate("btap/codes/necb/lighting/storage_garage/__init__.py",
                            'inputs=inputs, article=f"{article}(1)")',
                            'inputs=inputs, article=f"{article}(9)")')
        total_before = sum(n for k in before["dynamic"].values() for n in k.values())
        total_after = sum(n for k in after["dynamic"].values() for n in k.values())
        self.assertEqual(total_before, total_after, "precondition: a bare total sees nothing")
        self.assertLess(self.count(after, "dynamic", key), self.count(before, "dynamic", key),
                        "the keyed gate must still see the swap")

    def test_an_embedded_8_4_is_not_mistaken_for_a_section_8_4_citation(self):
        """``5.2.8.4.`` contains the substring ``8.4``. The scanner's own regex
        is unanchored and reads it as a Section 8.4 token, which would resolve
        to no article there and look gated here — falling between both gates."""
        self.assertTrue(_foreign_content("5.2.8.4."), "a Part 5 article is foreign content")
        self.assertTrue(_foreign_content("Table 3.2.8.4."))
        self.assertFalse(_foreign_content("8.4.4.9.(6)(a); 8.4.1.2.(5)"),
                         "a wholly 8.4 citation belongs to the other gate alone")

    def test_dynamic_keys_do_not_depend_on_the_running_interpreter(self):
        """``ast.unparse`` renders an f-string in the running interpreter's
        syntax — a 3.12 key (PEP 701) is not the 3.11 one. Keys must be the
        file's own bytes, or a structural dump when the slice is unreliable."""
        counts = compute_foreign_citation_counts()
        for key in counts["dynamic"]:
            if key.startswith(("JoinedStr(", "Name(", "Subscript(", "Call(", "IfExp(")):
                continue  # the deliberate structural fallback
            # Parenthesised for the same reason the helper does it: a slice from
            # inside an argument list can span lines legally only because of the
            # parentheses it does not itself include.
            rebuilt = ast.dump(ast.parse(f"({key})", mode="eval").body)
            self.assertTrue(rebuilt, f"{key!r} must be re-parseable source, not a rendering")


if __name__ == "__main__":
    unittest.main()
