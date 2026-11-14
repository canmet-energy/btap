"""SDK-binding invariants, enforced mechanically rather than documented.

D-79 records that ``.get()`` on an unchecked SDK Optional is unsafe in the
Python bindings in a way it is not in Ruby. Measured on 3.11.0 (#164),
unwrapping an EMPTY optional has three possible outcomes and the choice is not
a stable function of the type:

- SEGFAULT, for 615 of the 617 ``Optional*`` names in ``openstudio.model`` —
  every NON-DEFAULT-CONSTRUCTIBLE one. Mostly model objects, but 23 wrap
  other value types (``ClimateZone``, ``ViewFactor``, ``ScheduleTypeKey``, …),
  so the dividing line is constructibility and not being a ``ModelObject``. History-independent. A crash takes the
  xdist worker with it and reports as a lost node, not a failure. This is what
  a failed ``to_X()`` cast returns and what the optional accessors
  (``.thermalZone()``, ``.construction()``, …) return.
- ``SystemError`` caused by ``RuntimeError: Optional not initialized``. The
  value optionals do this on their first call.
- a DEFAULT-CONSTRUCTED object, silently. ``OptionalModel`` and
  ``OptionalScheduleType`` do this in a fresh interpreter — the behaviour
  behind the catalog report's 97 "diagram unavailable" cards.

Which of the last two a default-constructible optional gives depends on the
process's history, per class. This file pins the two sequences that ANCHOR the
hazard and deliberately does not pin the rest: two attempts to state a general
rule for the ordering (#164) each described behaviour the SDK does not have,
so the documented position is "state-dependent, never rely on it".

Issue #141 was one instance. A probe in
``tests/modeling/test_catalog_report.py`` asserted the fresh-interpreter
behaviour IN-PROCESS, where a predecessor in its xdist worker had constructed
a ``Model()``. It was NOT stale error-indicator residue, which is what this
file and ``btap._compat.opt`` both claimed before #164 — the raising case
clears the indicator. Residue is real but comes from a SURVIVING unwrap, and
then lands on an unrelated call.

Stating that in a docstring is not enough — the rule was written down and
then violated four times by copy-paste within a day. This test makes it
mechanical, so the next copy-paste fails in CI instead of shipping.
"""

import re
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent.parent

# `Model.load(...)` followed by `.get()` with no emptiness check between.
# Narrow on purpose: this is the pattern that fails SILENTLY, and a narrow
# rule with no false positives gets obeyed where a broad one gets suppressed.
UNCHECKED_LOAD = re.compile(r"\.load\([^\n]*\)\s*\.get\(\)", re.MULTILINE)

# btap/_sdk.py is the one sanctioned implementation (it checks
# is_initialized() first); this file is the rule's own definition site and
# necessarily quotes the pattern in its message and its hazard test.
ALLOWED = {"btap/_sdk.py", "tests/test_sdk_invariants.py"}


