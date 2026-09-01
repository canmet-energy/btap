"""Every tracked verification artifact has one explicit D-80 R6 outcome."""

import json
import subprocess
import unittest

from tests.support import REPO_ROOT

DISPOSITION = REPO_ROOT / "verification" / "r6_disposition.json"
OUTCOMES = {"survive", "archive", "port", "delete"}


def _inventory() -> list[str]:
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         "verification"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    return [path for path in files if (REPO_ROOT / path).is_file()]


class TestVerificationDisposition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(DISPOSITION.read_text(encoding="utf-8"))

    def test_every_tracked_file_has_exactly_one_outcome(self):
        classifications = self.data["classifications"]
        self.assertEqual(OUTCOMES, set(classifications))
        tracked = _inventory()
        self.assertGreater(len(tracked), 100, "verification inventory is non-vacuous")

        problems = []
        for path in tracked:
            outcomes = [
                outcome for outcome, rules in classifications.items()
                if path in rules["paths"]
                or any(path.startswith(prefix) for prefix in rules["prefixes"])
            ]
            if len(outcomes) != 1:
                problems.append(f"{path}: outcomes={outcomes}")
        self.assertEqual([], problems, "\n".join(problems))

    def test_rules_are_nonempty_and_not_stale(self):
        classifications = self.data["classifications"]
        tracked = set(_inventory())
        for outcome, rules in classifications.items():
            self.assertTrue(rules["reason"].strip(), f"{outcome} needs a reason")
            for path in rules["paths"]:
                self.assertIn(path, tracked, f"{outcome}: stale path {path}")
            for prefix in rules["prefixes"]:
                self.assertTrue(any(path.startswith(prefix) for path in tracked),
                                f"{outcome}: stale prefix {prefix}")


if __name__ == "__main__":
    unittest.main()