"""The D-58 golden's one-time rename is a pure relabelling (HVAC taxonomy).

D-79 forbids regenerating the D-58 reference-selection golden from Python. The
HVAC rename therefore edited it BY HAND, in its identity paths only, through
the committed legacy -> id bijection. This holds the edit to what it claims
(Astra, taxonomy review finding 4):

- inverse-mapping the committed golden reproduces the PRE-rename file
  byte-for-byte, so no assignment, count, energy type, block or ruling moved;
- every identity value in it is a catalogue id;
- and no catalogue row's CONFIGURATION changed in the rename — only names.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MIGRATION = json.loads((FIXTURES / "system_id_migration.json").read_text(encoding="utf-8"))
MAPPING = MIGRATION["mapping"]
INVERSE = {v: k for k, v in MAPPING.items()}
SCENARIOS = ("catalog_data_processing", "catalog_general_2storey", "catalog_general_3storey",
             "catalog_residential", "scrubbed_data_processing", "scrubbed_general_2storey",
             "scrubbed_general_3storey", "scrubbed_residential")


def _dump(value):
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


class TestTheGoldenRenameIsARelabelling(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads((FIXTURES / "reference_selection_matrix.json").read_text(encoding="utf-8"))

    def test_the_mapping_is_a_bijection_over_the_catalogue(self):
        from btap.modeling.hvac import catalog
        self.assertEqual(len(MAPPING), len(set(MAPPING.values())))
        self.assertEqual({r["legacy_name"]: r["id"] for r in catalog.rows()}, MAPPING)

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
        from btap.modeling.hvac import catalog
        projection = {}
        for row in catalog.rows():
            projection[row["id"]] = {
                key: ([{**{k: v for k, v in p.items() if k != "id"}, "ref": p["id"]} for p in value]
                      if key == "parts" else value)
                for key, value in row.items() if key not in ("id", "legacy_name", "aliases")}
        self.assertEqual(MIGRATION["catalogue_configuration_before_sha256"],
                         hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