class TestNoUncheckedOptionalGet(unittest.TestCase):
    def test_no_unchecked_model_load_get(self):
        offenders = []
        for path in sorted(PYTHON_ROOT.rglob("*.py")):
            rel = path.relative_to(PYTHON_ROOT).as_posix()
            # Match on path PARTS, not substrings: a build/ or .venv/ at the
            # root has no leading slash, and substring matching silently
            # missed it (found the hard way — a stale build/ tree from an
            # earlier wheel build flagged the sanctioned loader's own copy).
            parts = set(path.relative_to(PYTHON_ROOT).parts)
            if rel in ALLOWED or parts & {".venv", ".ci-venv", "build", "dist"}:
                continue
            text = path.read_text(encoding="utf-8")
            for match in UNCHECKED_LOAD.finditer(text):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{rel}:{line}: {match.group(0).strip()}")

        self.assertEqual(
            [], offenders,
            "unchecked Model.load(...).get() — an empty optional yields an EMPTY "
            "MODEL here, it does not raise. Use btap._sdk.load_model(path), or "
            "btap._compat.opt(). Offenders:\n  " + "\n  ".join(offenders))

    def test_the_documented_hazard_still_holds(self):
        # If a future SDK release makes .get() raise properly, this fails and
        # the whole invariant can be revisited rather than cargo-culted.
        #
        # Probed in a SUBPROCESS: .get() on an empty optional can leave the
        # C-level error indicator set (the very hazard family this file
        # documents), and in-process that detonated on the NEXT attribute
        # lookup as a spurious AttributeError ('...has no attribute
        # 'assertEqual'') — poisoning the test runner itself. Isolation
        # makes the probe deterministic; the markers are printed before any
        # further SDK call so a post-probe detonation cannot hide them.
        try:
            import openstudio  # noqa: F401
        except ImportError:
            self.skipTest("needs the openstudio wheel")

        import subprocess
        import sys
        probe = (
            "import openstudio\n"
            "empty = openstudio.model.Model.load("
            "openstudio.path('/nonexistent.osm'))\n"
            "assert not empty.is_initialized()\n"
            "model = empty.get()\n"  # would raise here if the SDK were fixed
            "print('GOT_MODEL', flush=True)\n"
            "print('SPACES', len(model.getSpaces()), flush=True)\n"
            "print('ZONES', len(model.getThermalZones()), flush=True)\n"
        )
        out = subprocess.run([sys.executable, "-c", probe],
                             capture_output=True, text=True, check=False,
                             timeout=120)
        self.assertIn("GOT_MODEL", out.stdout,
                      ".get() on an empty optional RAISED — the documented "
                      "hazard no longer holds; revisit the load_model "
                      f"invariant. stderr: {out.stderr[:400]}")
        self.assertIn("SPACES 0", out.stdout,
                      "empty optional yielded a populated model — invariant "
                      f"changed. stdout: {out.stdout[:200]}")
        # ZONES carries what the catalog report actually reads. It used to be
        # asserted by a SECOND, IN-PROCESS copy of this probe in
        # tests/modeling/test_catalog_report.py, which issue #141 caught
        # failing under some xdist layouts. The cause was not residue from a
        # predecessor's error: it was a predecessor having constructed a
        # `Model()`, after which `OptionalModel.get()` RAISES in that process
        # instead of returning an empty model. A subprocess has constructed
        # none, so it sees the first-call behaviour this test is about.
        self.assertIn("ZONES 0", out.stdout,
                      "empty optional yielded a model WITH zones — the trap "
                      "the catalog report depends on has changed. stdout: "
                      f"{out.stdout[:200]}")

    def test_a_model_object_optional_CRASHES_rather_than_raising(self):
        """The third family, and the worst: `.get()` kills the process.

        `OptionalModel` returns an empty model and `OptionalDouble` raises, so
        it would be reasonable to assume the rest merely raise too. They do
        not: 615 of the 617 `Optional*` names in `openstudio.model` segfault
        the interpreter immediately, swept one subprocess per type on 3.11.0.
        `OptionalModel` and `OptionalScheduleType` are the only survivors.

        This is the family a FAILED `to_X()` cast returns, which is why the
        rule is `opt()` and not "check the ones that raise". Asserting the
        crash is the point: if a future SDK release makes these raise, this
        test fails and the hazard can be downgraded deliberately instead of
        being carried forever as folklore.
        """
        try:
            import openstudio  # noqa: F401
        except ImportError:
            self.skipTest("needs the openstudio wheel")

        import signal
        import subprocess
        import sys
        probe = (
            "import openstudio\n"
            "opt = openstudio.model.OptionalAirLoopHVAC()\n"
            "assert not opt.is_initialized()\n"
            "print('BEFORE', flush=True)\n"
            "try:\n"
            "    opt.get()\n"
            "    print('NO_RAISE', flush=True)\n"
            "except BaseException as e:\n"
            "    print('RAISED', type(e).__name__, flush=True)\n"
        )
        # NO `-I`: the `verify` job's interpreter gets the SDK from
        # PYTHONPATH (/usr/local/openstudio-3.11.0/Python), and isolated mode
        # ignores PYTHONPATH, so `import openstudio` would fail there and the
        # probe would die before reaching `.get()`. The BEFORE assertion below
        # would catch that as a failure rather than a false pass, but the lane
        # would be red for the wrong reason. The sibling probe above omits
        # `-I` for the same reason. (Fable, review of this PR; reproduced with
        # `PYTHONPATH=<sdk> /usr/bin/python3 -I -c 'import openstudio'`.)
        out = subprocess.run([sys.executable, "-c", probe],
                             capture_output=True, text=True, check=False,
                             timeout=120)
        self.assertIn("BEFORE", out.stdout,
                      "the probe did not reach the .get() call at all, so this "
                      f"test proves nothing. stderr: {out.stderr[:300]}")
        # A segfault leaves the returncode negative (-signal) and prints
        # neither marker. Assert the ABSENCE of both markers together with the
        # abnormal exit, so a clean raise cannot pass as a crash.
        self.assertNotIn("NO_RAISE", out.stdout, out.stdout[:200])
        self.assertNotIn("RAISED", out.stdout,
                         "a ModelObject optional RAISED instead of crashing — "
                         "the SDK may have been fixed. Revisit the opt() "
                         f"docstring and D-79. stdout: {out.stdout[:200]}")
        # SIGSEGV specifically, not merely "a signal": the docstring claims a
        # segfault, and all 615 of the crashing family die with -11. A test
        # that accepted any signal would also pass on a SIGABRT or an external
        # kill, neither of which is what is being documented.
        self.assertEqual(-signal.SIGSEGV, out.returncode,
                         "expected death by SIGSEGV; got "
                         f"{out.returncode}. stdout: {out.stdout[:200]}")

    def test_constructing_a_Model_flips_OptionalModel_to_RAISING(self):
        """The fresh-interpreter half of #141's mechanism. The flip is NOT
        asserted, because it is not reliable on the floor interpreter.

        `opt()` and this file once described the hazard as a stale C error
        indicator left by a raising `.get()` for a later call to trip over.
        That is not what happens — the raise clears the indicator. What
        happens is that an unwrap of an empty default-constructible optional
        returns a default object in a fresh interpreter, and USUALLY raises
        once something has constructed a `Model()`. That is #141's mechanism:
        the flaky probe's result depended on whether a predecessor in its
        xdist worker had built one, which nearly every SDK test does.

        **Usually, not always.** This test asserted the flip until it turned
        `main` red (issue #167, at `843aa932`): on CPython 3.11 the
        post-`Model()` unwrap silently returns a default about 2% of the time
        — measured 1 of 60 here, and the CI `python` job hit it. A reviewer
        had flagged a sibling probe shape as nondeterministic on 3.11 (9
        silent defaults in 65) and I accepted 80 clean runs of THIS shape as
        proof it was immune. Eighty runs cannot distinguish 2% from zero; the
        expected count is 1.6.

        So only the CONTROL is asserted — a fresh interpreter yields an EMPTY
        MODEL, which is the silent-flow hazard `opt()` exists for and was
        stable in every sample on both interpreters. The post-`Model()` case
        is probed and its outcome recorded in the failure message, so a run
        that sees the rare branch says so instead of failing.
        """
        try:
            import openstudio  # noqa: F401
        except ImportError:
            self.skipTest("needs the openstudio wheel")

        import subprocess
        import sys

        def probe(construct_first):
            body = (
                "import openstudio\n"
                + ("openstudio.model.Model()\n" if construct_first else "")
                + "empty = openstudio.model.Model.load("
                  "openstudio.path('/nonexistent.osm'))\n"
                  "assert not empty.is_initialized()\n"
                  "try:\n"
                  "    m = empty.get()\n"
                  "    print('NO_RAISE', len(m.getSpaces()), flush=True)\n"
                  "except SystemError as e:\n"
                  "    print('RAISED', type(e.__cause__).__name__, flush=True)\n"
            )
            out = subprocess.run([sys.executable, "-c", body],
                                 capture_output=True, text=True, check=False,
                                 timeout=120)
            self.assertEqual(0, out.returncode,
                             f"probe died: {out.stderr[-300:]}")
            return out.stdout

        self.assertIn("NO_RAISE 0", probe(construct_first=False),
                      "in a fresh interpreter the empty optional must still "
                      "yield an EMPTY MODEL — if this changed, the silent-flow "
                      "hazard is gone and D-79 can be revisited")

        # The post-`Model()` case is NOT asserted either way: it raises about
        # 98% of the time on 3.11 and returning a default is the other 2%.
        # Both outcomes are accepted and the one seen is named, so this cannot
        # go red on the rare branch — which is exactly how it broke `main`.
        after = probe(construct_first=True)
        self.assertTrue(
            'RAISED RuntimeError' in after or 'NO_RAISE' in after,
            "after a Model(), the unwrap must either raise SystemError caused "
            "by RuntimeError (the usual outcome, and #141's mechanism) or "
            "return a default model (~2% on 3.11). Anything else means the "
            f"behaviour has changed and D-79 needs revisiting. Saw: {after!r}")

    def test_a_value_optional_RAISES_on_its_very_first_call(self):
        """The third family, pinned — and not where I first put it.

        `opt()` grouped the value optionals with `OptionalModel` as
        "returns a default the first time", which is simply false: they raise
        immediately in a fresh interpreter. Pinned in a subprocess so "first
        call" means it, and so a crash cannot take the runner down with it.
        """
        try:
            import openstudio  # noqa: F401
        except ImportError:
            self.skipTest("needs the openstudio wheel")

        import subprocess
        import sys
        probe = (
            "import openstudio\n"
            "for name in ('OptionalDouble', 'OptionalString', 'OptionalInt'):\n"
            "    try:\n"
            "        getattr(openstudio, name)().get()\n"
            "        print(name, 'NO_RAISE', flush=True)\n"
            "    except SystemError as e:\n"
            "        print(name, 'RAISED',\n"
            "              type(e.__cause__).__name__, flush=True)\n"
        )
        out = subprocess.run([sys.executable, "-c", probe],
                             capture_output=True, text=True, check=False,
                             timeout=120)
        self.assertEqual(0, out.returncode,
                         f"probe died: {out.stderr[-300:]}")
        for name in ('OptionalDouble', 'OptionalString', 'OptionalInt'):
            self.assertIn(f"{name} RAISED RuntimeError", out.stdout,
                          f"{name} must raise on its FIRST unwrap in a fresh "
                          f"interpreter. stdout: {out.stdout[:300]}")

    # THE RESIDUE TRAP IS PINNED ONLY IN THE HALF THAT IS PORTABLE, because
    # HOW it fails differs by interpreter while THAT it fails does not.
    #
    # The trap: D-79 said the RAISING unwrap leaves the C error indicator set.
    # It does not. After `g M g` — unwrap, construct a `Model()`, unwrap again
    # — the NEXT CHECKED C CALL raises `SystemError` caused by
    # `RuntimeError: Optional not initialized`. Any checked call: a bare
    # `[].append(0)` shows it as readily as an SDK call, which is what makes an
    # unguarded `.get()` hard to diagnose. The error is set DURING that call,
    # not left pending before it (`PyErr_Occurred()` reads clear in the same
    # position, and `gc.disable()`/`gc.freeze()` change nothing). No mechanism
    # is claimed.
    #
    # What cannot be pinned is a single outcome. The SECOND unwrap does not do
    # the same thing on both interpreters:
    #
    #   CPython 3.12  it SURVIVES, and the sentinel after it is poisoned
    #   CPython 3.11  it RAISES, so a probe never reaches a sentinel at all
    #
    # Each is 10/10 deterministic on its own interpreter, so this is a clean
    # split rather than a flake: whichever outcome a test asserts, it is right
    # on one interpreter and wrong on the other.
    #
    # 3.11 is the project floor (`test.yml` pins it for `lint` and `python`),
    # 3.12 is what the CI image and local venvs run, so a pin asserting EITHER
    # outcome passes one job and fails the other. A probe written against 3.12
    # turned the `python` job red at `def9930d` with `probe died (rc=1)` — the
    # interpreter difference, not a flake.
    #
    # What IS portable, and is pinned below, is that the sequence is NEVER a
    # silent default: 30/30 poisoned on 3.12 and 30/30 raising on 3.11, with
    # the control clean 30/30 on both. The silent default is the dangerous
    # outcome — a wrong answer rather than a failure — so a test that catches
    # its return is worth more than one asserting which way the failure comes.
    # (Shape and the disjunction both from Fable's review of #164.)
    #
    # Three traps for anyone who tries again, each of which caught someone
    # during #164:
    #
    # 1. The pending error is tripped by whatever checked C call comes next.
    #    Put anything between the surviving unwrap and the sentinel and the
    #    probe dies THERE; a harness looking for a marker then scores the
    #    death as a clean run. That is how the trap was first reported as
    #    intermittent when it was firing every time.
    # 2. Measure the artifact, not a tidier rebuild of it. A simplified
    #    one-launch probe came back 60/60 clean while the real three-launch
    #    pin failed 2 of 30, which nearly got a real observation dismissed as
    #    noise.
    # 3. Measure on the FLOOR interpreter. Every determinism figure here —
    #    200/200, 30/30, 42/42 — was taken on 3.12 and said nothing about the
    #    job that actually failed.
    #
    # The four invariants this file DOES pin are MEASURED on both, not merely
    # green in a job: 50/50 on 3.12, and on 3.11 the flip pin passed 40/40
    # plus 10/10, the fresh unwrap returned a default 30/30, and the
    # value-optional and segfault pins passed every 3.11 run of this file.
    #
    # One footnote that is an observation, not a defect. A BARE `M g` probe —
    # no `unwrap()` helper, no `is_initialized` assert — returned a silent
    # default on 3.11 in 9 of 95 runs, clustered in two of four batches, while
    # the shape actually used here never did in 80. The shape dependence is
    # unexplained, so do not restructure these probes without re-measuring on
    # 3.11.

    _RESIDUE_PROBE = (
        "import openstudio\n"
        "def unwrap():\n"
        "    x = openstudio.model.Model.load("
        "openstudio.path('/nonexistent.osm'))\n"
        "    assert not x.is_initialized()\n"
        "    return x.get()\n"
        "outcome = None\n"
        "try:\n"
        "    m1 = unwrap()\n"
        "%s"
        "    m2 = unwrap()\n"
        "    try:\n"
        "        [].append(0)\n"
        "        outcome = 'CLEAN'\n"
        "    except SystemError:\n"
        "        outcome = 'POISONED'\n"
        "except SystemError:\n"
        "    outcome = 'RAISED_AT_UNWRAP'\n"
        "print('OUTCOME', outcome, flush=True)\n"
    )

    def _residue_outcome(self, *, construct_between):
        """One subprocess launch, and the probe prints exactly one outcome.

        Every branch is classified INSIDE the probe, so the parent never has
        to read a missing marker: a probe that dies has broken, and the
        returncode assertion says so. Printing anything before the sentinel
        would make `print` the poisoned call instead.
        """
        try:
            import openstudio  # noqa: F401
        except ImportError:
            self.skipTest("needs the openstudio wheel")

        import subprocess
        import sys
        out = subprocess.run(
            [sys.executable, "-c", self._RESIDUE_PROBE % (
                "    openstudio.model.Model()\n" if construct_between else "")],
            capture_output=True, text=True, check=False, timeout=120)
        self.assertEqual(
            0, out.returncode,
            f"probe broke (rc={out.returncode}) instead of classifying its "
            f"own outcome. stderr: {out.stderr[-400:]}")
        marker = [line for line in out.stdout.splitlines()
                  if line.startswith("OUTCOME ")]
        self.assertEqual(1, len(marker),
                         f"expected one OUTCOME line, got {marker!r}")
        return marker[0].split(None, 1)[1]

    def test_unwraps_alone_leave_the_next_call_alone(self):
        """CONTROL, and it stays its own test — see the note above on launches."""
        self.assertEqual(
            "CLEAN", self._residue_outcome(construct_between=False),
            "two surviving unwraps with no Model() between them must leave "
            "the next checked call alone; without this the test below shows "
            "only that SOMETHING in the sequence misbehaves")

    def test_an_unwrap_after_a_Model_is_NEVER_a_silent_default(self):
        """The portable half of the trap: it fails, and which way is not fixed.

        On 3.12 the second unwrap survives and poisons the next checked C call;
        on 3.11 it raises at the unwrap. Both are failures. What must never
        happen is CLEAN — a silent default-constructed model handed back to a
        caller that asked for a file it could not read.

        Asserting the disjunction rather than either branch is deliberate: a
        pin on one outcome is red on the other interpreter, which is how this
        file came to turn the `python` job red once already.
        """
        outcome = self._residue_outcome(construct_between=True)
        self.assertIn(
            outcome, ("POISONED", "RAISED_AT_UNWRAP"),
            f"got {outcome!r}. CLEAN means an unwrap after a Model() silently "
            f"returned a default model — a wrong answer rather than a "
            f"failure, and the one outcome this sequence must never give")

    def test_the_checked_loader_names_the_path(self):
        from btap._sdk import load_model
        with self.assertRaises(ValueError) as ctx:
            load_model("/nonexistent/model.osm")
        self.assertIn("/nonexistent/model.osm", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
