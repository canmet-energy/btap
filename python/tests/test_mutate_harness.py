"""Regressions for `scripts/mutate.py`'s verdicts and containment.

WHY THESE EXIST. Every failure mode below was found by a reviewer probing the
script by hand, and the fixes shipped with no committed test — so a later edit
could restore any of them silently. Sol asked for exactly that and he is
right: a tool whose job is to detect dishonest checks is not exempt from
having its own.

Two of these were FALSE GREENS, which is the shape that matters most here:

* a mutant that failed to IMPORT exited nonzero, so it was reported `caught`
  while no assertion had ever seen the mutant;
* a mutant whose run ERRORED (a timeout) was labelled ERROR and then left out
  of the exit condition entirely;
* a mutant that genuinely failed one test AND broke another's setup was
  reported `caught (as declared)`, though part of the suite never ran;
* a `target` was trusted, and because the shadow tree's `tests/` is a SYMLINK
  to the real checkout, a path through it — or an absolute path — WROTE TO
  THE REAL TREE. A matrix typo could have overwritten a collaborator's file.

Each case drives the real `main()` against a tiny throwaway suite, so the
verdict AND the exit status are both pinned. Offline; no product test runs.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "python" / "scripts" / "mutate.py"


def _load():
    spec = importlib.util.spec_from_file_location("mutate_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Harness(unittest.TestCase):
    """A throwaway package and suite, so nothing touches the real tree."""

    def setUp(self):
        self.mutate = _load()
        self.addCleanup(sys.modules.pop, "mutate_under_test", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

        # a minimal `btap`-shaped package for the harness to copy
        package = self.root / "btap"
        (package / "simulation").mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "simulation" / "__init__.py").write_text("", encoding="utf-8")
        # `'ORIGINAL'` deliberately appears TWICE, so a matrix can exercise
        # the "anchor matches many" refusal with a real repeated token.
        (package / "simulation" / "probe.py").write_text(
            "MARKER = 'ORIGINAL'\nALT = 'ORIGINAL'\n", encoding="utf-8")

        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_probe.py").write_text(
            "from btap.simulation.probe import MARKER\n"
            "\n"
            "def test_marker_is_original():\n"
            "    assert MARKER == 'ORIGINAL'\n",
            encoding="utf-8")
        # point the harness at this tree instead of the repository's
        self.mutate.PYTHON_ROOT = self.root

    #: Every verdict the tool can print for one row. Used to assert that
    #: EXACTLY ONE appears — `assertIn` cannot see a second verdict emitted
    #: alongside the first, and with this many states that is the natural
    #: defect (Fable, PR #81).
    VERDICTS = ("*** SURVIVED ***", "*** CAUGHT BY SOMETHING ELSE ***",
                "*** UNVIABLE (no test failed) ***",
                "*** MIXED (failure + error) ***", "*** ERROR ***",
                "caught (as declared)", "caught", "BROKEN")

    def assert_exactly_one_verdict(self, out, label, expected):
        """The row for `label` carries `expected` and no other verdict."""
        rows = [ln for ln in out.splitlines()
                if ln.strip().startswith(label)]
        self.assertEqual(1, len(rows),
                         f"expected one row for {label!r}, got {rows}")
        row = rows[0]
        present = [v for v in self.VERDICTS if v in row]
        # "caught" is a substring of "caught (as declared)", so compare on the
        # longest match rather than counting overlaps.
        longest = max(present, key=len) if present else None
        self.assertEqual(
            expected, longest,
            f"row for {label!r} should read {expected!r}: {row!r}")
        others = [v for v in present
                  if v != expected and v not in expected and expected not in v]
        self.assertEqual([], others,
                         f"a second verdict leaked onto the row: {others}")

    def run_matrix(self, mutations, tests=("tests/test_probe.py",), jobs=2,
                   timeout=None):
        spec = {"target": "btap/simulation/probe.py",
                "tests": list(tests), "mutations": mutations}
        path = self.root / "matrix.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        import contextlib
        import io

        argv = [str(path), "-j", str(jobs)]
        if timeout is not None:
            argv += ["--timeout", str(timeout)]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.mutate.main(argv)
        return code, buffer.getvalue()


class TestFalseGreens(_Harness):
    def test_an_unimportable_mutant_is_UNVIABLE_and_exits_nonzero(self):
        """Nonzero pytest status is not evidence that the gate discriminated."""
        code, out = self.run_matrix([{
            "label": "unimportable",
            "old": "MARKER = 'ORIGINAL'",
            "new": "MARKER = 'ORIGINAL'\nthis is not python",
        }])
        self.assertIn("UNVIABLE", out, out)
        self.assertNotIn("caught", out.replace("UNVIABLE", ""), out)
        self.assertEqual(1, code, "an unviable mutation must not exit 0")

    def test_a_MIXED_failure_and_error_is_not_a_clean_catch(self):
        """Sol's finding: a declared failure plus another test's setup error.

        The declared test really does fail, so `failed` is nonempty — but
        another test never ran, so the row's evidence is incomplete.
        """
        tests = self.root / "tests"
        (tests / "test_errors.py").write_text(
            "import pytest\n"
            "\n"
            "@pytest.fixture\n"
            "def boom():\n"
            "    from btap.simulation import probe\n"
            "    if getattr(probe, 'INJECTED', False):\n"
            "        raise RuntimeError('setup exploded')\n"
            "    return 1\n"
            "\n"
            "def test_uses_the_fixture(boom):\n"
            "    assert boom == 1\n",
            encoding="utf-8")
        code, out = self.run_matrix(
            [{
                "label": "fail-plus-error",
                "old": "MARKER = 'ORIGINAL'",
                "new": "MARKER = 'CHANGED'\nINJECTED = True",
                "expect_failures": ["test_marker_is_original"],
            }],
            tests=("tests/test_probe.py", "tests/test_errors.py"))
        self.assertIn("MIXED", out, out)
        self.assertEqual(1, code, "a mixed failure+error must not exit 0")

    def test_an_inert_mutation_is_BROKEN(self):
        code, out = self.run_matrix([{
            "label": "inert",
            "old": "MARKER = 'ORIGINAL'",
            "new": "MARKER = 'ORIGINAL'",
        }])
        self.assertIn("BROKEN", out, out)
        self.assertEqual(1, code)

    def test_a_MISLABELLED_row_is_not_credited(self):
        """The suite fails, but not where the row says — the stale-row signal."""
        code, out = self.run_matrix([{
            "label": "mislabelled",
            "old": "MARKER = 'ORIGINAL'",
            "new": "MARKER = 'CHANGED'",
            "expect_failures": ["test_some_other_thing_entirely"],
        }])
        self.assertIn("CAUGHT BY SOMETHING ELSE", out, out)
        self.assertEqual(1, code)

    def test_an_honest_row_is_caught_as_declared_and_exits_zero(self):
        """THE CONTROL — the only proof the tool can say "yes".

        Fable corrected my reasoning about this test. I worried that if it
        passed for the wrong reason the others would be vacuous; they would
        not, since each asserts exit 1 or 2 and its own verdict
        independently. Its unique job is narrower and real: without it, a
        harness that ALWAYS reported a problem would satisfy every other case
        here.

        It asserts EXACTLY ONE verdict, not merely that the right one is
        present — a spurious second verdict printed on every row went
        undetected by `assertIn`.
        """
        code, out = self.run_matrix([{
            "label": "honest",
            "old": "MARKER = 'ORIGINAL'",
            "new": "MARKER = 'CHANGED'",
            "expect_failures": ["test_marker_is_original"],
        }])
        self.assert_exactly_one_verdict(out, "honest", "caught (as declared)")
        self.assertEqual(0, code, out)

    def test_an_UNDECLARED_row_that_fails_is_plain_caught(self):
        """The other arm of the ternary whose declared arm is covered."""
        code, out = self.run_matrix([{
            "label": "undeclared",
            "old": "MARKER = 'ORIGINAL'",
            "new": "MARKER = 'CHANGED'",
        }])
        self.assert_exactly_one_verdict(out, "undeclared", "caught")
        self.assertIn("no row declared `expect_failures`", out,
                      "the footer must say the wrong-reason case is "
                      "undetectable without declarations")
        self.assertEqual(0, code, out)

    def test_a_hanging_mutant_is_ERROR_and_exits_nonzero(self):
        """The `rc is None` path — a false green once already, since it was
        labelled ERROR and then left out of the exit condition."""
        code, out = self.run_matrix([{
            "label": "hangs",
            "old": "MARKER = 'ORIGINAL'",
            "new": "MARKER = 'ORIGINAL'\nimport time as _t; _t.sleep(90)",
            "expect_failures": ["test_marker_is_original"],
        }], timeout=10)
        self.assert_exactly_one_verdict(out, "hangs", "*** ERROR ***")
        self.assertEqual(1, code, out)


class TestItCanReportItsOwnReasonForExisting(_Harness):
    """SURVIVED had no test, and that is the worst gap this tool could have.

    Fable replaced the `rc == 0` branch's verdict with `caught (as declared)`
    and dropped the `survived.append(label)` — and all eleven other cases
    still passed. So if that branch ever broke, `mutate.py` would report EVERY
    mutation as caught, exit 0, and hand the next user a clean bill of health
    on a suite that pins nothing.

    In its words: the harness built to catch checks that cannot fail had no
    check that it can report a failure to catch. `SURVIVED` appeared in this
    file only inside the NAME of a test asserting its ABSENCE.
    """

    def test_a_mutation_no_test_observes_is_reported_SURVIVED(self):
        """`ALT` is in the probe module and no test reads it."""
        code, out = self.run_matrix([{
            "label": "unobserved",
            "old": "ALT = 'ORIGINAL'",
            "new": "ALT = 'CHANGED'",
        }])
        self.assert_exactly_one_verdict(out, "unobserved", "*** SURVIVED ***")
        self.assertIn("the tests do not pin", out, out)
        self.assertEqual(1, code, "a survivor is a finding and must exit 1")

    def test_a_surviving_row_is_named_in_the_footer(self):
        """The label has to reach the summary, not only the row."""
        _, out = self.run_matrix([{
            "label": "unobserved-footer",
            "old": "ALT = 'ORIGINAL'",
            "new": "ALT = 'CHANGED'",
        }])
        tail = out[out.index("wall for"):]
        self.assertIn("unobserved-footer", tail,
                      "a survivor must be named where a reader looks last")


class TestContainment(_Harness):
    """The target may not leave the mutant's own copied package."""

    def test_an_absolute_target_is_refused(self):
        outside = self.root / "outside.txt"
        outside.write_text("ORIGINAL\n", encoding="utf-8")
        with tempfile.TemporaryDirectory() as work:
            with self.assertRaises(ValueError) as caught:
                self.mutate.build_mutant(Path(work), 0, str(outside),
                                         "ORIGINAL", "CHANGED")
        self.assertIn("relative", str(caught.exception))
        self.assertEqual("ORIGINAL\n", outside.read_text(encoding="utf-8"),
                         "the file outside the mutant must be untouched")

    def test_a_traversal_target_is_refused(self):
        outside = self.root / "outside.txt"
        outside.write_text("ORIGINAL\n", encoding="utf-8")
        with tempfile.TemporaryDirectory() as work:
            with self.assertRaises(ValueError) as caught:
                self.mutate.build_mutant(Path(work), 0,
                                         "btap/../../outside.txt",
                                         "ORIGINAL", "CHANGED")
        self.assertIn("outside the mutant", str(caught.exception))
        self.assertEqual("ORIGINAL\n", outside.read_text(encoding="utf-8"))

    def test_a_target_under_the_tests_symlink_is_refused(self):
        """The route that actually wrote to the real checkout.

        `tests/` in the shadow is a symlink, so `resolve()` walks out of the
        mutant and a write lands in the real tree.
        """
        victim = self.root / "tests" / "test_probe.py"
        before = victim.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as work:
            with self.assertRaises(ValueError) as caught:
                self.mutate.build_mutant(Path(work), 0,
                                         "tests/test_probe.py",
                                         "ORIGINAL", "CHANGED")
        self.assertIn("outside the mutant", str(caught.exception))
        self.assertEqual(before, victim.read_text(encoding="utf-8"),
                         "a real test file must never be mutated")


