"""The decisions drift gate must be reachable from a docs-only change.

`docs/decisions/D-NN.md` is the canonical source of the runtime registry. While
that registry was itself the canonical file, under `python/`, `test.yml`'s
`paths-ignore: ['**.md', 'docs/**']` was harmless: every canonical edit touched
a non-ignored path and so ran CI. Once the canonical source moved into the
ignored region, the gate became anti-correlated with need (Fable, PR #64):

    edit a source AND regenerate -> decisions.json changes -> test.yml runs
    edit a source and FORGET     -> only docs/** changed   -> NOTHING runs

and `main` carries no branch protection or rulesets, so a skipped workflow does
not block a merge. A forgotten regenerate could merge green with a stale runtime
registry.

These tests assert the structural fix rather than a filter's semantics: a
dedicated workflow with NO path filter at all. Modelling GitHub's `paths`
override rules in order to trust a narrowed `paths-ignore` is the same mistake
as modelling its Markdown renderer, which cost five review rounds on this PR.

stdlib only, no YAML dependency: the assertions are about the presence and
absence of keys, which is answerable from the text.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GATE = WORKFLOWS / "decisions.yml"
MAIN = WORKFLOWS / "test.yml"
CHECK = "generate_decisions.py --check"


def top_level_on_block(text: str) -> str:
    """The `on:` block, to the next top-level key."""
    match = re.search(r"(?m)^on:\s*$(.*?)(?=^\S)", text, re.DOTALL)
    return match.group(1) if match else ""


class TestDecisionsGateIsUnskippable(unittest.TestCase):
    def test_the_gate_workflow_exists(self):
        self.assertTrue(GATE.is_file(),
                        f"{GATE.name} is the unskippable drift gate; without it a "
                        "docs-only push can merge a stale runtime registry")

    def test_the_gate_has_no_path_filter(self):
        """The whole point. A filter here would recreate the hole."""
        block = top_level_on_block(GATE.read_text(encoding="utf-8"))
        self.assertTrue(block.strip(), "could not find the gate's on: block")
        for key in ("paths:", "paths-ignore:"):
            self.assertNotIn(
                key, block,
                f"{GATE.name} must carry NO {key.rstrip(':')} — the gate exists "
                "because a path filter made the drift check unreachable from the "
                "change that causes drift")

    def test_the_gate_runs_on_push_and_pull_request(self):
        block = top_level_on_block(GATE.read_text(encoding="utf-8"))
        for event in ("push:", "pull_request:"):
            self.assertIn(event, block, f"{GATE.name} must run on {event}")

    def test_the_gate_actually_runs_the_check(self):
        """A workflow that runs on everything and checks nothing is worse than
        none, because it looks like coverage."""
        self.assertIn(CHECK, GATE.read_text(encoding="utf-8"),
                      f"{GATE.name} must run `{CHECK}`")

    def test_the_gate_needs_no_dependency_install(self):
        """It runs on every push, so it must stay stdlib-only and cheap.

        `-m unittest` rather than pytest, and no `pip install`, so the gate
        cannot be slowed or broken by the dependency set.
        """
        text = GATE.read_text(encoding="utf-8")
        self.assertIn("-m unittest", text)
        self.assertNotIn("pip install", text)

    def test_the_main_workflow_still_ignores_docs_which_is_why_this_exists(self):
        """Pins the premise. If `test.yml` ever stops ignoring `docs/**`, this
        gate becomes redundant rather than load-bearing, and whoever changes
        that should see this test and decide deliberately.
        """
        block = top_level_on_block(MAIN.read_text(encoding="utf-8"))
        self.assertIn("paths-ignore", block,
                      "test.yml no longer filters paths — re-read whether "
                      "decisions.yml is still needed, then update this test")
        self.assertIn("docs/**", block)


if __name__ == "__main__":
    unittest.main()
