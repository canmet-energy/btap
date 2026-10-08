"""Every Section 8.4 article a FROZEN run cites must exist in its edition's
own snapshot.

Stdlib-only and reads committed artifacts, so it runs in `lint` beside the
other document checks and needs no SDK, no EnergyPlus and no install.

Fable's `133` G3 found five sites citing NECB 2020's subsection on NECB 2025
runs — one of them in the `article` FIELD, naming an article 2025 does not
contain — and the frozen corpus saw every one while the fixture-based gate
reached none. His `135` H1 then showed why that gate cannot be the only one:
it runs `simulate="none"`, and `_size_reference` returns immediately on
`none`, so it never reaches `apply_economizer_thresholds` — the very site G3
led with. The baselines are the broadest instrument available, so they are
the gate.

The membership property needs no judgement about which subsection means what
in which edition, which is what killed the first version of this check: it
asserted a 2025 run citing `8.4.4.x` is "always wrong", and `8.4.4.1`/`.2`
ARE 2025's archetype-EUI articles, cited correctly on every 2025 run.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINES = REPO_ROOT / "verification" / "scenarios" / "baselines"
SNAPSHOTS = REPO_ROOT / "python" / "btap" / "codes" / "necb" / "data"

#: Any `8.4.x.y`, at the depth the snapshots carry.
ARTICLE = re.compile(r"8\.4\.\d+\.\d+")

#: A DELIBERATE cross-edition reference, `8.4.4.3./8.4.5.3.`. Prose that says
#: where a requirement lands in EITHER edition names both numbers on purpose,
#: so one is always absent from the running edition and is not a miscitation.
PAIRED = re.compile(r"(8\.4\.\d+\.\d+)\.?/(8\.4\.\d+\.\d+)")

#: The fields that reach a reader. `article` is what an authority is told;
#: the rest carry the deciding entry's own account, which the resolver quotes
#: verbatim as a condition's `detail`.
FIELDS = ("article", "action", "value", "evidence")

#: Citations absent from their edition's snapshot that are NOT code literals:
#: each comes from that edition's own `necb_rules.json` article_coverage.
#: Whether the data or the snapshot is wrong is a NORMATIVE question, referred
#: to Sol in `136` and not settled here — and a coverage-data edit has four
#: gates of its own. Declared so this test still fails on anything NEW.
#:
#: The evidence, kept here because `.reviews/` is gitignored and this is the
#: tracked home for it (Fable's `135` H2). Live codes-MCP calls, 2026-10-08:
#:
#:     2020 8.4.1.4  -> Treatment of Additions
#:     2020 8.4.1.5  -> SERVER ERROR: get_section: empty result content
#:     2020 8.4.2.11 -> SERVER ERROR: get_section: empty result content
#:     2020 8.4.2.12 -> SERVER ERROR: get_section: empty result content
#:     2025 8.4.1.5  -> Treatment of Process Loads
#:     2025 8.4.2.11 -> Testing of Energy Modeling Software
#:     2025 8.4.2.12 -> Exceptional Calculation Methods
#:
#: All three 2020 ids come back empty and all three are titled in 2025; Sol's
#: `126` already noted 8.4.2.12 has no 2020 counterpart. An empty MCP result
#: is not proof of absence, which is exactly why this is a referral and not a
#: fix: the server has shipped errata before. The 2020 `8.4.1.2` row's own
#: prose points the other way — its `how` says "(see 8.4.2.11.)" — so whoever
#: authored it believed those articles were available in 2020.
PENDING_SOL_136 = {
    "necb2020": {"8.4.1.5", "8.4.2.11", "8.4.2.12"},
    "necb2025": set(),
}


def _snapshot(code: str) -> set:
    path = SNAPSHOTS / code / "coverage" / "articles_8_4.json"
    articles = json.loads(path.read_text(encoding="utf-8"))["articles"]
    return set(articles) if isinstance(articles, dict) else {
        str(entry) for entry in articles}


def _entries(audit_path: Path) -> list:
    data = json.loads(audit_path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else (data.get("entries") or [])


def _foreign(entries, known: set) -> set:
    cited, paired = set(), set()
    for entry in entries:
        blob = " ".join(str(entry.get(field) or "") for field in FIELDS)
        paired.update(PAIRED.findall(blob))
        cited.update(ARTICLE.findall(blob))
    forgiven = {other for left, right in paired
                for one, other in ((left, right), (right, left))
                if one in known and other not in known}
    return {article for article in cited if article not in known} - forgiven


class TestFrozenArticleMembership(unittest.TestCase):

    def _scenarios(self):
        """(name, code, entries) for every frozen baseline that declares a
        code and carries an audit."""
        found = []
        for scenario in sorted(BASELINES.iterdir()):
            report, audit = scenario / "report.json", scenario / "audit.json"
            if not (report.is_file() and audit.is_file()):
                continue
            code = (json.loads(report.read_text(encoding="utf-8"))
                    or {}).get("code")
            if code:
                found.append((scenario.name, code, _entries(audit)))
        return found

    def test_the_corpus_is_there_to_sweep(self):
        """Absence of output is not evidence: a sweep over nothing passes."""
        scenarios = self._scenarios()
        self.assertGreater(len(scenarios), 20,
                           "the frozen corpus should carry dozens of runs")
        cited = sum(len(_foreign(entries, set())) for _n, _c, entries
                    in scenarios)
        self.assertGreater(cited, 0, "the probe must find citations at all")

    def test_no_frozen_run_cites_a_foreign_article(self):
        snapshots = {}
        for name, code, entries in self._scenarios():
            with self.subTest(name, code=code):
                known = snapshots.setdefault(code, _snapshot(code))
                unexpected = sorted(_foreign(entries, known)
                                    - PENDING_SOL_136.get(code, set()))
                self.assertEqual(
                    [], unexpected,
                    "{} cites articles absent from the {} snapshot and not "
                    "among the declared referrals: {}".format(
                        name, code, unexpected))

    def test_the_declared_referrals_still_FIRE(self):
        """A settled referral must leave this list deliberately, not drift out
        of it — otherwise the declaration outlives the reason for it."""
        seen = {code: set() for code in PENDING_SOL_136}
        snapshots = {}
        for _name, code, entries in self._scenarios():
            if code not in seen:
                continue
            known = snapshots.setdefault(code, _snapshot(code))
            seen[code] |= _foreign(entries, known)
        for code, declared in PENDING_SOL_136.items():
            with self.subTest(code):
                self.assertEqual(
                    declared, seen[code] & declared,
                    "a declared referral stopped firing; settle it in the list")

    def test_the_sweep_has_TEETH(self):
        """G3's two real offenders, against the 2025 snapshot."""
        known = _snapshot("necb2025")
        self.assertEqual(
            {"8.4.4.12", "8.4.4.9"},
            _foreign([{"article": "8.4.4.12.; 5.2.2.7.(1)"},
                      {"action": "the structural 8.4.4.9.(4) proxy"}], known))

    def test_a_cross_edition_pair_is_forgiven_and_a_lone_number_is_not(self):
        known = _snapshot("necb2025")
        self.assertEqual(
            set(),
            _foreign([{"action": "see 8.4.2.9. and 8.4.4.3./8.4.5.3."}], known))
        self.assertEqual(
            {"8.4.4.3"}, _foreign([{"action": "see 8.4.4.3. alone"}], known))


if __name__ == "__main__":
    unittest.main()
