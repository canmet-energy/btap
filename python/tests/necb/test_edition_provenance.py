"""Stage 4 provenance gate (docs/NECB_MULTI_EDITION_PLAN.md, Stage 4 "checked
provenance, and the generated delta"): every manifest-declared output file
for every registered NECB code id must be covered by a checked `provenance`
entry in that edition's `manifest.json`, keyed by the output's own relative
path.

Written against the Stage 4 spec, AHEAD of the sibling agent's provenance
data: no `manifest.json` on this tree carries a `provenance` block yet, so
every test here is EXPECTED TO FAIL until that lands (the missing-block
failure in ``test_provenance_block_covers_exactly_the_declared_outputs`` is
the expected shape of that failure).

Also exports :func:`check_provenance`, callable from the Stage 3 removability
gate's subprocess script (``tests/necb/test_edition_independence.py``) so the
provenance contract is proven under a one-edition-only temp tree too — the
same reason ``byte_identical_to`` targets naming an absent edition are
SKIPPED here, never failed.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import btap.codes as codes
import btap.codes.necb as necb_pkg

#: Keys every provenance entry MUST carry.
REQUIRED_ENTRY_KEYS = {
    "source", "request", "source_revision", "source_sha256", "extractor",
    "retrieved", "method", "source_verification", "result_sha256",
}
#: Keys an entry MAY carry in addition to the required ones.
# `note` is the entry's own disclosure of what source_sha256 does NOT cover
# (mixed-origin files, self-archived caches) — optional, free text.
OPTIONAL_ENTRY_KEYS = {"byte_identical_to", "note"}
ALLOWED_ENTRY_KEYS = REQUIRED_ENTRY_KEYS | OPTIONAL_ENTRY_KEYS

METHODS = {"transcribed", "copied", "generated"}
SOURCE_VERIFICATIONS = {"archived", "revision_addressable", "current_only", "manual"}

#: Manifest top-level keys, besides `rules`/`tables`/`coverage_text`, that
#: name a declared OUTPUT file rather than metadata. Today only the 2025
#: Part 11 files; a manifest without them contributes nothing here.
EXTRA_MANIFEST_FILE_KEYS = ("eui_targets", "ghg_factors")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def declared_outputs(manifest: dict) -> set[str]:
    """Every file this manifest declares as an output.

    The provenance coverage set is EXACTLY this (Stage 4 spec): every
    ``rules`` value, every ``tables`` entry, ``coverage_text``, plus the 2025
    eui/ghg files. Neither ``manifest.json`` itself (self-hash is recursive)
    nor anything under ``provenance/`` (the archived artifacts would
    otherwise need their own provenance) is ever a member.
    """
    outputs = set((manifest.get("rules") or {}).values())
    outputs.update(manifest.get("tables") or [])
    coverage_text = manifest.get("coverage_text")
    if coverage_text:
        outputs.add(coverage_text)
    for key in EXTRA_MANIFEST_FILE_KEYS:
        value = manifest.get(key)
        if value:
            outputs.add(value)
    return outputs


def _archive_name(rel_path: str) -> str:
    """The archived-payload filename for a declared output.

    Stage 4 spec: "the canonical result payload ... is archived under
    ``btap/codes/necb/data/<id>/provenance/<table>.result.json``". ``<name>``
    is the output's own basename, extension-stripped — every declared output
    in one edition has a unique basename (rule files and every ``tables/``
    entry are named distinctly), so this is collision-free without needing
    the directory part.
    """
    stem = Path(rel_path).name
    if stem.endswith(".json"):
        stem = stem[: -len(".json")]
    return f"{stem}.result.json"


def _load_manifest(manifest_dir: Path) -> dict:
    return json.loads((manifest_dir / "manifest.json").read_text(encoding="utf-8"))


def _check_coverage_set(code_id: str, manifest: dict) -> list[str]:
    """(a) provenance coverage set == exactly the manifest-declared outputs."""
    problems = []
    outputs = declared_outputs(manifest)
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        problems.append(f"{code_id}: manifest.json has no 'provenance' block")
        return problems

    entry_keys = set(provenance)
    for name in sorted(outputs - entry_keys):
        problems.append(f"{code_id}: declared output {name!r} has no provenance entry")
    for name in sorted(entry_keys - outputs):
        if name == "manifest.json" or name.startswith("provenance/"):
            problems.append(
                f"{code_id}: provenance entry {name!r} must be absent — manifest.json "
                "and files under provenance/ are never in the coverage set"
            )
        else:
            problems.append(f"{code_id}: provenance entry {name!r} names an undeclared output")
    return problems


def _check_entry_shape(code_id: str, name: str, entry) -> list[str]:
    """(b) every entry has the required keys and enum values."""
    problems = []
    if not isinstance(entry, dict):
        return [f"{code_id}: provenance[{name!r}] is not an object"]

    entry_keys = set(entry)
    for key in sorted(REQUIRED_ENTRY_KEYS - entry_keys):
        problems.append(f"{code_id}: provenance[{name!r}] missing required key {key!r}")
    for key in sorted(entry_keys - ALLOWED_ENTRY_KEYS):
        problems.append(f"{code_id}: provenance[{name!r}] has unknown key {key!r}")
    if "method" in entry and entry["method"] not in METHODS:
        problems.append(
            f"{code_id}: provenance[{name!r}].method {entry['method']!r} not in {sorted(METHODS)}"
        )
    if "source_verification" in entry and entry["source_verification"] not in SOURCE_VERIFICATIONS:
        problems.append(
            f"{code_id}: provenance[{name!r}].source_verification "
            f"{entry['source_verification']!r} not in {sorted(SOURCE_VERIFICATIONS)}"
        )
    return problems


def _check_result_sha256(code_id: str, manifest_dir: Path, name: str, entry: dict) -> list[str]:
    """(c) every result_sha256 equals the sha256 of the shipped file."""
    shipped_path = manifest_dir / name
    if not shipped_path.exists():
        return [f"{code_id}: declared output {name!r} does not exist at {shipped_path}"]
    actual = _sha256(shipped_path)
    expected = entry.get("result_sha256")
    if actual != expected:
        return [
            f"{code_id}: provenance[{name!r}].result_sha256 {expected!r} != "
            f"sha256 of shipped file {actual!r}"
        ]
    return []


def _check_archived_payload(code_id: str, manifest_dir: Path, name: str, entry: dict) -> list[str]:
    """(d) every archived entry's payload exists and matches source_sha256."""
    if entry.get("source_verification") != "archived":
        return []
    archive_path = manifest_dir / "provenance" / _archive_name(name)
    expected = entry.get("source_sha256")
    if not archive_path.exists():
        # The named exception: a cache that IS its own canonical payload
        # (the Section 8.4 article caches) is archived as itself — only when
        # the entry says so in a note and source_sha256 equals result_sha256,
        # and then the shipped file must hash to it.
        if expected == entry.get("result_sha256") and entry.get("note"):
            shipped = manifest_dir / name
            if shipped.exists() and _sha256(shipped) == expected:
                return []
            return [
                f"{code_id}: provenance[{name!r}] is self-archived but the "
                f"shipped file does not hash to source_sha256"
            ]
        return [
            f"{code_id}: provenance[{name!r}] is 'archived' but its payload is "
            f"missing at {archive_path}"
        ]
    actual = _sha256(archive_path)
    if actual != expected:
        return [
            f"{code_id}: provenance[{name!r}] archived payload sha256 {actual!r} != "
            f"source_sha256 {expected!r}"
        ]
    return []


