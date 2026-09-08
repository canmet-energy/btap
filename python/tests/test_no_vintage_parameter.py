"""Stage 7's gate (R-C, D-XX pending): no function or lambda parameter named
``vintage``, no call passing ``vintage=``, and no ``def`` whose name contains
``vintage`` survives in tracked Python under ``python/``.

Written on the pre-migration tree, deliberately: Stage 6 left ``vintage`` as
the public parameter name on 97 domain functions (277 call sites in tests and
scripts) plus five functions outside the NECB package that use it as an edition
selector (see ``docs/NECB_MULTI_EDITION_PLAN.md``, "Stage 7 — the public
API"). This gate is expected to FAIL with the full inventory until that
migration lands and every site is renamed to ``code=`` (or ``edition=`` for
the five costing/sample selectors) — at which point it passes and stands as
the standing gate against regression, the same way
``test_no_legacy_namespace.py`` stands for the ``the NECB package`` rename.

The walk is over ``git ls-files``, never the working tree, for the same
reason ``test_no_legacy_namespace.py`` gives: untracked build output (e.g.
``packaging/windows/stage/``) is not source.

The word ``vintage`` may survive in string literals, comments and
docstrings — the AST walk naturally does not look at those. Only real
parameters, real call keywords and real def names are flagged.

Every allowlist entry is documented by name with its reason. Do not add an
entry here to make a new hit pass; migrate the site instead.
"""

from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Files excluded from the walk, each with why it is legitimately exempt.
#: ``python/tests/data/coverage_code_ref_mapping*.json`` need no entry here:
#: they are not ``.py`` and the walk only ever considers tracked ``.py``
#: files, so the glob itself excludes them.
ALLOWLIST: dict[str, str] = {
    "python/tests/test_no_vintage_parameter.py":
        "this gate names the parameter and the call keyword it forbids, "
        "and its own docstring narrates the migration by name.",
}


def tracked_py_files() -> list[str]:
    """Tracked ``.py`` files under ``python/``, via ``git ls-files`` only.

    ``git ls-files python/ -- '*.py'`` is two OR'd pathspecs in this git
    (it matches the ``python/`` prefix pathspec as well as the bare
    ``*.py`` glob pathspec), which pulls in every non-Python file under
    ``python/`` too. Listing ``python/`` and filtering the ``.py`` suffix
    in Python gives the intended set — verified identical to
    ``git ls-files -- 'python/*.py'`` — without relying on that pathspec
    interaction.
    """
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "python/"],
        capture_output=True, text=True, check=True,
    ).stdout
    return sorted(line for line in out.splitlines() if line.endswith(".py"))


def _all_params(args: ast.arguments) -> list[ast.arg]:
    params = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    if args.vararg is not None:
        params.append(args.vararg)
    if args.kwarg is not None:
        params.append(args.kwarg)
    return params


def _callee_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return "<call>"


def _scan(relative: str, text: str) -> list[str]:
    """Return ``"path:line: context"`` hits for one file's source text."""
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError:
        # Not a parseable Python file (should not happen for tracked .py
        # files); nothing to scan rather than a spurious gate failure.
        return []

    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for param in _all_params(node.args):
                if param.arg == "vintage":
                    where = ("lambda" if isinstance(node, ast.Lambda)
                              else f"def {node.name}")
                    hits.append((param.lineno,
                                 f"parameter 'vintage' on {where}"))
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and "vintage" in node.name):
                hits.append((node.lineno,
                             f"def name contains 'vintage': {node.name}"))
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "vintage":
                    lineno = getattr(kw, "lineno", node.lineno)
                    hits.append(
                        (lineno,
                         f"call keyword vintage= on {_callee_name(node.func)}"))

    hits.sort()
    return [f"{relative}:{line}: {context}" for line, context in hits]


def vintage_parameter_hits() -> list[str]:
    """``"path:line: context"`` for every ``vintage`` parameter, keyword
    call argument, or ``vintage``-containing def name in tracked
    ``python/**/*.py`` source, minus the allowlist. Importable so both
    tests here — and any future caller — share one scan."""
    offenders: list[str] = []
    for relative in tracked_py_files():
        if relative in ALLOWLIST:
            continue
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            continue
        offenders.extend(_scan(relative, text))
    return offenders


class TestNoVintageParameter(unittest.TestCase):

    def test_no_tracked_source_has_a_vintage_parameter_or_call(self):
        hits = vintage_parameter_hits()
        self.assertEqual(
            [], hits,
            f"{len(hits)} tracked source location(s) still use 'vintage' as "
            "a parameter, a call keyword, or in a def name (Stage 7, "
            "docs/NECB_MULTI_EDITION_PLAN.md); rename to 'code=' (or "
            "'edition=' for the five edition-selector sites) rather than "
            "allowlisting:\n  " + "\n  ".join(hits))

    def test_allowlist_entries_all_exist(self):
        for relative, reason in ALLOWLIST.items():
            path = REPO_ROOT / relative
            self.assertTrue(path.is_file(),
                             f"allowlisted {relative} no longer exists — "
                             "drop its entry")
            self.assertTrue(reason, relative)


class TestCliHasNoVintageFlag(unittest.TestCase):
    """The CLI's own surface: ``--vintage`` replaced by ``--code`` (Stage 7).
    Independent of the AST walk above because argparse flag names
    (``--vintage``) are string literals, not parameters or call keywords,
    and the AST gate is not meant to chase strings."""

    def test_parser_has_code_not_vintage(self):
        from btap.codes.cli import build_parser

        parser = build_parser()
        options = parser._option_string_actions  # argparse's own index

        self.assertNotIn(
            "--vintage", options,
            "the CLI parser still exposes --vintage; Stage 7 replaces it "
            "with --code")
        self.assertIn(
            "--code", options,
            "the CLI parser has no --code option; Stage 7 adds it in place "
            "of --vintage")


if __name__ == "__main__":
    unittest.main()
