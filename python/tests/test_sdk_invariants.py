"""SDK-binding invariants, enforced mechanically rather than documented.

D-79 records that ``.get()`` on an unchecked SDK Optional is unsafe in the
Python bindings in a way it is not in Ruby:

- ``OptionalModel.get()`` on an EMPTY optional RETURNS AN EMPTY MODEL rather
  than raising, so an unreadable path flows onward as a model with no spaces
  and no zones and fails much later, misleadingly. This is exactly how the
  packaged catalog report came to emit 97 "diagram unavailable" cards from a
  wheel instead of one clear error.
- ``OptionalDouble``/``OptionalString.get()`` raise ``SystemError`` AND leave
  the C-level error indicator set, which can segfault the interpreter on a
  later, unrelated call.

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
        try:
            import openstudio
        except ImportError:
            self.skipTest("needs the openstudio wheel")

        empty = openstudio.model.Model.load(openstudio.path("/nonexistent.osm"))
        self.assertFalse(empty.is_initialized())
        model = empty.get()  # does NOT raise — that is the hazard
        self.assertEqual(0, len(model.getSpaces()),
                         "empty optional yielded a populated model — invariant changed")

    def test_the_checked_loader_names_the_path(self):
        from btap._sdk import load_model
        with self.assertRaises(ValueError) as ctx:
            load_model("/nonexistent/model.osm")
        self.assertIn("/nonexistent/model.osm", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