def _check_revision_addressable(code_id: str, name: str, entry: dict) -> list[str]:
    """(e) every revision_addressable entry has a non-null source_revision."""
    if entry.get("source_verification") != "revision_addressable":
        return []
    if not entry.get("source_revision"):
        return [
            f"{code_id}: provenance[{name!r}] is 'revision_addressable' but "
            "source_revision is null/empty"
        ]
    return []


def _check_byte_identical_to(
    code_id: str, data_root: Path, manifest_dir: Path, present_ids: set[str],
    name: str, entry: dict,
) -> list[str]:
    """(f) byte_identical_to is checked ONLY when its edition is present."""
    target = entry.get("byte_identical_to")
    if not target:
        return []
    target_id = target.split("/", 1)[0]
    if target_id not in present_ids:
        return []  # the target edition is absent -- skipped, never failed
    target_path = data_root / target
    shipped_path = manifest_dir / name
    if not target_path.exists():
        return [f"{code_id}: provenance[{name!r}].byte_identical_to {target!r} does not exist"]
    if not shipped_path.exists():
        return []  # already reported by _check_result_sha256
    if shipped_path.read_bytes() != target_path.read_bytes():
        return [
            f"{code_id}: provenance[{name!r}].byte_identical_to {target!r} is not "
            f"byte-identical to {shipped_path}"
        ]
    return []


