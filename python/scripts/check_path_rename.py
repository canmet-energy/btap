#!/usr/bin/env python3
"""Prove a diff is the src-layout move and nothing else (#229, Route B step 1).

The move touches thousands of lines — the frozen baselines alone carry ~11,800
`python/btap/...` code pointers — and a diff that size cannot be READ. A path
rename and a behaviour change look alike in it, so the project's re-freeze
discipline ("attribute every changed baseline") could not be honoured by eye.

This script turns the review into a property. For every file the diff touches:

  renamed   the new path must be ``map_path(old)``, and the new content must
            equal ``map_text(old content)``;
  modified  the new content must equal ``map_text(old content)``;
  deleted   only the paths in ``DELETED`` (each with its reason);
  added     only the paths in ``ADDED``.

A second property covers what the diff cannot show: a file the move never
touched is not IN the diff, so a pointer left on the old path would pass the
first check. So at HEAD no tracked text file may still contain a path the
mapping would move, except the files in ``KEEP_OLD_PATHS``.

Anything else fails — UNLESS the path is in a ``--hand-edited`` list. Those are
the files the move genuinely has to change by hand (config, the workflows,
``Path(__file__).parents[N]`` depths). They are printed with their diff size so
a reviewer reads exactly them and nothing else, and the list is the review.

The text mapping is anchored: ``python/`` followed by ``btap``, ``tests`` or
``scripts`` as a whole path segment, and only where it is not the tail of a
longer name. It must NOT touch ``packaging/windows``'s ``python/python.exe`` or
``python/Lib/site-packages/...`` — that ``python/`` is the EMBEDDED interpreter
inside the Windows installer, not this repository's directory.

Usage, from the repository root:

    python3 scripts/check_path_rename.py BASE [HEAD] [--hand-edited FILE ...]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

#: Directory moves, in the order they are applied. `python/README.md` is the
#: distribution's long_description and moves beside the source it describes.
PATH_MAP: tuple[tuple[str, str], ...] = (
    ("python/btap/", "src/btap/"),
    ("python/tests/", "tests/"),
    ("python/scripts/", "scripts/"),
    ("python/README.md", "src/README.md"),
)

#: The same moves as TEXT, anchored. The lookbehind refuses a longer name
#: (`cpython/btap`, `my-python/tests`); the trailing group requires a segment
#: boundary, so `python/btapx` or `python/tests_old` are left alone.
_TEXT_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])python/(btap|tests|scripts|README\.md)(?![A-Za-z0-9_-])",
    re.MULTILINE)
_TEXT_TO = {"btap": "src/btap", "tests": "tests", "scripts": "scripts",
            "README.md": "src/README.md"}

#: Deletions the move is allowed to make, each with its reason.
DELETED = {
    "python/LICENSE": "byte-identical to the root LICENSE; one copy is enough",
}

#: Additions the move is allowed to make (none: a move adds nothing).
ADDED: dict[str, str] = {}

#: Files at HEAD that must keep spelling the OLD paths, each with its reason.
KEEP_OLD_PATHS = {
    "scripts/check_path_rename.py": "the checker defines the mapping",
    "tests/test_check_path_rename.py": "its tests feed the old paths in",
}


def map_path(path: str) -> str:
    for old, new in PATH_MAP:
        if path == old or path.startswith(old):
            return new + path[len(old):]
    return path


def map_text(text: str) -> str:
    return _TEXT_RE.sub(lambda m: _TEXT_TO[m.group(1)], text)


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def _blob(ref: str, path: str) -> bytes:
    return _git("show", f"{ref}:{path}")


def _same_after_mapping(old: bytes, new: bytes) -> bool:
    try:
        return map_text(old.decode("utf-8")).encode("utf-8") == new
    except UnicodeDecodeError:
        return old == new  # binary: a move must not change a single byte


def changes(base: str, head: str) -> list[tuple[str, str, str]]:
    """(status, old path, new path) for every change between BASE and HEAD.

    Renames are detected at 50% similarity, which every pure move clears
    easily; a file rewritten past that shows up as delete + add and fails.
    """
    raw = _git("diff", "-z", "--name-status", "--find-renames=50%", base, head)
    fields = raw.decode("utf-8").split("\0")
    out, i = [], 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status[0] in "RC":
            out.append((status[0], fields[i + 1], fields[i + 2]))
            i += 3
        else:
            out.append((status[0], fields[i + 1], fields[i + 1]))
            i += 2
    # Git pairs a rename by similarity, and a SMALL file whose one line is a
    # path pointer falls under any threshold once that line changes — it comes
    # back as a delete plus an add. The mapping already says where each file
    # goes, so pair those by it rather than by git's guess.
    added = {new for s, _, new in out if s == "A"}
    paired = {old for s, old, _ in out if s == "D" and map_path(old) in added}
    targets = {map_path(old) for old in paired}
    out = [c for c in out
           if not (c[0] == "D" and c[1] in paired) and not (c[0] == "A" and c[2] in targets)]
    out.extend(("R", old, map_path(old)) for old in sorted(paired))
    return out


def leftovers(head: str) -> list[str]:
    """Tracked text files at HEAD that still name a path the move relocates."""
    coarse = subprocess.run(
        ["git", "grep", "-l", "-I", "-E", r"python/(btap|tests|scripts|README\.md)", head],
        capture_output=True)
    if coarse.returncode not in (0, 1):
        raise RuntimeError(coarse.stderr.decode())
    out = []
    for line in coarse.stdout.decode("utf-8").splitlines():
        path = line.split(":", 1)[1]
        if path in KEEP_OLD_PATHS:
            continue
        text = _blob(head, path).decode("utf-8", errors="replace")
        hits = len(_TEXT_RE.findall(text))
        if hits:
            out.append(f"{path}: still names the old layout {hits} time(s)")
    return out


def check(base: str, head: str, hand_edited: set[str]) -> tuple[list[str], dict[str, int]]:
    problems: list[str] = []
    counts = {"renamed": 0, "modified": 0, "hand-edited": 0, "deleted": 0}
    seen_hand: set[str] = set()
    for status, old, new in changes(base, head):
        if new in hand_edited:
            seen_hand.add(new)
            counts["hand-edited"] += 1
            if status == "R" and map_path(old) != new:
                problems.append(f"{old} -> {new}: hand-edited, but the PATH is "
                                f"not the mapped one ({map_path(old)})")
            continue
        if status == "R":
            counts["renamed"] += 1
            if map_path(old) != new:
                problems.append(f"{old} -> {new}: expected {map_path(old)}")
            elif not _same_after_mapping(_blob(base, old), _blob(head, new)):
                problems.append(f"{old} -> {new}: content is not a path-only change")
        elif status == "M":
            counts["modified"] += 1
            if map_path(old) != old:
                problems.append(f"{old}: modified in place, but it should have MOVED "
                                f"to {map_path(old)}")
            elif not _same_after_mapping(_blob(base, old), _blob(head, new)):
                problems.append(f"{old}: content is not a path-only change")
        elif status == "D":
            counts["deleted"] += 1
            if old not in DELETED:
                problems.append(f"{old}: deleted, and not in DELETED")
        elif status == "A":
            if new not in ADDED:
                problems.append(f"{new}: added, and not in ADDED or --hand-edited")
        else:
            problems.append(f"{old}: unexpected status {status!r}")
    for path in sorted(hand_edited - seen_hand):
        problems.append(f"{path}: listed as hand-edited but the diff does not touch it")
    problems.extend(leftovers(head))
    return problems, counts


def _numstat(base: str, head: str) -> dict[str, tuple[str, str]]:
    """{path at HEAD: (added, removed)}, with renames paired as in `changes`."""
    fields = _git("diff", "-z", "--numstat", "--find-renames=50%", base, head
                  ).decode("utf-8").split("\0")
    out, i = {}, 0
    while i < len(fields) and fields[i]:
        added, removed, path = fields[i].split("\t", 2)
        if path:                       # plain change: path inline
            out[path] = (added, removed)
            i += 1
        else:                          # rename: old and new follow
            out[fields[i + 2]] = (added, removed)
            i += 3
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("base")
    ap.add_argument("head", nargs="?", default="HEAD")
    ap.add_argument("--hand-edited", nargs="*", default=[],
                    help="paths (as they are at HEAD) changed by hand; printed for review")
    args = ap.parse_args(argv)
    hand = set(args.hand_edited)
    problems, counts = check(args.base, args.head, hand)
    summary = ", ".join(f"{v} {k}" for k, v in counts.items())
    if problems:
        print(f"NOT a pure src-layout move ({summary}):")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"pure src-layout move: {summary}")
    if hand:
        print("hand-edited — review these diffs, and only these:")
        sizes = _numstat(args.base, args.head)
        for path in sorted(hand):
            added, removed = sizes.get(path, ("?", "?"))
            print(f"  {path}  (+{added} -{removed})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
