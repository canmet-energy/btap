"""Standing dormancy gate for the NECB-I-Fan / ``exhaust_schedule`` shape.

``docs/necb_decisions.md``'s D-06 open item flags "wiring reference fan
schedules to archetype operating-schedule letters" as undecided: builders
default fan availability to Always On, and switching that would flip many
systems' ERV continuous-operation classification (Table 5.2.10.1.-B). The
packaged NECB snapshots (``python/btap/codes/necb/data/<code id>/tables/
space_types.json``'s ``exhaust_schedule`` field, ``.../tables/
schedules.json``'s ``NECB-I-Fan`` / ``NECB-I-FAN`` schedule rows) already
ship this data -- it travels with the table extraction regardless -- but no
product Python reads it. That is deliberate: the D-06 decision has not been
made, so nothing should be silently consuming a value nobody adjudicated.

This test makes that a fact CI checks, not a claim left in prose. It fails
the moment any product source under ``python/btap/`` starts referencing
``exhaust_schedule``, ``NECB-I-Fan`` or ``NECB-I-FAN`` as a live value --
at which point the D-06 wiring decision has actually been made, and this
test (plus its docstring, plus D-06 itself) should be updated together
rather than the gate being loosened to let the reference through unnoticed.

The forbidden tokens are allowed to appear in a DOCSTRING or a COMMENT --
prose that discusses the dormancy (this file's own docstring, review notes,
D-06's text) must not itself trip the gate. Comments never enter the AST at
all, so walking ``ast.Constant`` string nodes and identifier nodes, and
excluding only the nodes that ARE a docstring, draws exactly that line.
"""

from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Case-sensitive by design: `NECB-I-FAN` and `NECB-I-Fan` are both real
#: spellings seen in the packaged schedules tables (see
#: `tables/schedules.json`'s `name` field); `exhaust_schedule` is the
#: `space_types.json` key that would point a consumer at either one.
FORBIDDEN_TOKENS = ("exhaust_schedule", "NECB-I-Fan", "NECB-I-FAN")

#: Identifier-shaped node attributes worth checking for a bare reference
#: (import alias, attribute access, keyword argument, function/variable
#: name). `NECB-I-Fan` / `NECB-I-FAN` can never appear here -- a hyphen is
#: not a legal identifier character -- so only `exhaust_schedule` could ever
#: show up this way; checked anyway so a future rename to a legal-identifier
#: forbidden token stays covered without touching this test.
_IDENTIFIER_ATTRS = ("id", "attr", "arg", "name", "asname")


def _tracked_python_files() -> list[str]:
    """Every ``python/btap/**/*.py`` file git tracks, via ``git ls-files``
    rather than a filesystem walk -- consistent with
    ``test_no_legacy_namespace.py``'s reasoning: untracked build output
    (``packaging/windows/stage/``, ``__pycache__``) must never feed a gate
    like this one."""
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "python/btap"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line.endswith(".py")]


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """``id()`` of every ``Constant`` node that IS a docstring: the first
    statement of a module/class/function body, expressed as a bare string
    expression. These are exempt from the token check."""
    ids: set[int] = set()
    docstring_owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, docstring_owners):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def _offenders_in_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    docstring_ids = _docstring_node_ids(tree)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_ids:
                continue
            for token in FORBIDDEN_TOKENS:
                if token in node.value:
                    offenders.append(
                        f"{path}:{node.lineno}: string literal {node.value!r} "
                        f"names {token!r}"
                    )
            continue
        for attr in _IDENTIFIER_ATTRS:
            value = getattr(node, attr, None)
            if isinstance(value, str) and value in FORBIDDEN_TOKENS:
                offenders.append(
                    f"{path}:{getattr(node, 'lineno', '?')}: identifier "
                    f"{attr}={value!r}"
                )
    return offenders


class TestScheduleIDormant(unittest.TestCase):
    """The wiring of NECB-I-Fan / exhaust_schedule is a separate, not-yet-made
    decision (D-06's open item). Product Python must not consume it."""

    def test_no_product_python_consumes_exhaust_schedule_or_necb_i_fan(self):
        offenders: list[str] = []
        scanned = 0
        for relative in _tracked_python_files():
            path = REPO_ROOT / relative
            if not path.is_file():
                continue
            offenders.extend(_offenders_in_file(path))
            scanned += 1

        self.assertGreater(
            scanned, 50,
            f"only {scanned} python/btap/**/*.py files scanned -- the "
            "git ls-files walk went stale, and a stale gate proves nothing",
        )
        self.assertEqual(
            [], offenders,
            "python/btap product source must not reference exhaust_schedule / "
            "NECB-I-Fan / NECB-I-FAN as a consumer -- wiring reference fan "
            "schedules to archetype operating-schedule letters is D-06's open "
            "item, not yet decided (docs/necb_decisions.md):\n  "
            + "\n  ".join(offenders),
        )