def _check_copied_own_fields(code_id: str, name: str, entry: dict) -> list[str]:
    """(g) a `copied` entry carries its OWN source_* fields, not a bare
    reference to another edition's live file."""
    if entry.get("method") != "copied":
        return []
    problems = []
    # source_revision is required only where the source is revision-
    # addressable — check (e) covers that; an MCP source honestly has none.
    for key in ("source", "source_sha256", "extractor", "retrieved"):
        if not entry.get(key):
            problems.append(
                f"{code_id}: provenance[{name!r}] is 'copied' but its own {key!r} is "
                "empty — a copied file must carry its own source fields"
            )
    return problems


def check_manifest(manifest_dir: Path, data_root: Path, present_ids: set[str]) -> list[str]:
    """Every Stage 4 provenance problem for ONE edition's manifest."""
    code_id = manifest_dir.name
    manifest = _load_manifest(manifest_dir)
    problems = list(_check_coverage_set(code_id, manifest))

    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        return problems  # already reported by _check_coverage_set

    outputs = declared_outputs(manifest)
    for name in sorted(set(provenance) & outputs):
        entry = provenance[name]
        problems.extend(_check_entry_shape(code_id, name, entry))
        if not isinstance(entry, dict) or REQUIRED_ENTRY_KEYS - set(entry):
            continue  # entry too structurally incomplete to check further
        problems.extend(_check_result_sha256(code_id, manifest_dir, name, entry))
        problems.extend(_check_archived_payload(code_id, manifest_dir, name, entry))
        problems.extend(_check_revision_addressable(code_id, name, entry))
        problems.extend(_check_byte_identical_to(code_id, data_root, manifest_dir, present_ids, name, entry))
        problems.extend(_check_copied_own_fields(code_id, name, entry))
    return problems


def check_provenance(data_root) -> list[str]:
    """Every Stage 4 provenance problem across every edition manifest under
    ``data_root``. Empty list = ok.

    Callable from the Stage 3 removability gate's subprocess (a fresh
    interpreter pointed at a temp tree holding one edition via
    ``btap.codes.necb._set_data_root``), so the provenance contract is proven
    independent of any other edition's files too.
    """
    data_root = Path(data_root)
    manifest_dirs = sorted(p.parent for p in data_root.glob("*/manifest.json"))
    present_ids = {p.name for p in manifest_dirs}
    problems: list[str] = []
    for manifest_dir in manifest_dirs:
        problems.extend(check_manifest(manifest_dir, data_root, present_ids))
    return problems


