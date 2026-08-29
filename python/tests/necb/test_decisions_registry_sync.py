"""Decision-registry sync gate: the generated Ruby copy of decisions.json
must be byte-identical to the canonical Python registry, always produced by
``python/scripts/sync_decisions_registry.py`` and never hand-edited.

This is what caught the D-79 drift: the Python copy was a one-time hand
export that fell behind the (then-canonical) Ruby registry by one entry (78
vs 79) with nothing to notice. The canonical/generated direction reversed at
R3 (D-81): the Python registry is now canonical and the Ruby copy is
generated from it. No SDK import — must run on a bare runner.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = PYTHON_ROOT.parent

RUBY_REGISTRY = REPO_ROOT / "btap-necb" / "lib" / "btap_necb" / "data" / "decisions.json"
PYTHON_REGISTRY = PYTHON_ROOT / "btap" / "necb" / "data" / "decisions.json"
SYNC_SCRIPT = PYTHON_ROOT / "scripts" / "sync_decisions_registry.py"
DECISIONS_DOC = REPO_ROOT / "btap-necb" / "docs" / "necb_decisions.md"

ID_PATTERN = re.compile(r"^D-\d{2}$")
HEADING_PATTERN = re.compile(r"^## (D-\d{2})\b", re.MULTILINE)


class TestDecisionsRegistrySync(unittest.TestCase):
    def test_generated_ruby_copy_is_byte_identical_to_canonical_python_registry(self):
        ruby_bytes = RUBY_REGISTRY.read_bytes()
        python_bytes = PYTHON_REGISTRY.read_bytes()
        self.assertEqual(
            ruby_bytes, python_bytes,
            f"the GENERATED {RUBY_REGISTRY} has drifted from the canonical "
            f"{PYTHON_REGISTRY}. Fix: python3 {SYNC_SCRIPT}")

    def test_decision_ids_are_unique_and_well_formed(self):
        with open(PYTHON_REGISTRY, encoding="utf-8") as handle:
            data = json.load(handle)
        ids = [entry["id"] for entry in data["decisions"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate decision ids")
        for decision_id in ids:
            self.assertRegex(decision_id, ID_PATTERN,
                              f"malformed decision id: {decision_id!r}")

    def test_doc_headings_mirror_the_canonical_registry(self):
        with open(PYTHON_REGISTRY, encoding="utf-8") as handle:
            data = json.load(handle)
        registry_ids = {entry["id"] for entry in data["decisions"]}

        doc_text = DECISIONS_DOC.read_text(encoding="utf-8")
        heading_ids = set(HEADING_PATTERN.findall(doc_text))

        missing_headings = registry_ids - heading_ids
        self.assertEqual(
            missing_headings, set(),
            f"decision(s) in the canonical registry have no ## heading in "
            f"btap-necb/docs/necb_decisions.md: {sorted(missing_headings)} — "
            f"author the doc section, then regenerate the TOC")

        missing_entries = heading_ids - registry_ids
        self.assertEqual(
            missing_entries, set(),
            f"## heading(s) in the doc have no canonical registry entry: "
            f"{sorted(missing_entries)} — add the entry to "
            f"python/btap/necb/data/decisions.json (the canonical "
            f"registry), then run python3 "
            f"python/scripts/sync_decisions_registry.py")


if __name__ == "__main__":
    unittest.main()
