"""Canonical Python decision-registry, document, and TOC drift gates."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = PYTHON_ROOT.parent

PYTHON_REGISTRY = PYTHON_ROOT / "btap" / "necb" / "data" / "decisions.json"
TOC_SCRIPT = PYTHON_ROOT / "scripts" / "generate_decisions_toc.py"
DECISIONS_DOC = REPO_ROOT / "docs" / "necb_decisions.md"

ID_PATTERN = re.compile(r"^D-\d{2}$")
HEADING_PATTERN = re.compile(r"^## (D-\d{2})\b", re.MULTILINE)


class TestDecisionsRegistrySync(unittest.TestCase):
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
        heading_list = HEADING_PATTERN.findall(doc_text)
        self.assertEqual(
            len(heading_list), len(set(heading_list)),
            "duplicate ## D-XX headings in docs/necb_decisions.md: "
            f"{sorted(h for h in set(heading_list) if heading_list.count(h) > 1)}"
            " — a set comparison alone would collapse them silently")
        heading_ids = set(heading_list)

        missing_headings = registry_ids - heading_ids
        self.assertEqual(
            missing_headings, set(),
            f"decision(s) in the canonical registry have no ## heading in "
            f"docs/necb_decisions.md: {sorted(missing_headings)} — "
            f"author the doc section, then regenerate the TOC")

        missing_entries = heading_ids - registry_ids
        self.assertEqual(
            missing_entries, set(),
            f"## heading(s) in the doc have no canonical registry entry: "
            f"{sorted(missing_entries)} — add the entry to "
            f"python/btap/necb/data/decisions.json (the canonical registry)")

    def test_doc_toc_matches_the_canonical_registry(self):
        result = subprocess.run(
            [sys.executable, str(TOC_SCRIPT), "--check", "--doc", str(DECISIONS_DOC)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