class TestEditionProvenance(unittest.TestCase):
    """One test method per Stage 4 spec letter (a)-(g), each iterating every
    registered code id so a failure names both the id and the exact problem.
    """

    def test_a_provenance_covers_exactly_the_declared_outputs(self):
        for code_id in codes.code_ids():
            with self.subTest(code_id=code_id):
                manifest = _load_manifest(necb_pkg._data_root() / code_id)
                problems = _check_coverage_set(code_id, manifest)
                self.assertEqual([], problems, "\n".join(problems))

    def test_b_entries_have_required_keys_and_valid_enums(self):
        for code_id in codes.code_ids():
            with self.subTest(code_id=code_id):
                manifest = _load_manifest(necb_pkg._data_root() / code_id)
                provenance = manifest.get("provenance")
                self.assertIsInstance(provenance, dict, f"{code_id}: no 'provenance' block")
                problems = []
                for name, entry in sorted(provenance.items()):
                    problems.extend(_check_entry_shape(code_id, name, entry))
                self.assertEqual([], problems, "\n".join(problems))

    def test_c_result_sha256_matches_the_shipped_file(self):
        for code_id in codes.code_ids():
            with self.subTest(code_id=code_id):
                manifest_dir = necb_pkg._data_root() / code_id
                manifest = _load_manifest(manifest_dir)
                provenance = manifest.get("provenance")
                self.assertIsInstance(provenance, dict, f"{code_id}: no 'provenance' block")
                problems = []
                for name, entry in sorted(provenance.items()):
                    if isinstance(entry, dict):
                        problems.extend(_check_result_sha256(code_id, manifest_dir, name, entry))
                self.assertEqual([], problems, "\n".join(problems))

    def test_d_archived_entries_have_a_matching_payload(self):
        for code_id in codes.code_ids():
            with self.subTest(code_id=code_id):
                manifest_dir = necb_pkg._data_root() / code_id
                manifest = _load_manifest(manifest_dir)
                provenance = manifest.get("provenance")
                self.assertIsInstance(provenance, dict, f"{code_id}: no 'provenance' block")
                problems = []
                for name, entry in sorted(provenance.items()):
                    if isinstance(entry, dict):
                        problems.extend(_check_archived_payload(code_id, manifest_dir, name, entry))
                self.assertEqual([], problems, "\n".join(problems))

    def test_e_revision_addressable_entries_have_a_source_revision(self):
        for code_id in codes.code_ids():
            with self.subTest(code_id=code_id):
                manifest = _load_manifest(necb_pkg._data_root() / code_id)
                provenance = manifest.get("provenance")
                self.assertIsInstance(provenance, dict, f"{code_id}: no 'provenance' block")
                problems = []
                for name, entry in sorted(provenance.items()):
                    if isinstance(entry, dict):
                        problems.extend(_check_revision_addressable(code_id, name, entry))
                self.assertEqual([], problems, "\n".join(problems))

    def test_f_byte_identical_to_checked_only_when_the_edition_is_present(self):
        data_root = necb_pkg._data_root()
        present_ids = set(codes.code_ids())
        for code_id in codes.code_ids():
            with self.subTest(code_id=code_id):
                manifest_dir = data_root / code_id
                manifest = _load_manifest(manifest_dir)
                provenance = manifest.get("provenance")
                self.assertIsInstance(provenance, dict, f"{code_id}: no 'provenance' block")
                problems = []
                for name, entry in sorted(provenance.items()):
                    if isinstance(entry, dict):
                        problems.extend(_check_byte_identical_to(
                            code_id, data_root, manifest_dir, present_ids, name, entry))
                self.assertEqual([], problems, "\n".join(problems))

    def test_g_copied_entries_carry_their_own_source_fields(self):
        for code_id in codes.code_ids():
            with self.subTest(code_id=code_id):
                manifest = _load_manifest(necb_pkg._data_root() / code_id)
                provenance = manifest.get("provenance")
                self.assertIsInstance(provenance, dict, f"{code_id}: no 'provenance' block")
                problems = []
                for name, entry in sorted(provenance.items()):
                    if isinstance(entry, dict):
                        problems.extend(_check_copied_own_fields(code_id, name, entry))
                self.assertEqual([], problems, "\n".join(problems))

    def test_check_provenance_helper_matches_the_packaged_tree(self):
        """The exact function the Stage 3 removability gate calls."""
        problems = check_provenance(necb_pkg._data_root())
        self.assertEqual([], problems, "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
