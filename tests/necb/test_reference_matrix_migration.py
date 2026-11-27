"""The D-58 golden's one-time rename is a pure relabelling (HVAC taxonomy).

D-79 forbids regenerating the D-58 reference-selection golden from Python. The
HVAC rename therefore edited it BY HAND, in its identity paths only, through
the committed legacy -> id bijection. This holds the edit to what it claims
(Astra, taxonomy review finding 4):

- inverse-mapping the committed golden reproduces the PRE-rename file
  byte-for-byte, so no assignment, count, energy type, block or ruling moved;
- every identity value in it is a catalogue id;
- and no catalogue row's CONFIGURATION changed in the rename — only names.

D-113 later RETIRED eight duplicate rows (the NECB System 4 '-necbs4' twins).
`system_retirements.json` keeps each verbatim with its positions, so these
proofs first rebuild the pre-retirement catalogue and golden — byte-checked
against the hashes recorded when they were retired — and then run unchanged.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MIGRATION = json.loads((FIXTURES / "system_id_migration.json").read_text(encoding="utf-8"))
MAPPING = MIGRATION["mapping"]
RETIREMENTS = json.loads((FIXTURES / "system_retirements.json").read_text(encoding="utf-8"))
#: Rows added AFTER the rename and the retirement; neither proof's "before"
#: file contained them.
ADDED = {a["id"] for a in json.loads(
    (FIXTURES / "system_additions.json").read_text(encoding="utf-8"))["added"]}
SYSTEMS = Path(__file__).resolve().parents[2] / "src/btap/modeling/hvac/data/systems.json"
INVERSE = {v: k for k, v in MAPPING.items()}
SCENARIOS = ("catalog_data_processing", "catalog_general_2storey", "catalog_general_3storey",
             "catalog_residential", "scrubbed_data_processing", "scrubbed_general_2storey",
             "scrubbed_general_3storey", "scrubbed_residential")


def _dump(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _sha(value):
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def catalogue_before_retirement():
    """systems.json as it was before D-113, rebuilt from the retirement record."""
    data = json.loads(SYSTEMS.read_text(encoding="utf-8"))
    # D-113 also added the overrides a retired name carries; they are new.
    data = {k: v for k, v in data.items() if k not in ("alias_config", "alias_config_comment")}
    rows = [dict(r) for r in data["systems"] if r["id"] not in ADDED]
    by_id = {r["id"]: r for r in rows}
    for item in RETIREMENTS["retired"]:
        old = item["row"]
        added = [old["id"], old["legacy_name"], *old["aliases"]]
        into = by_id[item["into"]]
        if into["aliases"][-len(added):] != added:
            raise AssertionError(f"{item['id']}: its names are not the tail of {item['into']}'s aliases")
        into["aliases"] = into["aliases"][:-len(added)]
    for item in sorted(RETIREMENTS["retired"], key=lambda i: i["catalogue_index"]):
        rows.insert(item["catalogue_index"], item["row"])
    return {**data, "systems": rows}


def golden_before_retirement(golden):
    """The D-58 golden as it was before D-113: each retired row's record was
    its System 3 row's record under its own id."""
    golden = [g for g in golden if g["id"] not in ADDED]
    by_id = {g["id"]: g for g in golden}
    out = list(golden)
    for item in sorted(RETIREMENTS["retired"], key=lambda i: i["golden_index"]):
        out.insert(item["golden_index"], {**by_id[item["into"]], "id": item["id"]})
    return out


