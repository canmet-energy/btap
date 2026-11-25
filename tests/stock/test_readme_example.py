"""The btap.stock README's round trip RUNS as written (#237).

The README's own block is executed — not a copy — so documentation and test
cannot drift. It must rebuild the identified HVAC, refuse nothing, and flag no
unscheduled load, which is what the four #237 reader fixes made true.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.support import needs_sdk

README = Path(__file__).resolve().parents[2] / "src" / "btap" / "stock" / "README.md"


def example_source() -> str:
    text = README.read_text(encoding="utf-8")
    section = text[text.index("## A round trip"):]
    match = re.search(r"```python\n(.*?)```", section, re.S)
    assert match, "the README section lost its python block"
    return match.group(1)


class TestTheExampleUsesThePublicApi(unittest.TestCase):

    def test_no_private_names(self):
        self.assertNotRegex(example_source(), r"\._[a-z]")


@needs_sdk
class TestTheExampleRuns(unittest.TestCase):

    def test_round_trip(self):
        scope: dict = {}
        exec(compile(example_source(), str(README), "exec"), scope)  # noqa: S102
        account, target = scope["account"], scope["target"]
        self.assertEqual([], account["refused"])
        self.assertIn("HVAC 'psz-gas-perzone' (IDENTIFIED) on 16 zone(s)", account["applied"])
        self.assertEqual([], [s for s in account["skipped"] if "NO schedule" in s])
        self.assertEqual(16, len(target.getAirLoopHVACs()))


if __name__ == "__main__":
    unittest.main()
