"""SDK-binding invariants, enforced mechanically rather than documented.

D-79 records that ``.get()`` on an unchecked SDK Optional is unsafe in the
Python bindings in a way it is not in Ruby:

- ``OptionalModel.get()`` on an EMPTY optional RETURNS AN EMPTY MODEL rather
  than raising, so an unreadable path flows onward as a model with no spaces
  and no zones and fails much later, misleadingly. This is exactly how the
  packaged catalog report came to emit 97 "diagram unavailable" cards from a
  wheel instead of one clear error.
- ``OptionalDouble``/``OptionalString``/``OptionalInt.get()`` raise
  ``SystemError`` AND leave the C-level error indicator set, which surfaces on
  a later, unrelated call as a spurious ``SystemError`` THERE. Issue #141 was
  one of those: a probe in ``tests/modeling/test_catalog_report.py`` kept
  failing under some xdist worker layouts because a predecessor in its worker
  had left the indicator set.
- every OTHER ``openstudio.model.Optional*.get()`` SEGFAULTS the interpreter
  on the spot — 615 of the namespace's 617 on 3.11.0, swept one subprocess per
  type. This is what a failed ``to_X()`` cast returns, and it is strictly
  worse than the ``SystemError`` family: there is no later call to surface it.
  ``OptionalModel`` and ``OptionalScheduleType`` are the only two survivors,
  so the benign first bullet is the exception rather than the rule.

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
                             capture_output=True, text=True, check=False)
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
        # failing under some xdist layouts: a PRIOR test in the same worker
        # left the C error indicator set, and this `.get()` then surfaced that
        # residue as `SystemError: OptionalModel_get returned a result with an
        # exception set` rather than its own result. The test was vulnerable to
        # the very trap it documented. Here the subprocess has no predecessor,
        # so the probe observes its own call.
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
        out = subprocess.run([sys.executable, "-I", "-c", probe],
                             capture_output=True, text=True, check=False)
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
        self.assertLess(out.returncode, 0,
                        "expected death by signal (negative returncode); got "
                        f"{out.returncode}. stdout: {out.stdout[:200]}")

    def test_the_checked_loader_names_the_path(self):
        from btap._sdk import load_model
        with self.assertRaises(ValueError) as ctx:
            load_model("/nonexistent/model.osm")
        self.assertIn("/nonexistent/model.osm", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
