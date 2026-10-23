"""Keep article-coverage code pointers attached to real Python definitions."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPING_PATH = Path(__file__).with_name("data") / "coverage_code_ref_mapping.json"
#: The R7 (Stage 1 / R-B, D-86) ledger: the R6 ledger's `new` column carried
#: through the btap.necb -> btap.codes rename and the eui/tiers move. Two
#: ledgers, never one rewritten in place — see test_r7_ledger_chains_from_r6.
MAPPING_PATH_R7 = (Path(__file__).with_name("data")
                   / "coverage_code_ref_mapping_r7.json")
#: References retired from the live manifests after R-B: either their coverage
#: claim was deleted or an ambiguous pointer was superseded. The third term
#: that keeps R6's 313 provable instead of edited — see
#: test_r7_ledger_chains_from_r6_to_the_live_manifests.
ADDITIONS_PATH = (Path(__file__).with_name("data")
                  / "coverage_code_ref_additions.json")
RETIREMENTS_PATH = (Path(__file__).with_name("data")
                    / "coverage_code_ref_retirements.json")
GENERATOR = REPO_ROOT / "python" / "scripts" / "generate_necb_8_4_coverage.py"
SPEC = importlib.util.spec_from_file_location("generate_necb_8_4_coverage_refs", GENERATOR)
coverage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = coverage
SPEC.loader.exec_module(coverage)
SIZING_TIME = re.compile(
    r"sizing[- ]time|autosiz|not explicitly enforced|not individually evaluated",
    re.IGNORECASE,
)


#: Where each code family keeps one snapshot directory per edition. Discovery
#: is MANIFEST-driven since Stage 3 of the multi-edition plan: the rule files
#: no longer carry the edition in their names, so a filename grammar
#: (``*_rules_*.json``) cannot find them and an edition that renames a file
#: must say so in its manifest.
EDITION_DATA = REPO_ROOT / "python" / "btap" / "codes" / "necb" / "data"


def coverage_manifests():
    manifests = []
    for manifest_path in sorted(EDITION_DATA.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for _domain, filename in sorted((manifest.get("rules") or {}).items()):
            path = manifest_path.parent / filename
            data = json.loads(path.read_text(encoding="utf-8"))
            articles = data.get("article_coverage", {}).get("articles")
            if articles is not None:
                manifests.append((path.relative_to(REPO_ROOT), articles))
    return manifests


def code_refs(manifests):
    return [
        ref
        for _manifest, articles in manifests
        for article in articles
        for ref in article.get("code", [])
    ]


def test_manifest_inventory_and_every_code_ref_resolves():
    manifests = coverage_manifests()
    assert len(manifests) == 12
    # 241 -> 239 and 313 -> 312 on Sol's `137`: NECB 2020 contains neither
    # Article 8.4.1.5 nor Sentence 8.4.2.2.(6), verified against the official
    # NRC 2020 second printing with the 2025-02-27 errata, so two 2020
    # coverage rows cited articles that do not exist and were DELETED rather
    # than renumbered. One carried a code pointer, hence the ref count. The
    # 2025 claims for the same provisions stay: they exist there.
    #
    # Sol's `215` re-declared NECB 2025's 8.4.1.2 from `implemented` to
    # `partial` — sentence (5)'s capacity iteration is applied on the 8.4.5
    # reference path and NOT on the 8.4.4 archetype-EUI path (AHJ-21), and
    # the row claimed both. The ARTICLE count is unchanged at 239: it was
    # re-declared at its true depth, not split.
    #
    # 312 -> 313 on his `220`: the row gained
    # `path.py#evaluate_unmet_8_4_4`, because its two inherited pointers are
    # reference-path forwarding surfaces and the EUI path executes neither.
    # Recorded in `coverage_code_ref_additions.json` rather than by editing a
    # historical ledger.
    #
    # 239 -> 241 and 313 -> 321 under D-105: both envelope snapshots gained
    # the previously absent 3.2.3.3 row and its four runtime witnesses.
    #
    # 321 -> 323 for issue #73: the ambiguous backends.py#execute pointer was
    # retired and replaced by both concrete execution paths, Local.execute and
    # Remote.execute. The historical R7 ledger stays frozen; the retirement
    # and two additions record the correction.
    #
    # 323 -> 327 under D-32's method-neutral correction: both editions'
    # 3.2.3.3 rows gained the phase-2b inventory and equivalent-UA application
    # surfaces. The four uses are additions, not historical R-B renames.
    assert sum(len(articles) for _path, articles in manifests) == 241

    refs = code_refs(manifests)
    assert len(refs) > 60
    assert len(refs) == 327
    assert all(not re.match(r"^btap-[^/]+/lib/", ref) for ref in refs)

    for manifest, articles in manifests:
        for article in articles:
            for ref in article.get("code", []):
                path_text, separator, symbol = ref.partition("#")
                assert separator and symbol, f"{manifest} {article['article']}: invalid ref {ref}"
                path = REPO_ROOT / path_text
                assert path.is_file(), f"{manifest} {article['article']}: no such file {path_text}"
                lines = coverage.python_definition_lines(path, symbol)
                assert len(lines) == 1, (
                    f"{manifest} {article['article']}: {ref} resolves to "
                    f"{len(lines)} definitions at lines {lines}; use Class.method "
                    "when a name is ambiguous"
                )


def test_qualified_backend_refs_reject_the_ambiguous_stub_name():
    path = REPO_ROOT / "python" / "btap" / "simulation" / "backends.py"
    assert len(coverage.python_definition_lines(path, "execute")) == 3
    for symbol in ("Backend.execute", "Local.execute", "Remote.execute"):
        assert len(coverage.python_definition_lines(path, symbol)) == 1

    old = "python/btap/simulation/backends.py#execute"
    refs = Counter(code_refs(coverage_manifests()))
    assert refs[old] == 0
    assert refs["python/btap/simulation/backends.py#Local.execute"] == 2
    assert refs["python/btap/simulation/backends.py#Remote.execute"] == 2
    try:
        coverage.code_ref_line(REPO_ROOT, old)
    except ValueError as error:
        assert "resolves to 3 definitions" in str(error)
    else:
        raise AssertionError("the ambiguous unqualified execute ref must be rejected")


def test_every_covering_entry_names_its_code():
    for manifest, articles in coverage_manifests():
        for article in articles:
            if article.get("gap_owner") == "modeller":
                continue

            status = article.get("status")
            if status in {"implemented", "satisfied_by_clone"}:
                needed = True
            elif status == "host_scope":
                needed = not re.search(
                    r"modeller", f"{article.get('how', '')} {article.get('gaps', '')}", re.I
                )
            elif status == "partial":
                needed = not SIZING_TIME.search(str(article.get("gaps", "")))
            else:
                needed = False

            assert not needed or article.get("code"), (
                f"{manifest} {article['article']} ({status}): must name the code where "
                "this is dealt with"
            )


def test_reviewed_mapping_was_consumed_without_unknown_old_refs():
    """The R6 ledger: Ruby gem owner -> Python owner. Frozen; its `new` column
    is a historical endpoint, so it is checked against the R7 ledger's `old`
    column (below) rather than against the live manifests."""
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    rows = mapping["mappings"]
    assert mapping["source_checkpoint"] == "cbce093"
    assert len(rows) == 87
    assert sum(row["uses"] for row in rows) == 313

    old_refs = [row["old"] for row in rows]
    new_refs = [row["new"] for row in rows]
    assert len(set(old_refs)) == len(old_refs)
    assert len(set(new_refs)) == len(new_refs)

    actual = Counter(code_refs(coverage_manifests()))
    assert not set(actual).intersection(old_refs)
    assert not {
        ref for ref in actual if re.match(r"^btap-[^/]+/lib/", ref)
    }.difference(old_refs)


def test_r7_ledger_chains_from_r6_to_the_live_manifests():
    """The CHAIN, in three links, so neither ledger can be quietly edited:

    1. every R7 `old` is an R6 `new` (and every R6 `new` is an R7 `old`) —
       R-B moved paths, it did not add, drop or merge an owner;
    2. every R7 `new` is a live manifest reference, with the same use count;
    3. the R7 use counts still sum to R6's 313, counting live references and
       recorded retirements together.
    """
    r6 = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))["mappings"]
    r7_mapping = json.loads(MAPPING_PATH_R7.read_text(encoding="utf-8"))
    rows = r7_mapping["mappings"]
    assert r7_mapping["schema_version"] == 1

    # --- link 1: R7.old == R6.new, as a multiset with its use counts --------
    assert Counter({row["old"]: row["uses"] for row in rows}) == Counter(
        {row["new"]: row["uses"] for row in r6}
    )
    assert len(rows) == len(r6) == 87
    assert len({row["old"] for row in rows}) == len(rows)
    assert len({row["new"] for row in rows}) == len(rows)

    # --- link 2: R7.new == the live manifests PLUS the retirements ----------
    #
    # A deleted coverage claim takes its code reference with it; an ambiguous
    # historical pointer can likewise be replaced by qualified live refs.
    # Those are different events from the rename these ledgers record — link 1
    # asserts R-B "did not add, drop or merge an owner" — so they are accounted
    # in a THIRD file rather than by rewriting a ledger in place, which both
    # ledgers forbid. The invariant is unchanged and still exact: every
    # reference R7 names is either live today or retired on a stated authority.
    # A silent ledger edit still fails this; a recorded retirement passes it.
    retirements = json.loads(RETIREMENTS_PATH.read_text(encoding="utf-8"))
    assert retirements["schema_version"] == 1
    retired = Counter()
    for entry in retirements["retirements"]:
        assert entry["authority"], "a retirement without an authority is a silent edit"
        assert entry["reason"], "a retirement must say why"
        retired[entry["ref"]] += entry["uses"]

    # A FOURTH term, for the opposite event. A coverage claim can acquire a
    # surface that did not exist when these ledgers were written, and the
    # ledgers record RENAMES — they assert R-B "moved paths, it did not add,
    # drop or merge an owner". So an addition is recorded beside them, by the
    # same reasoning that put deletions in their own file rather than in a
    # ledger edit.
    #
    # I first read the ledger's total as a rule that no pointer may ever be
    # added, and removed one that a claim needed. Sol (`220`) ruled that the
    # ledger is a historical migration record, not that prohibition: the
    # claim that NECB 2025's 8.4.1.2 applies (3) and (4)(a) on the EUI path
    # has to point at code the EUI path EXECUTES, and its two inherited
    # pointers are reference-path forwarding surfaces.
    additions = json.loads(ADDITIONS_PATH.read_text(encoding="utf-8"))
    assert additions["schema_version"] == 1
    added = Counter()
    for entry in additions["additions"]:
        assert entry["authority"], "an addition without an authority is a silent edit"
        assert entry["reason"], "an addition must say why"
        added[entry["ref"]] += entry["uses"]

    assert Counter(code_refs(coverage_manifests())) + retired == Counter(
        {row["new"]: row["uses"] for row in rows}
    ) + added

    # --- link 3: the total survived both hops ------------------------------
    assert sum(row["uses"] for row in rows) == sum(row["uses"] for row in r6)
    assert sum(row["uses"] for row in rows) == 313

    # No live pointer may still name the pre-R-B package.
    assert not [row for row in rows if row["new"].startswith("python/btap/necb/")]
    # tiers.py's one pointer followed eui_building_energy_target into the
    # 2025 edition module, so the owning-file count drops 32 -> 31.
    assert len({row["old"].split("#")[0] for row in rows}) == 32
    assert len({row["new"].split("#")[0] for row in rows}) == 31