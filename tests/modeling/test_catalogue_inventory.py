"""The catalogue's independent inventory (#261 step 1).

`tests/fixtures/catalogue_inventory.json` lists every catalogue id with its
legacy name, aliases and the sha256 of its adjudicated D-58 golden record. The
catalogue, the golden and (in `scripts/wheel_smoke.py`) the installed wheel are
each checked AGAINST it, so none of them is its own reference: a count derived
from the catalogue it checks would check nothing (Astra and Fable, #261).

It also declares the chiller-kind PRESETS: rows that differ from their scroll
base only in `chiller_type`. They keep their ids, which are still emitted into
models (D-112), and their own D-58 records, which must equal the base's
(#261 decision 1). The AWHP rows are deliberately NOT presets: their gas and
electric backup pairs differ in every golden field.

Stdlib only: no SDK, so it runs in every lane.
"""

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


INVENTORY = _load(FIXTURES / "catalogue_inventory.json")
CATALOGUE = _load(ROOT / "src" / "btap" / "modeling" / "hvac" / "data" / "systems.json")["systems"]
GOLDEN = _load(FIXTURES / "reference_selection_matrix.json")
RETIRED = {item["id"] for item in _load(FIXTURES / "system_retirements.json")["retired"]}

#: The id token of each compressor kind and the `chiller_type` it must carry.
KIND_OF_TOKEN = {"scrollchiller": "Scroll", "centrifchiller": "Centrifugal",
                 "screwchiller": "Rotary Screw", "recipchiller": "Reciprocating"}
IDENTITY_KEYS = ("id", "legacy_name", "aliases")
#: The ONLY key a preset may differ from its base in (#261 decision 1). Pinned
#: here, not read from the inventory alone, so widening a group's
#: `neutral_keys` there cannot quietly admit a fuel or coil change (Fable,
#: review of #262).
NEUTRAL_KEYS = ["chiller_type"]