class TestTheRetirementIsLossless(unittest.TestCase):
    """D-113 removed only exact duplicates, and nothing else moved."""

    def test_the_rebuilt_files_are_the_pre_retirement_bytes(self):
        golden = json.loads((FIXTURES / "reference_selection_matrix.json").read_text(encoding="utf-8"))
        self.assertEqual(RETIREMENTS["systems_json_before_sha256"], _sha(catalogue_before_retirement()))
        self.assertEqual(RETIREMENTS["d58_golden_before_sha256"], _sha(golden_before_retirement(golden)))

    def test_each_retired_row_was_its_kept_row_under_other_names(self):
        rows = {r["id"]: r for r in catalogue_before_retirement()["systems"]}
        for item in RETIREMENTS["retired"]:
            old, kept = item["row"], rows[item["into"]]
            with self.subTest(retired=item["id"]):
                self.assertEqual(["aliases", "id", "legacy_name", "sys_abbr"],
                                 sorted(k for k in set(old) | set(kept) if old.get(k) != kept.get(k)))
                self.assertEqual(("sys_4", "sys_3"), (old["sys_abbr"], kept["sys_abbr"]))

    def test_a_retired_name_still_resolves_to_the_row_it_became(self):
        from btap.modeling.hvac import catalog
        for item in RETIREMENTS["retired"]:
            for name in (item["id"], item["row"]["legacy_name"], *item["row"]["aliases"]):
                with self.subTest(name=name):
                    self.assertEqual(item["into"], catalog.resolve(name)["id"])

    def test_a_retired_name_carries_what_made_it_distinct(self):
        """Fable (PR #241): resolving an old System 4 name to the System 3
        row silently built System 3 naming. A retired name resolves to its
        row WITH the retired row's distinguishing config, so every field the
        retired row had, the resolved config has."""
        from btap.modeling.hvac import catalog
        for item in RETIREMENTS["retired"]:
            old = {k: v for k, v in item["row"].items()
                   if k not in ("id", "legacy_name", "aliases", "sizing")}
            for name in (item["id"], item["row"]["legacy_name"], *item["row"]["aliases"]):
                with self.subTest(name=name):
                    got = catalog.resolve(name)
                    self.assertEqual(old, {k: got.get(k) for k in old})


class TestTheGoldenRenameIsARelabelling(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.golden = golden_before_retirement(
            json.loads((FIXTURES / "reference_selection_matrix.json").read_text(encoding="utf-8")))

    def test_the_mapping_is_a_bijection_over_the_catalogue(self):
        self.assertEqual(len(MAPPING), len(set(MAPPING.values())))
        self.assertEqual({r["legacy_name"]: r["id"] for r in catalogue_before_retirement()["systems"]},
                         MAPPING)

    def test_inverse_mapping_reproduces_the_pre_rename_bytes(self):
        back = []
        for row in self.golden:
            out = {}
            for key, value in row.items():
                if key == "id":
                    out["name"] = INVERSE[value]
                elif key in SCENARIOS:
                    out[key] = [{**a, "catalog": INVERSE[a["catalog"]]}
                                if a.get("catalog") is not None else a for a in value]
                else:
                    out[key] = value
            back.append(out)
        self.assertEqual(MIGRATION["d58_golden_before_sha256"],
                         hashlib.sha256(_dump(back).encode("utf-8")).hexdigest())

    def test_every_identity_value_is_an_id(self):
        ids = set(MAPPING.values())
        for row in self.golden:
            self.assertIn(row["id"], ids)
            for key in SCENARIOS:
                for assignment in row[key]:
                    if assignment.get("catalog") is not None:
                        self.assertIn(assignment["catalog"], ids)


class TestNoRowsConfigurationMoved(unittest.TestCase):

    def test_every_row_builds_what_it_built_before(self):
        projection = {}
        for row in catalogue_before_retirement()["systems"]:
            projection[row["id"]] = {
                key: ([{**{k: v for k, v in p.items() if k != "id"}, "ref": p["id"]} for p in value]
                      if key == "parts" else value)
                for key, value in row.items() if key not in ("id", "legacy_name", "aliases")}
        self.assertEqual(MIGRATION["catalogue_configuration_before_sha256"],
                         hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest())


class TestTheAdditionsAreRecorded(unittest.TestCase):
    """Every row added after the rename is in system_additions.json, in both
    files, appended at the END — so removing them restores the earlier bytes."""

    def test_additions_are_appended_in_order_to_both_files(self):
        order = [a["id"] for a in json.loads(
            (FIXTURES / "system_additions.json").read_text(encoding="utf-8"))["added"]]
        rows = [r["id"] for r in json.loads(SYSTEMS.read_text(encoding="utf-8"))["systems"]]
        golden = [g["id"] for g in json.loads(
            (FIXTURES / "reference_selection_matrix.json").read_text(encoding="utf-8"))]
        self.assertEqual(order, rows[-len(order):])
        self.assertEqual(order, golden[-len(order):])

    def test_an_added_row_has_no_retired_names(self):
        from btap.modeling.hvac import catalog
        for row in catalog.rows():
            if row["id"] in ADDED:
                with self.subTest(id=row["id"]):
                    self.assertEqual(row["id"], row["legacy_name"])
                    self.assertEqual([], row["aliases"])


if __name__ == "__main__":
    unittest.main()
