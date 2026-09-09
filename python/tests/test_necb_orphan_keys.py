"""Parity and negative controls for the Python orphan-key lint."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT

SCRIPT = REPO_ROOT / "python" / "scripts" / "necb_orphan_keys.py"
SPEC = importlib.util.spec_from_file_location("necb_orphan_keys", SCRIPT)
orphan_keys = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(orphan_keys)


class TestNecbOrphanKeys(unittest.TestCase):
    def test_current_python_rules_have_no_orphans(self):
        findings, manifests, keys = orphan_keys.findings()
        self.assertEqual([], findings)
        # Six rule files per edition, two editions. `efficiencies.json` is a
        # transcribed code table, not a rule manifest, and stays out of scope
        # (orphan_keys.NON_RULE_MANIFESTS).
        self.assertEqual(12, manifests)
        self.assertGreaterEqual(keys, 25)

    def test_unconsumed_key_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edition = root / "family" / "data" / "sample2020"
            edition.mkdir(parents=True)
            (edition / "manifest.json").write_text(json.dumps({
                "id": "sample2020",
                "family": "sample",
                "edition": "2020",
                "label": "Sample 2020",
                "rules": {"sample": "sample_rules.json",
                          "hvac_efficiencies": "efficiencies.json"},
            }), encoding="utf-8")
            (edition / "sample_rules.json").write_text(json.dumps({
                "used": 1,
                "orphan": 2,
                "article_coverage": {"articles": []},
                "non_rule_keys": ["documentation"],
                "documentation": "not a rule",
            }), encoding="utf-8")
            # Declared in the manifest but OUT of the gate's scope: a key only
            # this file declares must not be reported.
            (edition / "efficiencies.json").write_text(
                json.dumps({"never_read_table": []}), encoding="utf-8")
            (root / "family" / "apply.py").write_text(
                "value = rules['used']\n", encoding="utf-8")
            findings, manifests, keys = orphan_keys.findings(root)
            self.assertEqual(1, manifests)
            self.assertEqual(2, keys)
            self.assertEqual([{"key": "orphan",
                               "files": ["sample_rules.json"]}], findings)


if __name__ == "__main__":
    unittest.main()