"""Decision-registry sync gate: the packaged Python copy of decisions.json
must be byte-identical to the authoritative Ruby registry, always produced by
``python/scripts/sync_decisions_registry.py`` and never hand-edited.

This is what caught the D-79 drift: the Python copy was a one-time hand
export that fell behind the Ruby registry by one entry (78 vs 79) with
nothing to notice. No SDK import — must run on a bare runner.
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

ID_PATTERN = re.compile(r"^D-\d{2}$")


class TestDecisionsRegistrySync(unittest.TestCase):
    def test_python_copy_is_byte_identical_to_ruby_registry(self):
        ruby_bytes = RUBY_REGISTRY.read_bytes()
        python_bytes = PYTHON_REGISTRY.read_bytes()
        self.assertEqual(
            ruby_bytes, python_bytes,
            f"{PYTHON_REGISTRY} has drifted from the authoritative "
            f"{RUBY_REGISTRY}. Fix: python3 {SYNC_SCRIPT}")

    def test_decision_ids_are_unique_and_well_formed(self):
        with open(PYTHON_REGISTRY, encoding="utf-8") as handle:
            data = json.load(handle)
        ids = [entry["id"] for entry in data["decisions"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate decision ids")
        for decision_id in ids:
            self.assertRegex(decision_id, ID_PATTERN,
                              f"malformed decision id: {decision_id!r}")


if __name__ == "__main__":
    unittest.main()
