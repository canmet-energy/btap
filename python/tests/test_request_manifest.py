"""The D-80 request manifest is INTERNALLY LIVE: every golden group it
requests has at least one pytest consumer, its pytest file list exists and
collects the declared count, and the committed goldens match it exactly.
An orphaned group (requested, exported, checksummed — consumed by nothing)
would be verification theater; this is the test that forbids it."""

import json
import subprocess
import sys

from tests.support import REPO_ROOT

MANIFEST = REPO_ROOT / "verification" / "oracle" / "request_manifest.json"
GOLDENS = REPO_ROOT / "verification" / "oracle" / "goldens"

# Which golden groups each goldens test file consumes (asserted below so the
# map cannot rot: every file must exist, every group must appear).
CONSUMERS = {
    "tests/necb/test_oracle_goldens_envelope.py": [
        "envelope_lookups", "envelope_prescriptive", "envelope_u_table"],
    "tests/necb/test_oracle_goldens_loads.py": [
        "loads_schedules", "loads_apply", "loads_merged_tables"],
    "tests/necb/test_oracle_goldens_shw.py": ["shw"],
    "tests/necb/test_oracle_goldens_lighting.py": [
        "lighting_lights", "lighting_daylighting", "lighting_costing"],
    "tests/costing/test_oracle_goldens_envelope.py": ["costing_envelope"],
}


def load():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_every_group_has_a_consumer():
    manifest = load()
    consumed = {g for groups in CONSUMERS.values() for g in groups}
    orphaned = set(manifest["golden_groups"]) - consumed
    assert not orphaned, (
        f"golden groups {sorted(orphaned)} are requested from the oracle but "
        "consumed by NO goldens test — either add a consumer or retire the "
        "group via an adjudicated request-manifest update")


def test_consumer_map_matches_manifest_files():
    manifest = load()
    assert sorted(CONSUMERS) == sorted(manifest["pytest"]["files"]), (
        "the consumer map and request_manifest.json['pytest']['files'] "
        "disagree — update both together")
    for rel in CONSUMERS:
        assert (REPO_ROOT / "python" / rel).is_file(), f"{rel} does not exist"


def test_consumer_files_actually_read_their_groups():
    for rel, groups in CONSUMERS.items():
        text = (REPO_ROOT / "python" / rel).read_text(encoding="utf-8")
        for group in groups:
            assert group in text, (
                f"{rel} is declared the consumer of {group!r} but never "
                "mentions it")


def test_collected_count_is_current():
    manifest = load()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", *manifest["pytest"]["files"]],
        cwd=REPO_ROOT / "python", capture_output=True, text=True, check=True)
    line = [ln for ln in result.stdout.splitlines() if "collected" in ln][-1]
    count = int(line.split()[0])
    assert count == manifest["pytest"]["collected"], (
        f"the goldens files collect {count} tests but the request manifest "
        f"declares {manifest['pytest']['collected']} — update the manifest "
        "(adjudicated) so live_leg_c.sh's zero-skip assertion stays exact")


def test_committed_goldens_are_exactly_the_declared_set():
    manifest = load()
    on_disk = sorted(p.stem for p in GOLDENS.glob("*.json")
                     if p.name != "manifest.json")
    assert on_disk == sorted(manifest["golden_groups"])


# ---- assertion (a) of the D-80 triad: Python's vendored data covers the
# request manifest. (b) is the exporter's inventory validation against a
# fresh export; (c) is the Ruby currency test's duty 4 on the committed
# goldens. The three are INDEPENDENT — a negative control on any one side
# trips only its own assertion.

def test_python_vendored_schedules_cover_the_manifest():
    from btap.necb import loads

    manifest = load()
    vendored = {r["name"] for r in loads.table("2020", "schedules")}
    missing = set(manifest["schedule_names"]) - vendored
    assert not missing, (
        f"the request manifest asks the oracle about schedules "
        f"{sorted(missing)} that Python's vendored loads table no longer "
        "carries — the Python side could not consume those goldens")


def test_python_vendored_costing_candidates_cover_the_manifest():
    from btap.costing.envelope.database import Database

    manifest = load()
    database = Database()
    vendored = {}
    for sheet, assemblies in database.constructions.items():
        for assembly in assemblies:
            for rsi, c in database.construction_candidates(sheet, assembly).items():
                vendored[f"{sheet}/{assembly}/{round(rsi, 3)}"] = c
    problems = []
    for candidate in manifest["costing_candidates"]:
        mine = vendored.get(candidate["key"])
        if mine is None:
            problems.append(f"{candidate['key']}: not in Python's vendored catalog")
        elif (mine["type"] != candidate["type"]
              or list(mine["id_layers"]) != list(candidate["id_layers"])):
            problems.append(f"{candidate['key']}: type/id_layers diverge from "
                            "the manifest's bootstrap record")
    assert not problems, "\n".join(problems)


def test_oracle_prep_cites_only_real_gates():
    """Every python/tests path cited in oracle_prep.py's composition
    contracts must exist — the contracts are the evidence that
    Python-prepared oracle inputs are independently verified, and a
    nonexistent cited gate is evidence pointing at nothing (post-merge
    review round 2, finding 2)."""
    import re

    source = (REPO_ROOT / "python" / "scripts" / "oracle_prep.py").read_text(
        encoding="utf-8")
    cited = set(re.findall(r"python/tests/[\w/]+\.py", source))
    assert cited, "no cited gates found — the contract format changed?"
    missing = [c for c in sorted(cited)
               if not (REPO_ROOT / "python" / c.removeprefix("python/")).is_file()]
    assert not missing, f"composition contracts cite nonexistent gates: {missing}"
