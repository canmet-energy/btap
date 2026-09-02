"""Self-containment invariant scanner (D-80 R2.1).

The invariant, in full:

    the installed package and Python-owned unit/fixture tests are
    self-contained; explicitly retirement-tagged cross-language and oracle
    tests may consume verification/, legacy_pin/, and (until R6) gem trees.

This is the mechanical half of that sentence. It walks every ``.py`` file git
knows about (tracked, plus untracked-and-not-ignored) under python/btap,
python/tests and python/scripts, finds
cross-tree reference expressions in CODE (string literals and ``Path`` ``/``
chains — comments and docstrings are prose and do not count), and demands that
each one be named in ALLOWLIST together with the D-80 phase at which it
retires. The point is not to forbid the dependencies that exist today; it is to
make every one of them a deliberate, dated entry rather than a habit — so no
NEW reach into the gem trees lands unnoticed while the port is being made
standalone.

The gate is hard in both directions: an unlisted hit fails, and a listed entry
that no longer matches anything fails too (a stale entry is how an allowlist
quietly becomes a blanket exemption).
"""

from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Trees scanned (repo-relative, as git spells them).
SCAN_ROOTS = ("python/btap", "python/tests", "python/scripts")

#: What counts as a cross-tree reference. Gem directories, the pinned Ruby
#: oracle, the shared verification harness, and the Ruby installer payload.
PATTERNS = (
    "btap-modeling",
    "btap-necb",
    "btap-costing",
    "btap-audit",
    "btap-simulation",
    "legacy_pin",
    "verification/",
    "packaging/windows",
)

#: Every permitted cross-tree reference, keyed by repo-relative path.
#:
#: ``refs``    — the substrings this file is allowed to mention.
#: ``retires`` — the D-80 phase that removes the dependency:
#:   ``R6``              the gems retire; the reference goes with them.
#:   ``R1-adjudicated``  consumption of verification/ by a cross-language or
#:                       oracle test — permitted permanently by the invariant.
#:   ``N/A-label``       the gem NAME as human-readable text (a report footer),
#:                       not a path into another tree. Nothing to retire.
#:   ``N/A-scanner``     this file, which must spell the patterns out.
#:   ``R4-dormant``      a live Leg-B gate made DORMANT by the R4 handoff
#:                       (D-82): the file and its refs stay on disk behind
#:                       BTAP_LEGB=1 until R6 deletes them.
#:   ``R2.2-pending``    owned by a sibling D-80 task, not by R2.1.
#:   ``TODO-review``     a real dependency with no retirement rationale yet.
ALLOWLIST = {
    # --- installed package -------------------------------------------------
    "python/btap/modeling/geometry/plan.py": {
        "refs": ["btap-modeling"],
        "retires": "N/A-label",
        "why": "the rendered plan-view footer credits the component by name",
    },
    "python/btap/necb/report/sections.py": {
        "refs": ["btap-necb"],
        "retires": "N/A-label",
        "why": "the compliance report's footer credits the btap family by name",
    },
    "python/btap/necb/coverage.py": {
        "refs": ["btap-necb"],
        "retires": "N/A-label",
        "why": ("btap-necb-coverage is the installed console-script name, not "
                "a reference to the retiring btap-necb directory"),
    },
    "python/scripts/wheel_smoke.py": {
        "refs": ["btap-necb"],
        "retires": "N/A-label",
        "why": ("btap-necb-coverage is the installed console-script name, not "
                "a reference to the retiring btap-necb directory"),
    },
    "python/scripts/legacy_whatsnew.py": {
        "refs": ["legacy_pin"],
        "retires": "R6-oracle-boundary",
        "why": "reports fork movement relative to the permanent oracle pin",
    },
    "python/scripts/necb_archetype_sweep.py": {
        "refs": ["legacy_pin", "verification/"],
        "retires": "R6-oracle-boundary",
        "why": ("the surviving sweep asks the pinned oracle generator under "
                "verification/ to produce proposed archetypes"),
    },
    # --- developer scripts -------------------------------------------------
    "python/scripts/oracle_prep.py": {
        "refs": ["verification/"],
        "retires": "R1-adjudicated",
        "why": ("builds the Leg-C oracle request manifest under "
                "verification/oracle — the shared harness, not a gem tree"),
    },
    # --- cross-language (Leg B) and oracle (Leg C) tests --------------------
    "python/tests/support.py": {
        "refs": ["verification/"],
        "retires": "R1-adjudicated",
        "why": "oracle_goldens_dir() resolves the committed Leg-C goldens",
    },
    "python/tests/necb/test_legacy_archetype_e2e.py": {
        "refs": ["legacy_pin", "verification/"],
        "retires": "R6-oracle-boundary",
        "why": ("the surviving whole-building gate consumes the pinned oracle "
                "generator, not the retiring product gems"),
    },
    "python/tests/necb/test_oracle_goldens_current.py": {
        "refs": ["legacy_pin", "verification/"],
        "retires": "R6-oracle-boundary",
        "why": ("the surviving currency gate ties committed Leg-C goldens to "
                "the permanent oracle pin and request manifest"),
    },
    "python/tests/test_inventory_validation.py": {
        "refs": ["verification/"],
        "retires": "R1-adjudicated",
        "why": ("negative tests for the permanent D-80 inventory validator in "
                "verification/oracle — verification/ consumption is permitted "
                "by the invariant"),
    },
    "python/tests/necb/test_frozen_scenarios.py": {
        "refs": ["verification/"],
        "retires": "R1-adjudicated",
        "why": ("the R4 frozen-scenario gate — Leg B's successor — runs the "
                "manifest under verification/scenarios/; verification/ "
                "consumption is permitted by the invariant permanently"),
    },
    "python/tests/necb/test_freeze_seal_transition.py": {
        "refs": ["verification/"],
        "retires": "R6-oracle-boundary",
        "why": ("negative-controls the post-handoff seal schema in the "
                "permanent scenario freezer"),
    },
    "python/tests/test_request_manifest.py": {
        "refs": ["verification/"],
        "retires": "R1-adjudicated",
        "why": ("proves the D-80 request manifest under verification/oracle is "
                "internally live (no orphaned golden groups)"),
    },
    "python/tests/test_verification_disposition.py": {
        "refs": ["verification/"],
        "retires": "R6-oracle-boundary",
        "why": "enforces the permanent file-by-file verification disposition record",
    },
    # --- this gate ---------------------------------------------------------
    "python/tests/test_self_containment.py": {
        "refs": list(PATTERNS),
        "retires": "N/A-scanner",
        "why": "the scanner has to spell out the patterns it looks for",
    },
}