class TestSafetyRails(_Harness):
    def test_a_broken_anchor_is_reported_separately_from_a_survivor(self):
        for label, old in (("matches nothing", "NOT_PRESENT_ANYWHERE"),
                           ("matches many", "'ORIGINAL'")):
            with self.subTest(case=label):
                code, out = self.run_matrix([{
                    "label": label, "old": old, "new": old + "_X",
                }])
                self.assertIn("BROKEN", out, out)
                self.assertNotIn("SURVIVED", out, out)
                self.assertEqual(1, code)

    def test_an_unsafe_jobs_count_is_refused_with_the_safe_value(self):
        code, out = self.run_matrix([{
            "label": "never runs", "old": "MARKER = 'ORIGINAL'",
            "new": "MARKER = 'CHANGED'",
        }], jobs=100000)
        self.assertIn("REFUSING", out, out)
        self.assertEqual(2, code)

    def test_a_red_baseline_stops_before_mutating(self):
        """Every mutation would otherwise 'fail' for the wrong reason."""
        (self.root / "tests" / "test_already_red.py").write_text(
            "def test_red():\n    assert False\n", encoding="utf-8")
        code, out = self.run_matrix(
            [{"label": "never runs", "old": "MARKER = 'ORIGINAL'",
              "new": "MARKER = 'CHANGED'"}],
            tests=("tests/test_probe.py", "tests/test_already_red.py"))
        self.assertIn("baseline FAILED", out, out)
        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
