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
#: NAMES, without the colon: a YAML key has more than one spelling, and matching
#: `re.escape("if:")` caught exactly one of four. `"if": false`, `'if': false`
#: and `if : false` are all valid YAML parsing to the key `if`, all honoured by
#: GitHub, and all evaded the first version of this check (Fable, PR #64).
ESCAPE_KEYS = ("if", "continue-on-error")
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


def escape_key_pattern(key: str) -> str:
    """Match ``key`` as a YAML mapping key in any of its spellings.

    Plain, double-quoted, single-quoted, space before the colon, and YAML's
    EXPLICIT KEY form `? if` / `: false` — all valid YAML, all parsing to the
    same key, all honoured by GitHub. The explicit form evaded every assertion in
    this module, and `[-?]` is the whole fix (Fable, PR #64). This still models
    no YAML semantics: it is one key name, matched as a key.

    Two spellings are deliberately NOT covered. A tagged key (`!!str if:`) is
    exotic and whether GitHub's parser honours it is unverified. Anchors and
    aliases are not supported in GitHub workflows at all, so they are not a
    route. Flow mappings (`- {name: x, if: false}`) are caught instead by the
    `run:`-form constraint and the check-runs assertion — the form constraint
    earning its keep rather than a gap.
    """
    return r"(?m)^\s*(?:[-?]\s+)?[\"']?" + re.escape(key) + r"[\"']?\s*:"


def shell_commands(line: str):
    """One executed line split into the commands it actually runs.

    `regen && check` had `--check` somewhere in the line, so a whole-line
    membership test read it as compliant. That was inconsistent with this
    module's own treatment of the check itself, where `--check; true` and
    `--check || true` are already refused: chaining was refused on one line and
    permitted on the other (Fable, PR #64).
    """
    return [part.strip() for part in re.split(r"&&|\|\||;|\|", line) if part.strip()]


def regenerating_steps(text: str):
    """Executed lines that invoke the generator WITHOUT ``--check``.

    A `--check` compares the tree against what the sources generate, so a
    preceding step that regenerates makes it compare identical bytes: green
    forever, committed outputs permanently stale, invisible on an ephemeral
    checkout. No escape key, no path filter, plain `run:` form — it reads as a
    harmless "regenerate first" (Fable, PR #64).

    A helper rather than an inline expression in the test, because the first
    version computed it inline and the falsifying test recomputed the same
    expression: neutering the live assertion to `[]` left the suite green. That
    is the fifth instance in this repository of a check agreeing with its own
    reimplementation, and the fix is always this one.
    """
    return [command for line in executed_lines(text)
            for command in shell_commands(line)
            if "generate_decisions.py" in command and "--check" not in command]


def carries_escape_key(text: str):
    """Which step/job escape keys ``text`` declares anywhere.

    Refused by NAME rather than by evaluating what they would do. `if: false` and
    `continue-on-error: true` each leave the command executed and the workflow
    unable to fail, and no amount of `run:` parsing sees them (Fable, PR #64).
    A legitimate future need for either must change this contract deliberately.
    """
    body = uncommented(text)
    return [key for key in ESCAPE_KEYS
            if re.search(escape_key_pattern(key), body)]


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

    def test_an_escape_key_would_be_detected_in_every_yaml_spelling(self):
        """Each spelling is valid YAML for the same key, so each must be caught.

        The first version matched `re.escape("if:")` and caught one of four.
        """
        for key in ESCAPE_KEYS:
            for spelling in (f"{key}: false", f'"{key}": false',
                             f"'{key}': false", f"{key} : false",
                             f"{key}  :   false",
                             # YAML's EXPLICIT KEY form, which evaded every
                             # assertion in this module (Fable, PR #64)
                             f"? {key}\n        : false"):
                with self.subTest(spelling=spelling):
                    text = ("jobs:\n  d:\n    steps:\n      - name: x\n        "
                            + spelling + "\n        run: " + EXACT_CHECK + "\n")
                    self.assertEqual(
                        [key], carries_escape_key(text),
                        f"{spelling!r} is valid YAML for the key {key!r} and "
                        "GitHub honours it")
        clean = "jobs:\n  d:\n    steps:\n      - run: " + EXACT_CHECK + "\n"
        self.assertEqual([], carries_escape_key(clean))

    def test_a_key_name_inside_another_word_is_not_an_escape_key(self):
        """The arm must refuse keys, not substrings: `notify:` is not `if:`."""
        for innocent in ("notify: true", "verify: all", "if-no-files-found: error",
                         "continue-on-error-policy: strict"):
            with self.subTest(innocent=innocent):
                text = ("jobs:\n  d:\n    steps:\n      - name: x\n        "
                        + innocent + "\n        run: " + EXACT_CHECK + "\n")
                self.assertEqual([], carries_escape_key(text))

    def test_no_step_regenerates_before_checking(self):
        """A `--check` compares the tree with what the sources generate.

        So a preceding step that REGENERATES makes it compare identical bytes:
        permanently green, committed outputs permanently stale, and invisible on
        an ephemeral checkout. No escape key, no path filter, plain `run:` form —
        it reads as a harmless "regenerate first" and was the cheapest bypass
        found in four rounds (Fable, PR #64).
        """
        live = GATE.read_text(encoding="utf-8")
        # The same precondition the path-filter assertion carries, and for the
        # same reason: without it `regenerating_steps("")` satisfies this test
        # vacuously. The asymmetry was real (Fable, PR #64).
        self.assertIn(EXACT_CHECK, executed_lines(live),
                      f"precondition: {GATE.name} must actually run the check, "
                      "or finding no regenerate step proves nothing")
        offenders = regenerating_steps(live)
        self.assertEqual(
            [], offenders,
            f"{GATE.name} must never invoke generate_decisions.py without "
            "--check: regenerating first makes the check compare identical "
            f"bytes and pass forever. Offending step(s): {offenders}")

    def test_regenerating_before_the_check_would_be_detected(self):
        bypass = ("jobs:\n  d:\n    steps:\n"
                  "      - name: regenerate first\n"
                  "        run: python3 python/scripts/generate_decisions.py\n"
                  "      - name: check\n        run: " + EXACT_CHECK + "\n")
        self.assertEqual(1, len(regenerating_steps(bypass)),
                         "the bypass must be detected")
        # chained onto ONE line is the same bypass, and was evading
        for joiner in ("&&", ";", "||", "|"):
            chained = ("jobs:\n  d:\n    steps:\n      - run: python3 "
                       "python/scripts/generate_decisions.py " + joiner + " "
                       + EXACT_CHECK + "\n")
            with self.subTest(joiner=joiner):
                self.assertEqual(1, len(regenerating_steps(chained)),
                                 f"a regenerate chained with {joiner} is still a "
                                 "regenerate before the check")
        clean = "jobs:\n  d:\n    steps:\n      - run: " + EXACT_CHECK + "\n"
        self.assertEqual([], regenerating_steps(clean))
        # and the live gate must actually contain the command, so neutering the
        # detector cannot pass by finding nothing to inspect
        self.assertIn(EXACT_CHECK, executed_lines(GATE.read_text(encoding="utf-8")))

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
