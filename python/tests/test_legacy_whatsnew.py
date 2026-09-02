"""Fixed-SHA contracts for the Python legacy fork drift reporter."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT

SCRIPT = REPO_ROOT / "python" / "scripts" / "legacy_whatsnew.py"
SPEC = importlib.util.spec_from_file_location("legacy_whatsnew", SCRIPT)
legacy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(legacy)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


class TestLegacyWhatsnew(unittest.TestCase):
    def test_fixed_tip_reports_commit_range_and_owners(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(repo, "init", "-q")
            _git(repo, "config", "user.email", "test@example.invalid")
            _git(repo, "config", "user.name", "R6 test")
            path = repo / "lib" / "openstudio-standards" / "btap"
            path.mkdir(parents=True)
            (path / "geometry.rb").write_text("before\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-qm", "pin")
            pin = _git(repo, "rev-parse", "HEAD")
            (path / "geometry.rb").write_text("after\n", encoding="utf-8")
            data = repo / "data"
            data.mkdir()
            (data / "table.json").write_text("{}\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-qm", "upstream changes")
            tip = _git(repo, "rev-parse", "HEAD")

            result = legacy.report(repo, pin, tip=tip)
            self.assertEqual(tip, result["tip"])
            self.assertEqual(["upstream changes"],
                             [item["subject"] for item in result["commits"]])
            owners = {item["path"]: item["owner"] for item in result["changed"]}
            self.assertEqual("btap.modeling",
                             owners["lib/openstudio-standards/btap/geometry.rb"])
            self.assertEqual("legacy DATA - check whether Python vendored a copy",
                             owners["data/table.json"])


if __name__ == "__main__":
    unittest.main()