def _sha256(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def record_sha256(record):
    """The golden record's hash, its own `id` excluded so equal records of two
    rows hash alike (the preset rule compares them)."""
    return _sha256({key: value for key, value in record.items() if key != "id"})


class TestTheInventoryIsTheReference(unittest.TestCase):

    def test_the_catalogue_is_exactly_the_inventory(self):
        """Adding, retiring, renaming or reordering a row means editing the
        inventory in the same change."""
        self.assertEqual(
            [entry["id"] for entry in INVENTORY["systems"]], [row["id"] for row in CATALOGUE],
            "systems.json and tests/fixtures/catalogue_inventory.json list different ids: "
            "a row added or retired on purpose is entered there in the same change")

    def test_legacy_names_and_aliases_are_unchanged(self):
        rows = {row["id"]: row for row in CATALOGUE}
        for entry in INVENTORY["systems"]:
            with self.subTest(system=entry["id"]):
                row = rows[entry["id"]]
                self.assertEqual(entry["legacy_name"], row.get("legacy_name"))
                self.assertEqual(entry["aliases"], row.get("aliases", []))

    def test_every_row_has_its_adjudicated_record_unchanged(self):
        """Per-preset D-58 coverage stays: every id keeps its own record, and an
        edit to an adjudicated record has to be entered here too."""
        golden = {record["id"]: record for record in GOLDEN}
        self.assertEqual(len(golden), len(GOLDEN), "duplicate ids in the D-58 golden")
        self.assertEqual(sorted(golden), sorted(entry["id"] for entry in INVENTORY["systems"]))
        for entry in INVENTORY["systems"]:
            with self.subTest(system=entry["id"]):
                self.assertEqual(entry["d58_record_sha256"], record_sha256(golden[entry["id"]]))

    def test_what_a_retired_name_builds_is_unchanged(self):
        """`aliases` pins the names; `alias_config` is what a retired name
        carries into the build (D-113), so it is pinned too."""
        catalogue = _load(ROOT / "src" / "btap" / "modeling" / "hvac" / "data" / "systems.json")
        self.assertEqual(INVENTORY["alias_config_sha256"], _sha256(catalogue["alias_config"]))

    def test_no_retired_id_comes_back(self):
        """D-113: a retired id is never reused."""
        self.assertFalse(RETIRED & {entry["id"] for entry in INVENTORY["systems"]})

    def test_the_inventory_has_no_duplicate_ids(self):
        ids = [entry["id"] for entry in INVENTORY["systems"]]
        self.assertEqual(len(ids), len(set(ids)))


class TestChillerKindPresets(unittest.TestCase):

    def setUp(self):
        self.rows = {row["id"]: row for row in CATALOGUE}
        self.golden = {record["id"]: record for record in GOLDEN}

    def test_the_neutral_key_is_only_the_chiller_kind(self):
        for group in INVENTORY["presets"]:
            with self.subTest(base=group["base"]):
                self.assertEqual(group["neutral_keys"], NEUTRAL_KEYS)

    def test_a_preset_differs_from_its_base_only_in_a_neutral_key(self):
        for group in INVENTORY["presets"]:
            base = self.rows[group["base"]]
            ignored = set(IDENTITY_KEYS) | set(NEUTRAL_KEYS)
            for preset_id in group["presets"]:
                with self.subTest(preset=preset_id):
                    preset = self.rows[preset_id]
                    differing = sorted(key for key in set(base) | set(preset)
                                       if key not in ignored and base.get(key) != preset.get(key))
                    self.assertEqual(differing, [], f"{preset_id} differs from {group['base']}")

    def test_a_presets_record_equals_its_bases(self):
        """The kind never changes NECB reference SELECTION (the reference builds
        its own chiller); the record is kept, and must stay equal."""
        for group in INVENTORY["presets"]:
            for preset_id in group["presets"]:
                with self.subTest(preset=preset_id):
                    self.assertEqual(record_sha256(self.golden[preset_id]),
                                     record_sha256(self.golden[group["base"]]))

    def test_each_rows_kind_is_the_one_its_id_names(self):
        """The kind travels to the model as `chiller_type`. A preset without
        one would build its base's scroll chiller under its own id, and one
        whose kind disagrees with its id token names a chiller it does not
        build. Kinds are distinct within a group (Fable, review of #262)."""
        for group in INVENTORY["presets"]:
            members = [group["base"], *group["presets"]]
            with self.subTest(base=group["base"]):
                kinds = []
                for row_id in members:
                    tokens = [t for t in row_id.split("-") if t in KIND_OF_TOKEN]
                    self.assertEqual(len(tokens), 1, row_id)
                    self.assertEqual(self.rows[row_id].get("chiller_type"),
                                     KIND_OF_TOKEN[tokens[0]], row_id)
                    kinds.append(self.rows[row_id]["chiller_type"])
                self.assertEqual(len(kinds), len(set(kinds)))

    def test_every_row_equal_but_for_the_chiller_kind_is_a_declared_group(self):
        """Judged by CONFIGURATION, not by name: rows that differ only in a
        neutral key are exactly one declared preset group, so a new kind
        sibling cannot pass undeclared under any id, and emptying the
        declarations cannot leave this test vacuous (Fable, review of #262)."""
        ignored = set(IDENTITY_KEYS) | set(NEUTRAL_KEYS)
        groups = {}
        for row_id, row in self.rows.items():
            key = json.dumps({k: v for k, v in row.items() if k not in ignored}, sort_keys=True)
            groups.setdefault(key, []).append(row_id)
        found = sorted(sorted(ids) for ids in groups.values() if len(ids) > 1)
        declared = sorted(sorted([group["base"], *group["presets"]])
                          for group in INVENTORY["presets"])
        self.assertEqual(found, declared)
        self.assertEqual(len(declared), 8)
        self.assertEqual(sum(len(g) - 1 for g in declared), 24)

    def test_no_row_is_both_a_base_and_a_preset(self):
        bases = [group["base"] for group in INVENTORY["presets"]]
        presets = [preset for group in INVENTORY["presets"] for preset in group["presets"]]
        self.assertEqual(len(bases), len(set(bases)))
        self.assertEqual(len(presets), len(set(presets)))
        self.assertFalse(set(bases) & set(presets))


if __name__ == "__main__":
    unittest.main()
