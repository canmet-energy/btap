#!/usr/bin/env python3
"""Report commits and changed paths between legacy_pin/REF and a fork tip."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIN_REF = REPO_ROOT / "legacy_pin" / "REF"
DEFAULT_REMOTE = "https://github.com/NatLabRockies/openstudio-standards.git"
DEFAULT_CACHE = REPO_ROOT / "tmp" / "legacy_fork.git"

OWNERS = [
    (re.compile(r"^test/"), "legacy TESTS - oracle behaviour, not our source"),
    (re.compile(r"^data/"), "legacy DATA - check whether Python vendored a copy"),
    (re.compile(r"/btap/costing/|/btap/common/.*\.csv$"),
     "costing (hvac + envelope + lighting + shw)"),
    (re.compile(r"/btap/geometry\.rb|create_shape|create_bar"), "btap.modeling"),
    (re.compile(r"space_types\.json|schedules\.json|beps_compliance_path\.rb"),
     "btap.necb (loads)"),
    (re.compile(r"lighting|daylight"), "btap.necb (lighting)"),
    (re.compile(r"service_water_heating|shw"), "btap.necb (shw)"),
    (re.compile(r"hvac_system|autozone|efficienc|curves|chiller|boiler|/fan"),
     "btap.necb (hvac) or btap.modeling"),
    (re.compile(r"building_envelope|thermal_transmittance|fdwr|thermal_bridging"),
     "btap.necb (envelope)"),
    (re.compile(r"necb_20\d\d\.rb"), "btap.necb (+ the domain each hunk touches)"),
]


class LegacyError(RuntimeError):
    pass


def git(directory: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, check=False,
    )
    if check and result.returncode != 0:
        raise LegacyError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def owner_for(path: str) -> str:
    return next((owner for pattern, owner in OWNERS if pattern.search(path)),
                "UNMAPPED - review by hand")


def local_fork() -> Path | None:
    for variable in ("LEGACY_FORK", "LEGACY_PIN_REMOTE"):
        value = os.environ.get(variable, "")
        if not value or value.startswith(("http", "git@")):
            continue
        path = Path(value).expanduser().resolve()
        if (path / ".git").is_dir() or (path / "objects").is_dir():
            return path
    return None


def cached_mirror(branch: str, cache: Path = DEFAULT_CACHE) -> Path:
    remote = os.environ.get("LEGACY_FORK", DEFAULT_REMOTE)
    if not cache.is_dir():
        cache.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--bare", "--filter=blob:none", remote, str(cache)],
            check=False,
        )
        if result.returncode != 0:
            raise LegacyError(
                f"could not clone {remote} - pass LEGACY_FORK=/path/to/a/local/checkout")
    subprocess.run(
        ["git", "-C", str(cache), "fetch", "--quiet", "origin",
         f"+refs/heads/{branch}:refs/heads/{branch}"], check=True,
    )
    return cache


def _resolves(directory: Path, revision: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "--verify", "--quiet",
         f"{revision}^{{commit}}"], capture_output=True, check=False,
    )
    return result.returncode == 0


def report(directory: Path, pin: str, *, branch: str = "nrcan",
           tip: str | None = None) -> dict:
    if not _resolves(directory, pin):
        raise LegacyError(f"pinned revision {pin[:12]} is not in {directory}")
    if tip is None:
        tip = next((candidate for candidate in (f"origin/{branch}", f"refs/heads/{branch}")
                    if _resolves(directory, candidate)), None)
    if tip is None or not _resolves(directory, tip):
        raise LegacyError(f"branch or tip '{tip or branch}' not found in {directory}")
    tip_sha = git(directory, "rev-parse", f"{tip}^{{commit}}").strip()
    commits = [line.split("\t", 3) for line in git(
        directory, "log", "--format=%H%x09%h%x09%ad%x09%s", "--date=short",
        "--reverse", f"{pin}..{tip_sha}").splitlines()]
    changed = []
    for line in git(directory, "diff", "--name-status", pin, tip_sha).splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        path = parts[-1]
        changed.append({"status": parts[0], "path": path, "owner": owner_for(path)})
    return {"pin": pin, "tip": tip_sha, "branch": branch,
            "commits": [{"sha": row[0], "short": row[1], "date": row[2],
                         "subject": row[3]} for row in commits],
            "changed": changed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--branch", default=os.environ.get("BRANCH", "nrcan"))
    parser.add_argument("--tip", default=os.environ.get("TIP"))
    args = parser.parse_args(argv)
    directory = local_fork() or cached_mirror(args.branch)
    result = report(directory, PIN_REF.read_text(encoding="utf-8").strip(),
                    branch=args.branch, tip=args.tip)
    if args.json:
        print(json.dumps(result, indent=1))
        return 0
    print(f"legacy oracle: {result['pin']}")
    print(f"fork tip:     {result['tip']} ({result['branch']})")
    print(f"{len(result['commits'])} commit(s), {len(result['changed'])} changed path(s)")
    for commit in result["commits"]:
        print(f"  {commit['short']}  {commit['date']}  {commit['subject']}")
    grouped: dict[str, list[dict]] = {}
    for item in result["changed"]:
        grouped.setdefault(item["owner"], []).append(item)
    for owner, items in sorted(grouped.items(), key=lambda pair: pair[0]):
        print(f"\n{owner} ({len(items)})")
        for item in items:
            print(f"  {item['status']}  {item['path']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LegacyError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error