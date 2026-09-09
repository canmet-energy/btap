"""R-B's standing gate (D-86): no ACTIVE reference to the pre-rename
``btap.necb`` / ``btap/necb`` namespace survives in tracked sources.

The needles are deliberately `btap.necb` and `btap/necb` only. The retired
GEM name `btap-necb` is period prose in ~100 docstrings the rename must not
reword, and it is also the stem of the live `btap-necb-coverage` console
entry point — matching it would make this gate demand edits that are wrong.

The walk is over ``git ls-files``, never the working tree:
``packaging/windows/stage/`` holds untracked build output full of legacy
strings, and a filesystem walk would trip on it in any checkout that has
staged an installer.

Every exception is allowlisted BY NAME with its reason. The historical
records are never rewritten — a dated review that described the tree as it
stood is evidence, and editing it to name today's paths would be falsifying
it. Do not add an entry here to make a new reference pass; move the
reference instead.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Tracked paths the gate walks. Anything outside them (docs prose, the
#: frozen scenario baselines) is R-B evidence or narrative, not an active
#: reference.
SCANNED_PREFIXES = (
    "python/btap/",
    "python/tests/",
    "python/scripts/",
    "packaging/",
    ".github/",
)
SCANNED_EXACT = (
    "python/pyproject.toml",
    "CLAUDE.md",
    "README.md",
    ".gitignore",
)
#: verification/ is scanned for its Python only — the Ruby oracle probes and
#: the frozen baselines are evidence, not product source.
SCANNED_SUFFIXES_UNDER = (("verification/", ".py"),)

ALLOWLIST: dict[str, str] = {
    "python/tests/data/coverage_code_ref_mapping.json":
        "R6 ledger: its `new` column IS python/btap/necb/... and is frozen "
        "as the historical endpoint the R7 ledger chains from.",
    "python/tests/data/coverage_code_ref_mapping_r7.json":
        "R7 ledger: its `old` column necessarily names python/btap/necb/...; "
        "test_coverage_code_refs.py validates both ledgers structurally.",
    "python/btap/codes/data/decisions.json":
        "the decision registry: D-82's dated summary describes the tree as it "
        "stood in 2026-08, and D-86 must name the namespace it retired. "
        "Adjudicated wording is a record, not a reference.",
    "python/tests/test_coverage_code_refs.py":
        "the chain test asserts that no live pointer names the old namespace, "
        "which means writing it out.",
    "python/tests/test_no_legacy_namespace.py":
        "this gate names the namespace it forbids.",
}

NEEDLES = ("btap.necb", "btap/necb")


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout
    return out.splitlines()


def scanned(relative: str) -> bool:
    if relative in ALLOWLIST:
        return False
    if relative in SCANNED_EXACT or relative.startswith(SCANNED_PREFIXES):
        return True
    return any(relative.startswith(prefix) and relative.endswith(suffix)
               for prefix, suffix in SCANNED_SUFFIXES_UNDER)


class TestNoLegacyNamespace(unittest.TestCase):

    def test_no_tracked_source_names_the_legacy_namespace(self):
        offenders = []
        scanned_count = 0
        for relative in tracked_files():
            if not scanned(relative):
                continue
            path = REPO_ROOT / relative
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, ValueError):
                continue
            scanned_count += 1
            for number, line in enumerate(text.splitlines(), start=1):
                if any(needle in line for needle in NEEDLES):
                    offenders.append(f"{relative}:{number}: {line.strip()}")

        self.assertGreater(
            scanned_count, 300,
            f"only {scanned_count} tracked files scanned — the prefix list "
            "went stale, and a stale gate proves nothing")
        self.assertEqual(
            [], offenders,
            "btap.necb / btap/necb is gone (D-86); these tracked sources "
            "still name it:\n  " + "\n  ".join(offenders))

    def test_allowlist_entries_all_exist_and_still_need_the_exception(self):
        for relative, reason in ALLOWLIST.items():
            path = REPO_ROOT / relative
            self.assertTrue(path.is_file(),
                            f"allowlisted {relative} no longer exists — "
                            "drop its entry")
            self.assertTrue(reason, relative)
            text = path.read_text(encoding="utf-8")
            self.assertTrue(
                any(needle in text for needle in NEEDLES),
                f"{relative} no longer names the legacy namespace — remove "
                "its allowlist entry rather than leaving a dead exception")

    def test_the_renamed_package_is_the_one_on_disk(self):
        package = REPO_ROOT / "python" / "btap" / "codes"
        self.assertTrue((package / "__init__.py").is_file())
        # Tracked files, not the filesystem: a branch switch leaves the old
        # package's __pycache__ behind, and that is not a legacy package.
        legacy = subprocess.run(["git", "ls-files", "python/btap/necb"],
                                cwd=REPO_ROOT, capture_output=True,
                                text=True, check=True).stdout.split()
        self.assertEqual([], legacy)
        for domain in ("envelope", "hvac", "lighting", "loads", "shw"):
            self.assertTrue((package / "necb" / domain).is_dir(), domain)
        editions = package / "necb" / "editions"
        self.assertTrue((editions / "necb2025" / "eui_archetypes.py").is_file())
        self.assertTrue((editions / "necb2025" / "part11_ghg.py").is_file())
        self.assertTrue((package / "data" / "decisions.json").is_file())
        self.assertTrue((package / "necb" / "tiers.py").is_file())


if __name__ == "__main__":
    unittest.main()