def tracked_python_files():
    """.py files under the scanned roots, as git sees them: everything
    TRACKED, plus anything untracked that is not ignored.

    Asking git is what keeps .venv, build/, *.egg-info and __pycache__ out
    without a hand-maintained ignore list (``--exclude-standard`` applies
    .gitignore). Untracked-but-not-ignored files are included deliberately:
    the invariant has to hold on the WORKING TREE, or a new cross-tree
    dependency would be invisible to this gate until the commit that ships
    it.
    """
    out = subprocess.run(["git", "ls-files", "--cached", "--others",
                          "--exclude-standard", "--", *SCAN_ROOTS],
                         cwd=REPO_ROOT, capture_output=True, text=True,
                         check=True)
    return sorted({line for line in out.stdout.splitlines()
                   if line.endswith(".py")})


def _docstring_nodes(tree):
    """ids of the string Constants that are DOCSTRINGS — prose, not code."""
    ids = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            ids.add(id(body[0].value))
    return ids


def _joined_path(node):
    """The literal segments of a ``a / "b" / "c"`` chain, joined with '/'.

    Without this a path assembled segment by segment — ``root / "packaging" /
    "windows"`` — hides from a plain substring scan, which is exactly how the
    interesting references are written.
    """
    def segments(inner):
        if isinstance(inner, ast.BinOp) and isinstance(inner.op, ast.Div):
            return segments(inner.left) + segments(inner.right)
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            return [inner.value]
        return []

    parts = segments(node)
    return "/".join(parts) if len(parts) > 1 else None


def scan_file(relative):
    """[(line, pattern)] for one file. Comments never reach ast; docstrings
    are dropped explicitly. Everything else is code."""
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative)
    docstrings = _docstring_nodes(tree)

    hits = set()
    for node in ast.walk(tree):
        texts = []
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            texts.append(node.value)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            joined = _joined_path(node)
            if joined:
                texts.append(joined)
        for text in texts:
            for pattern in PATTERNS:
                if pattern in text:
                    hits.add((node.lineno, pattern))
    return sorted(hits)


class TestSelfContainment(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.hits = {}
        for relative in tracked_python_files():
            found = scan_file(relative)
            if found:
                cls.hits[relative] = found

    def test_scan_is_not_vacuous(self):
        """A scanner that finds no files is a green-but-vacuous gate."""
        self.assertGreater(len(tracked_python_files()), 100,
                           "git ls-files returned almost nothing — is this "
                           "running outside the repository?")

    def test_no_unallowlisted_cross_tree_references(self):
        violations = []
        for relative, found in sorted(self.hits.items()):
            allowed = set(ALLOWLIST.get(relative, {}).get("refs", []))
            for line, pattern in found:
                if pattern not in allowed:
                    violations.append(
                        f"  {relative}:{line} references '{pattern}'")
        self.assertEqual(
            [], violations,
            "cross-tree reference(s) outside the self-containment "
            "allowlist:\n" + "\n".join(violations) + "\n\n"
            "The invariant: the installed package and Python-owned "
            "unit/fixture tests are self-contained; explicitly "
            "retirement-tagged cross-language and oracle tests may consume "
            "verification/, legacy_pin/, and (until R6) gem trees.\n"
            "Fix it EITHER by removing the dependency (own the data on the "
            "Python side — see tests/fixtures and tests/test_fixture_drift.py) "
            "OR by adding an ALLOWLIST entry in "
            "python/tests/test_self_containment.py whose 'retires' names the "
            "D-80 phase that deletes it.")

    def test_no_stale_allowlist_entries(self):
        stale = []
        for relative, entry in sorted(ALLOWLIST.items()):
            found = self.hits.get(relative, [])
            if not found:
                stale.append(f"  {relative}: entry matches NOTHING — the file "
                             "no longer has cross-tree references (or is no "
                             "longer tracked); delete the entry")
                continue
            patterns = {pattern for _, pattern in found}
            for ref in entry["refs"]:
                if ref not in patterns:
                    stale.append(f"  {relative}: '{ref}' is no longer "
                                 "referenced; drop it from 'refs'")
        self.assertEqual(
            [], stale,
            "stale self-containment allowlist entries — an exemption that "
            "matches nothing is how an allowlist turns into a blanket "
            "waiver:\n" + "\n".join(stale))

    def test_every_allowlist_entry_names_a_retirement_phase(self):
        for relative, entry in sorted(ALLOWLIST.items()):
            self.assertTrue(str(entry.get("retires", "")).strip(),
                            f"{relative}: allowlist entry must name the D-80 "
                            "phase at which the dependency retires")
            self.assertTrue(str(entry.get("why", "")).strip(),
                            f"{relative}: allowlist entry must say WHY the "
                            "dependency is legitimate")


if __name__ == "__main__":
    unittest.main()
