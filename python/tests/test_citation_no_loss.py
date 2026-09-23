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
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.citation_counts import (
    _foreign_content,
    compute_citation_counts,
    compute_data_citation_counts,
    compute_foreign_citation_counts,
    load_baseline,
    load_data_baseline,
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




class TestDataCitationNoLoss(unittest.TestCase):
    """No article value packaged in product DATA may lose a citation (DF-16).

    The two gates above scan ``article=`` in Python. Neither reads the rule
    files, so an id that reaches the audit through ``spec["article"]`` is keyed
    by the EXPRESSION and its value could be edited or deleted with nothing
    moving. Measured before this gate existed: 311 values across 14 files, and
    a mutation of one was invisible to both citation gates, the generated
    coverage document, and all 45 frozen scenario baselines.
    """

    def test_no_data_article_count_drops_below_baseline(self):
        baseline = load_data_baseline()
        current = compute_data_citation_counts()

        regressions = []
        for scope, articles in baseline.items():
            if scope == "_provenance":
                continue
            for article, expected in articles.items():
                actual = current.get(scope, {}).get(article, 0)
                if actual < expected:
                    regressions.append(
                        f"{scope}/{article}: baseline {expected}, now {actual}")
        self.assertEqual(
            [], regressions,
            "data article citation(s) lost relative to "
            "tests/data/data_citation_counts_baseline.json:\n" + "\n".join(regressions))

    def test_baseline_scopes_match_the_scanned_scopes(self):
        baseline = load_data_baseline()
        self.assertEqual(
            set(compute_data_citation_counts()),
            {key for key in baseline if key != "_provenance"})


class TestDataGateCatchesRealRegressions(unittest.TestCase):
    """The data gate's contracts, exercised by MUTATING a throwaway copy.

    Asserting a baseline against itself proves only that the file was read.
    Each case below changes one value and requires the gate to name it — and
    the swap case is the one a repository-wide total could not catch.
    """

    #: Both anchors live in the 2020 efficiencies snapshot. The 8.4 one is a
    #: part-load row; the other is a mixed legacy reference whose leading half
    #: is a Part 5 table, so it is exactly the "not 8.4" population the 8.4
    #: gate refuses by design.
    EIGHT_FOUR = '"article": "8.4.5.2."'
    FOREIGN = '"article": "NECB 2020 Table 5.2.12.1.-N; 8.4.5.2."'
    SNAPSHOT_2020 = "btap/codes/necb/data/necb2020/efficiencies.json"
    SNAPSHOT_2025 = "btap/codes/necb/data/necb2025/efficiencies.json"

    def copy(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copytree(Path(__file__).resolve().parents[1] / "btap", tmp / "btap")
        return tmp

    def edit(self, tmp, relative, old, new, *, count=1):
        target = tmp / relative
        text = target.read_text(encoding="utf-8")
        self.assertIn(old, text, f"anchor missing in {relative} — the fixture has moved")
        target.write_text(text.replace(old, new, count), encoding="utf-8")

    @staticmethod
    def total(counts):
        return sum(sum(values.values()) for values in counts.values())

    def before(self):
        """The gate's own reading of the UNMUTATED tree.

        Never the committed baseline. Comparing a mutation against the baseline
        file passes whenever the gate stops seeing a key at all — the count
        goes to zero, which reads as a drop — so a gate that quietly narrowed
        its key set would satisfy every mutation test here. Measured live, that
        same narrowing makes before and after equal and the assertion fails,
        which is the property these tests are for (found by narrowing
        EMITTED_ARTICLE_KEYS and watching two of them pass anyway).
        """
        return compute_data_citation_counts()

    def test_the_harness_measures_the_same_tree_as_the_real_run(self):
        """Positive control. Every assertion below is a DROP against the
        committed baseline, so all of them would pass vacuously if the copied
        tree measured something else. This fails first if it does.

        Compared against a REAL run rather than against the baseline file: the
        two sibling gates allow growth ("new keys and higher counts are fine"),
        so pinning the copy to the baseline would quietly convert this gate
        from no-LOSS to no-CHANGE, and adding one article to a rule file would
        fail here with a message about the harness (Fable, PR #56). The
        property this control actually needs is that copying the tree does not
        change what the gate sees.
        """
        self.assertEqual(compute_data_citation_counts(),
                         compute_data_citation_counts(source_root=self.copy()),
                         "a copy of the tree must measure exactly what the real "
                         "tree measures, or every drop assertion below is vacuous")

    def test_changing_a_data_owned_8_4_value_is_caught(self):
        tmp = self.copy()
        self.edit(tmp, self.SNAPSHOT_2020, self.EIGHT_FOUR, '"article": "8.4.9.99."')
        after = compute_data_citation_counts(source_root=tmp)
        self.assertLess(after["necb2020"].get("8.4.5.2.", 0),
                        self.before()["necb2020"]["8.4.5.2."],
                        "an 8.4 article living in DATA must be guarded — the 8.4 "
                        "gate never sees it, because it scans Python")

    def test_deleting_a_non_8_4_value_is_caught(self):
        tmp = self.copy()
        self.edit(tmp, self.SNAPSHOT_2020, self.FOREIGN, '"article": "REMOVED"')
        after = compute_data_citation_counts(source_root=tmp)
        key = "NECB 2020 Table 5.2.12.1.-N; 8.4.5.2."
        self.assertEqual(0, after["necb2020"].get(key, 0))
        self.assertEqual(1, self.before()["necb2020"][key],
                         "the deleted value was there before the mutation")

    def test_a_trigger_article_is_guarded(self):
        """``trigger_article`` is emitted verbatim as ``article=`` from
        ``checker.py:167`` and ``energy_recovery.py:63,71,88,93``. Guarding only
        the key spelled ``article`` left four of the twenty-four subscript
        sites open — the exact population this gate claims to close (Fable,
        PR #56)."""
        tmp = self.copy()
        rules = tmp / "btap/codes/necb/data/necb2020/reference_rules.json"
        blob = json.loads(rules.read_text(encoding="utf-8"))

        hits = []
        def retarget(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "trigger_article" and value == "5.2.2.9.":
                        node[key] = "9.9.9.9."
                        hits.append(value)
                    else:
                        retarget(value)
            elif isinstance(node, list):
                for item in node:
                    retarget(item)
        retarget(blob)
        self.assertEqual(["5.2.2.9."], hits, "anchor missing — the fixture has moved")
        rules.write_text(json.dumps(blob, indent=2), encoding="utf-8")

        after = compute_data_citation_counts(source_root=tmp)
        self.assertLess(after["necb2020"].get("5.2.2.9.", 0),
                        self.before()["necb2020"]["5.2.2.9."],
                        "a trigger_article reaches the audit like any other "
                        "citation and must be guarded like one")

    def test_a_manifest_article_registry_entry_is_guarded(self):
        """A manifest's ``articles`` mapping reaches the audit through
        ``ruleset.article(key)`` — ``heat_pump_aux_fuel`` lands at
        ``efficiency.py:1557``. That registry is the miniature of what DF-16
        ultimately wants everywhere, so leaving it unguarded would be
        perverse."""
        tmp = self.copy()
        manifest = tmp / "btap/codes/necb/data/necb2020/manifest.json"
        blob = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual("8.4.4.13.(2)(c)", blob["articles"]["heat_pump_aux_fuel"],
                         "anchor missing — the fixture has moved")
        blob["articles"]["heat_pump_aux_fuel"] = "9.9.9.9."
        manifest.write_text(json.dumps(blob, indent=2), encoding="utf-8")

        after = compute_data_citation_counts(source_root=tmp)
        self.assertLess(after["necb2020"].get("8.4.4.13.(2)(c)", 0),
                        self.before()["necb2020"]["8.4.4.13.(2)(c)"],
                        "an article id held in the manifest registry must be guarded")

    def test_a_non_string_article_value_raises_rather_than_vanishing(self):
        """Skipping a non-string would open a hole quietly: the value stops
        being counted, the next re-baseline records its absence as normal, and
        it is unguarded forever with every test green."""
        tmp = self.copy()
        target = tmp / self.SNAPSHOT_2020
        blob = json.loads(target.read_text(encoding="utf-8"))
        rows = blob["part_load_fheatplc"]
        rows[0]["article"] = ["8.4.5.2.", "8.4.5.3."]
        target.write_text(json.dumps(blob, indent=2), encoding="utf-8")

        with self.assertRaises(TypeError):
            compute_data_citation_counts(source_root=tmp)

    def test_an_edition_swap_is_caught_where_a_repository_TOTAL_would_not_be(self):
        """The case that decides the key shape: remove a value from 2020 and
        add one to 2025, so the repository-wide total is UNCHANGED and only the
        edition scope can fire.

        Edited structurally rather than by string replacement, because the
        obvious string edits do not do what they appear to. Changing a value to
        ``"REMOVED"`` keeps the count (the article moved, it did not go), and a
        second ``"article"`` key pasted into the same object is silently
        dropped by the JSON parser. A first draft of this test did both and
        passed while neither edition had lost or gained anything.
        """
        shared = "3.1.1.5."          # one of 65 values carried by BOTH editions
        rules = "btap/codes/necb/data/{}/envelope_rules.json"
        tmp = self.copy()

        def articles_of(edition):
            # Two lists are named "articles" in this file; the coverage one
            # holds dicts with an "article" key, which is what the gate counts.
            # The provenance one is a list of plain strings and is invisible to
            # it, exactly as intended.
            path = tmp / rules.format(edition)
            blob = json.loads(path.read_text(encoding="utf-8"))
            return path, blob, blob["article_coverage"]["articles"]

        path, blob, entries = articles_of("necb2020")
        for entry in entries:
            if entry.get("article") == shared:
                del entry["article"]
                break
        else:
            self.fail(f"{shared} missing from the 2020 snapshot — the fixture has moved")
        path.write_text(json.dumps(blob, indent=2), encoding="utf-8")

        path, blob, entries = articles_of("necb2025")
        twin = next((e for e in entries if e.get("article") == shared), None)
        self.assertIsNotNone(twin, f"{shared} must exist in 2025 for the swap to balance")
        entries.append(dict(twin))
        path.write_text(json.dumps(blob, indent=2), encoding="utf-8")

        after = compute_data_citation_counts(source_root=tmp)
        baseline = self.before()

        # Each half must do real work, or the swap proves nothing.
        self.assertEqual(sum(baseline["necb2020"].values()) - 1,
                         sum(after["necb2020"].values()), "2020 must lose exactly one")
        self.assertEqual(sum(baseline["necb2025"].values()) + 1,
                         sum(after["necb2025"].values()), "2025 must gain exactly one")
        self.assertEqual(self.total(baseline), self.total(after),
                         "the repository-wide total must be UNCHANGED")

        # The point of choosing a SHARED value: the global count of this exact
        # article is also unchanged, so a value-keyed gate WITHOUT a scope sees
        # nothing either. Only the edition scope can fire.
        global_before = (baseline["necb2020"].get(shared, 0)
                         + baseline["necb2025"].get(shared, 0))
        global_after = (after["necb2020"].get(shared, 0)
                        + after["necb2025"].get(shared, 0))
        self.assertEqual(global_before, global_after,
                         f"{shared} must be globally unchanged — otherwise this test "
                         "would pass on a scope-blind gate and prove nothing")

        self.assertLess(after["necb2020"].get(shared, 0), baseline["necb2020"][shared],
                        "the 2020 removal must fire even though 2025 gained the "
                        "same article — this is what the edition scope is for")

if __name__ == "__main__":
    unittest.main()
