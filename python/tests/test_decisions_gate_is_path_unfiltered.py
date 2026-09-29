"""The decisions drift gate is PATH-UNFILTERED and must stay that way.

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
#: The whole command, as its own executed line.
EXACT_CHECK = "python3 python/scripts/generate_decisions.py --check"


COMMENT_RE = re.compile(r"(?m)^\s*#.*$|(?<=\s)#.*$")


def uncommented(text: str) -> str:
    """``text`` with YAML comments removed.

    Every membership assertion below runs on this. Asserting against raw text
    meant a gate could be NEUTERED rather than deleted and still pass: the
    literal survived inside the `#` that disabled it, which is exactly what a
    person does to a gate they find inconvenient (Fable, PR #64).
    """
    return COMMENT_RE.sub("", text)


def run_lines(text: str) -> str:
    """Only what the workflow actually EXECUTES: `run:` values and the block
    scalars under them, comments stripped."""
    kept, in_block, indent = [], False, 0
    for line in uncommented(text).split("\n"):
        stripped = line.strip()
        if re.match(r"^-?\s*run:\s*\|", stripped) or re.match(r"^run:\s*\|", stripped):
            in_block, indent = True, len(line) - len(line.lstrip())
            continue
        if in_block:
            if stripped and (len(line) - len(line.lstrip())) <= indent:
                in_block = False
            else:
                kept.append(stripped)
                continue
        match = re.match(r"^-?\s*run:\s*(\S.*)$", stripped)
        if match:
            kept.append(match.group(1))
    return "\n".join(kept)


PATH_FILTER_KEYS = ("paths:", "paths-ignore:")


def carries_path_filter(text: str):
    """Which path-filter keys ``text``'s `on:` block declares.

    ONE predicate, called by the live assertion and by the synthetic pair
    below. Written inline, the live assertion could be neutered — pointing it at
    an empty string instead of the block — with nothing failing (Fable, PR #64).
    That is the same shape as the stray-file guard it sits beside.
    """
    block = top_level_on_block(text)
    return [key for key in PATH_FILTER_KEYS if key in block]


def exact_run_lines(text: str):
    """Executed lines, stripped and whole, for exact comparison.

    `run_lines` is used for substring questions such as "is there a pip
    install". This one answers "is this EXACT command a line of its own", which
    is what makes a swallowed exit status detectable without modelling the
    shell.
    """
    return [line.strip() for line in run_lines(text).split("\n") if line.strip()]


def top_level_on_block(text: str) -> str:
    """The `on:` block, to the next top-level key, comments stripped."""
    match = re.search(r"(?m)^on:\s*$(.*?)(?=^\S)", uncommented(text), re.DOTALL)
    return match.group(1) if match else ""


class TestDecisionsGateIsPathUnfiltered(unittest.TestCase):
    def test_the_gate_workflow_exists(self):
        self.assertTrue(GATE.is_file(),
                        f"{GATE.name} is the PATH-UNFILTERED drift gate; without "
                        "it a docs-only push can merge a stale runtime registry "
                        "with no run at all")

    def test_the_gate_has_no_path_filter(self):
        """The whole point. A filter here would recreate the hole."""
        block = top_level_on_block(GATE.read_text(encoding="utf-8"))
        self.assertTrue(block.strip(), "could not find the gate's on: block")
        self.assertIn("push:", block, "vacuity floor: the block must be real")
        # Called on the file inline, with no local to swap. Pointing this at
        # anything else is then visibly wrong on the line itself. That bound is
        # REVIEW, not mechanism: a test can always be deleted or redirected, and
        # no test catches its own deletion. What is mechanised is the predicate,
        # which `test_a_path_filter_would_be_detected` falsifies.
        self.assertEqual(
            [], carries_path_filter(GATE.read_text(encoding="utf-8")),
            f"{GATE.name} must carry NO paths/paths-ignore — the gate exists "
            "because a path filter made the drift check unreachable from the "
            "change that causes drift")

    def test_a_path_filter_would_be_detected(self):
        """The falsifying half, through the SAME predicate.

        Without this, the assertion above could be pointed at an empty string
        and nothing would fail (Fable, PR #64).
        """
        for key in PATH_FILTER_KEYS:
            with self.subTest(key=key):
                filtered = ("on:\n  push:\n    " + key + " ['docs/**']\n"
                            "  pull_request:\njobs:\n")
                self.assertEqual([key], carries_path_filter(filtered),
                                 "a real filter must be detected")
        self.assertEqual([], carries_path_filter("on:\n  push:\njobs:\n"),
                         "and an unfiltered block must report none")

    def test_the_gate_runs_on_push_and_pull_request(self):
        block = top_level_on_block(GATE.read_text(encoding="utf-8"))
        for event in ("push:", "pull_request:"):
            self.assertIn(event, block, f"{GATE.name} must run on {event}")

    def test_the_gate_runs_the_check_as_a_failing_command(self):
        """The check must be able to FAIL the step, not merely be executed.

        Substring matching on the executed lines was not enough: `--check
        || true`, `--check; true` and `echo ...--check` all satisfied it while
        the step could no longer fail (Sol, PR #64). Rather than model shell
        semantics, the contract is deliberately rigid — one exact normalized
        line, nothing appended.
        """
        self.assertIn(EXACT_CHECK, exact_run_lines(GATE.read_text(encoding="utf-8")),
                      f"{GATE.name} must run exactly `{EXACT_CHECK}` as its own "
                      "line, with nothing appended that could swallow its exit "
                      "status")

    def test_a_neutralized_check_does_not_satisfy_the_contract(self):
        """The falsifying half, through the same predicate.

        Each of these executes the command and cannot fail the step.
        """
        for suffix, why in ((" || true", "or-true"), ("; true", "semicolon-true"),
                            (" || exit 0", "or-exit-zero"), (" &", "backgrounded")):
            with self.subTest(form=why):
                neutered = ("jobs:\n  d:\n    steps:\n      - run: "
                            + EXACT_CHECK + suffix + "\n")
                self.assertNotIn(EXACT_CHECK, exact_run_lines(neutered),
                                 f"{why} must not satisfy the contract")
        for prefix, why in (("echo ", "echoed"), ("# ", "commented")):
            with self.subTest(form=why):
                neutered = ("jobs:\n  d:\n    steps:\n      - run: "
                            + prefix + EXACT_CHECK + "\n")
                self.assertNotIn(EXACT_CHECK, exact_run_lines(neutered),
                                 f"{why} must not satisfy the contract")
        real = "jobs:\n  d:\n    steps:\n      - run: " + EXACT_CHECK + "\n"
        self.assertIn(EXACT_CHECK, exact_run_lines(real),
                      "and the real form must satisfy it")

    def test_the_on_block_extractor_can_fail(self):
        """`top_level_on_block` returning everything, or nothing, must not pass.

        Both mutations survived: an always-empty extractor and one returning the
        whole file. The latter slipped through because this module's own header
        writes `paths-ignore` without a colon, so the membership test did not
        fire on it (Fable, PR #64).
        """
        self.assertEqual("", top_level_on_block("name: x\njobs: {}\n"),
                         "no on: block means no block")
        block = top_level_on_block("on:\n  push:\n    paths-ignore: ['a']\njobs:\n")
        self.assertIn("paths-ignore:", block,
                      "a real filter must be visible to the assertions")
        self.assertNotIn("jobs:", block,
                         "the extractor must stop at the next top-level key")

    def test_the_gate_needs_no_dependency_install(self):
        """It runs on every push, so it must stay stdlib-only and cheap.

        `-m unittest` rather than pytest, and no `pip install`, so the gate
        cannot be slowed or broken by the dependency set.
        """
        executed = run_lines(GATE.read_text(encoding="utf-8"))
        self.assertIn("-m unittest", executed)
        # Against raw text this would fail wrongly on a comment mentioning pip.
        self.assertNotIn("pip install", executed)

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
