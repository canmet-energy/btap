"""SDK-binding invariants, enforced mechanically rather than documented.

D-79 records that ``.get()`` on an unchecked SDK Optional is unsafe in the
Python bindings in a way it is not in Ruby. Measured on 3.11.0 (#164), the
behaviour splits by whether the wrapped type is default-constructible, and for
one group it also depends on what the PROCESS has already done:

- every ``openstudio.model.Optional*`` naming a MODEL OBJECT — 615 of that
  namespace's 617 — SEGFAULTS the interpreter, from a fresh process and after
  the type has been constructed alike. A crash takes the xdist worker with it
  and reports as a lost node, not as a failure. This is what a failed
  ``to_X()`` cast returns, and what ``.thermalZone()``, ``.construction()``
  and the other optional accessors return.
- ``OptionalModel``, ``OptionalScheduleType`` and the value optionals
  (``OptionalDouble``, ``OptionalString``, ``OptionalInt``) return a
  DEFAULT-CONSTRUCTED object the first time and raise ``SystemError`` from
  then on, per class and per process. Constructing a ``Model()`` is enough to
  flip ``OptionalModel``.

The silent-empty-model hazard is therefore the FIRST call's behaviour, not a
property of the type: ``Model.load(bad).get()`` yields an empty model in a
fresh interpreter and raises once anything has built a ``Model()``. That is
how the packaged catalog report emitted 97 "diagram unavailable" cards.

Issue #141 is the same fact seen from the other side. A probe in
``tests/modeling/test_catalog_report.py`` asserted the empty-model behaviour
IN-PROCESS, so it passed or failed according to whether a predecessor in its
xdist worker had constructed a ``Model()`` — which nearly every SDK test does.
It was NOT stale error-indicator residue, which is what this file and
``btap._compat.opt`` both claimed before #164: the raise clears the indicator
(CPython chains the ``RuntimeError`` as ``__cause__``), and ``PyErr_Occurred``
reads clear afterwards.

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
        """The fact that actually explains #141, pinned.

        `opt()` and this file both described the hazard as a stale C error
        indicator left by a raising `.get()` for a later call to trip over.
        That is not what happens — the raise clears the indicator. What
        happens is that the FIRST `.get()` on an empty default-constructible
        optional returns a default object and every later one raises, per
        class and per process. So `Model.load(bad)` unwrapped is silent in a
        fresh interpreter and raises once anything has built a `Model()`,
        which nearly every SDK test does.

        Two probes in ONE subprocess each, because the claim is about what a
        process has already done and in-process ordering is the whole point.
        The control matters as much as the subject: without it, a probe that
        raised for some unrelated reason would look like proof.
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
                      "CONTROL: in a fresh interpreter the empty optional must "
                      "still yield an empty model — if this changed, the "
                      "silent-flow hazard is gone and D-79 can be revisited")
        self.assertIn("RAISED RuntimeError", probe(construct_first=True),
                      "after a Model() has been constructed, the SAME call "
                      "must raise SystemError caused by RuntimeError. This is "
                      "the #141 mechanism; if it stops holding, the subprocess "
                      "isolation in this file is no longer needed")

    def test_the_checked_loader_names_the_path(self):
        from btap._sdk import load_model
        with self.assertRaises(ValueError) as ctx:
            load_model("/nonexistent/model.osm")
        self.assertIn("/nonexistent/model.osm", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
