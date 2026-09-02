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
        self.assertEqual(12, manifests)
        self.assertGreater(keys, 25)

    def test_unconsumed_key_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "domain" / "data"
            data.mkdir(parents=True)
            (data / "sample_rules_2020.json").write_text(json.dumps({
                "used": 1,
                "orphan": 2,
                "article_coverage": {"articles": []},
                "non_rule_keys": ["documentation"],
                "documentation": "not a rule",
            }), encoding="utf-8")
            (root / "domain" / "apply.py").write_text(
                "value = rules['used']\n", encoding="utf-8")
            findings, manifests, keys = orphan_keys.findings(root)
            self.assertEqual(1, manifests)
            self.assertEqual(2, keys)
            self.assertEqual([{"key": "orphan",
                               "files": ["sample_rules_2020.json"]}], findings)


if __name__ == "__main__":
    unittest.main()