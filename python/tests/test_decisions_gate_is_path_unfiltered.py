"""The decisions drift gate is PATH-UNFILTERED, and must stay that way.

`docs/decisions/D-NN.md` is the canonical source of the runtime registry. While
that registry was itself canonical, under `python/`, `test.yml`'s
`paths-ignore: ['**.md', 'docs/**']` was harmless: every canonical edit touched a
non-ignored path and so ran CI. Once the canonical source moved into the ignored
region the gate became anti-correlated with need (Fable, PR #64):

    edit a source AND regenerate -> decisions.json changes -> test.yml runs
    edit a source and FORGET     -> only docs/** changed   -> NOTHING runs

## What is mechanised here, and what is not

Mechanised: the workflow exists; its `on:` block declares no path filter; the
check runs as its own exact command that can fail the step; the workflow
declares no step- or job-level escape (`if:`, `continue-on-error:`); it needs no
dependency install.

**Not mechanised, and deliberately not attempted:** that the workflow *gates*.
"The literal appears in a `run:` value" cannot express that, and trying to make
it express that is a losing game — a first attempt closed one spelling
(commenting out) and left `|| true`, `; true`, `echo`, `if: false` and
`continue-on-error: true`; closing those three by exact-line matching still left
the last two, and the parser began rejecting valid workflows (`run: >`) into the
bargain (Fable, PR #64). This module therefore refuses the escape keys by NAME —
bounded, exact, no shell or YAML semantics modelled — and constrains the `run:`
form of a file this repository owns rather than parsing the general language.

The residual is stated rather than implied: GitHub-side disabling, `[skip ci]` in
a head commit message, and a filter or escape introduced somewhere this module
does not read are bounded by review, not by this test. `--check`'s own gating
behaviour IS mechanised, in
`tests/necb/test_decisions_generator.py::TestCheckReportsStaleWithoutWriting`.

stdlib only: every assertion is about the presence or absence of exact text,
which needs no YAML dependency.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GATE = WORKFLOWS / "decisions.yml"
MAIN = WORKFLOWS / "test.yml"

#: The whole command, as its own executed line.
EXACT_CHECK = "python3 python/scripts/generate_decisions.py --check"
#: Keys that let a step or job run without being able to fail the workflow.
ESCAPE_KEYS = ("if:", "continue-on-error:")
PATH_FILTER_KEYS = ("paths:", "paths-ignore:")

COMMENT_RE = re.compile(r"(?m)^\s*#.*$|(?<=\s)#.*$")
#: The one `run:` form this workflow is allowed to use. Constraining the form of
#: a file we own is what removes the need to parse the forms we do not use: a
#: rewrite into `run: >` or flow style fails loudly and deliberately, instead of
#: silently passing an assertion that no longer finds the command.
PLAIN_RUN_RE = re.compile(r"(?m)^\s*(?:-\s+)?run:\s*(?:\||$)|^\s*(?:-\s+)?run:\s*(\S.*)$")


def uncommented(text: str) -> str:
    """``text`` with YAML comments removed.

    Every membership assertion runs on this. Against raw text a gate could be
    NEUTERED rather than deleted and still pass: the literal survived inside the
    `#` that disabled it, which is what a person does to a gate they find
    inconvenient (Fable, PR #64).
    """
    return COMMENT_RE.sub("", text)


def executed_lines(text: str):
    """Every line the workflow executes, stripped, comments removed.

    Covers only the two `run:` forms the gate is allowed to use — a plain
    command, and a `|` literal block. That is not a general YAML reader and does
    not pretend to be; `test_the_gate_uses_only_the_plain_run_form` is what makes
    the restriction safe by refusing any other form outright.
    """
    kept, in_block, indent = [], False, 0
    for line in uncommented(text).split("\n"):
        stripped = line.strip()
        if re.match(r"^-?\s*run:\s*\|", stripped):
            in_block, indent = True, len(line) - len(line.lstrip())
            continue
        if in_block:
            if stripped and (len(line) - len(line.lstrip())) <= indent:
                in_block = False
            else:
                if stripped:
                    kept.append(stripped)
                continue
        match = re.match(r"^-?\s*run:\s*(\S.*)$", stripped)
        if match:
            kept.append(match.group(1).strip())
    return kept


def top_level_on_block(text: str) -> str:
    """The `on:` block, to the next top-level key, comments stripped."""
    match = re.search(r"(?m)^on:\s*$(.*?)(?=^\S)", uncommented(text), re.DOTALL)
    return match.group(1) if match else ""


def carries_path_filter(text: str):
    """Which path-filter keys ``text``'s `on:` block declares.

    ONE predicate, exercised below against the live file and synthetic cases in
    a single table, so redirecting the call cannot go unnoticed (Fable, PR #64).
    """
    block = top_level_on_block(text)
    return [key for key in PATH_FILTER_KEYS if key in block]


def carries_escape_key(text: str):
    """Which step/job escape keys ``text`` declares anywhere.

    Refused by NAME rather than by evaluating what they would do. `if: false` and
    `continue-on-error: true` each leave the command executed and the workflow
    unable to fail, and no amount of `run:` parsing sees them (Fable, PR #64).
    A legitimate future need for either must change this contract deliberately.
    """
    body = uncommented(text)
    return [key for key in ESCAPE_KEYS
            if re.search(r"(?m)^\s*(?:-\s+)?" + re.escape(key), body)]


class TestDecisionsGateIsPathUnfiltered(unittest.TestCase):
    def test_the_gate_workflow_exists(self):
        self.assertTrue(GATE.is_file(),
                        f"{GATE.name} is the path-unfiltered drift gate; without "
                        "it a docs-only push can merge a stale runtime registry "
                        "with no run at all")

    def test_no_path_filter_live_or_synthetic(self):
        """One predicate, one table, live case and falsifying cases together.

        Asserting the live case alone left the call redirectable to an empty
        string with nothing failing. Putting both in one table mechanises that
        mutation instead of bounding it by review (Fable, PR #64).
        """
        live = GATE.read_text(encoding="utf-8")
        # The precondition is what actually mechanises the redirect mutation.
        # A shared table does NOT: the live row expects [], so swapping its
        # input for "" — which also yields [] — passes. Reproduced against
        # Fable's suggested table before adding this line.
        self.assertIn(EXACT_CHECK, live,
                      "precondition: the live case must really be the gate file")
        cases = [
            (live, [], "the committed gate"),
            ("on:\n  push:\n    paths-ignore: ['docs/**']\njobs:\n",
             ["paths-ignore:"], "a paths-ignore filter"),
            ("on:\n  push:\n    paths: ['python/**']\njobs:\n",
             ["paths:"], "a paths filter"),
            ("on:\n  push:\n  pull_request:\njobs:\n", [], "an unfiltered block"),
        ]
        for text, expected, label in cases:
            with self.subTest(case=label):
                self.assertEqual(expected, carries_path_filter(text))

    def test_the_gate_runs_on_every_relevant_event(self):
        block = top_level_on_block(GATE.read_text(encoding="utf-8"))
        self.assertTrue(block.strip(), "could not find the gate's on: block")
        for event in ("push:", "pull_request:", "merge_group:"):
            self.assertIn(event, block, f"{GATE.name} must run on {event}")

    def test_the_check_runs_as_a_command_that_can_fail(self):
        """Exact line, nothing appended.

        `--check || true`, `--check; true` and `echo ...--check` each execute the
        command and cannot fail the step (Sol, PR #64), so substring matching on
        executed lines is not enough.
        """
        self.assertIn(EXACT_CHECK, executed_lines(GATE.read_text(encoding="utf-8")),
                      f"{GATE.name} must run exactly `{EXACT_CHECK}` as its own "
                      "line, with nothing appended that could swallow its exit "
                      "status")

    def test_a_neutralized_check_does_not_satisfy_the_contract(self):
        for form, why in ((EXACT_CHECK + " || true", "or-true"),
                          (EXACT_CHECK + "; true", "semicolon-true"),
                          (EXACT_CHECK + " || exit 0", "or-exit-zero"),
                          (EXACT_CHECK + " &", "backgrounded"),
                          ("echo " + EXACT_CHECK, "echoed"),
                          ("# " + EXACT_CHECK, "commented")):
            with self.subTest(form=why):
                text = "jobs:\n  d:\n    steps:\n      - run: " + form + "\n"
                self.assertNotIn(EXACT_CHECK, executed_lines(text),
                                 f"{why} must not satisfy the contract")
        real = "jobs:\n  d:\n    steps:\n      - run: " + EXACT_CHECK + "\n"
        self.assertIn(EXACT_CHECK, executed_lines(real),
                      "and the real form must satisfy it")

    def test_the_gate_declares_no_escape_key(self):
        """`if:` and `continue-on-error:` leave a step executed but unfailing.

        No `run:` parsing sees these, which is why they are refused by name
        (Fable, PR #64).
        """
        self.assertEqual(
            [], carries_escape_key(GATE.read_text(encoding="utf-8")),
            f"{GATE.name} must declare no {' or '.join(ESCAPE_KEYS)} — either "
            "lets the check run without being able to fail the workflow. A real "
            "need for one must change this contract deliberately")

    def test_an_escape_key_would_be_detected(self):
        for key in ESCAPE_KEYS:
            with self.subTest(key=key):
                text = ("jobs:\n  d:\n    steps:\n      - name: x\n        "
                        + key + " false\n        run: " + EXACT_CHECK + "\n")
                self.assertEqual([key], carries_escape_key(text))
        clean = "jobs:\n  d:\n    steps:\n      - run: " + EXACT_CHECK + "\n"
        self.assertEqual([], carries_escape_key(clean))

    def test_the_gate_uses_only_the_plain_run_form(self):
        """A style constraint on a file we own, in place of a YAML parser.

        `executed_lines` reads a plain command and a `|` block and nothing else.
        Rather than widen it to folded scalars and flow mappings — where a first
        attempt produced FALSE failures on valid workflows (Fable, PR #64) — the
        workflow is required to keep the form the reader covers. A deliberate
        rewrite must update this contract; a silent one fails here.
        """
        body = uncommented(GATE.read_text(encoding="utf-8"))
        for offending, why in ((r"(?m)^\s*(?:-\s+)?run:\s*>", "a folded scalar"),
                               (r"(?m)^\s*-\s*\{", "a flow-style step mapping")):
            self.assertIsNone(
                re.search(offending, body),
                f"{GATE.name} uses {why}, which this module's reader does not "
                "cover; keep the plain `run:` form or update the contract")
        self.assertTrue(executed_lines(body), "vacuity floor: something must run")

    def test_the_gate_needs_no_dependency_install(self):
        """It runs on every push, so it stays stdlib-only and cheap."""
        executed = "\n".join(executed_lines(GATE.read_text(encoding="utf-8")))
        self.assertIn("-m unittest", executed)
        self.assertNotIn("pip install", executed)

    def test_the_main_workflow_still_ignores_docs_which_is_why_this_exists(self):
        """Pins the premise. If `test.yml` stops ignoring `docs/**`, this gate
        becomes redundant rather than load-bearing, and whoever changes that
        should see this test and decide deliberately."""
        block = top_level_on_block(MAIN.read_text(encoding="utf-8"))
        self.assertIn("paths-ignore", block,
                      "test.yml no longer filters paths — re-read whether "
                      "decisions.yml is still needed, then update this test")
        self.assertIn("docs/**", block)


if __name__ == "__main__":
    unittest.main()
