#!/usr/bin/env python3
"""Refuse to release a staged tree that would ship broken or unaccounted bytes.

    python3 packaging/windows/release_guards.py --version 0.2.1 [--stage DIR]

These run BEFORE the installer is compiled and before a tag is pushed. Each
one exists because the failure it catches is invisible until a user hits it:
a version triple that disagrees, a payload missing the interpreter, a licence
obligation silently dropped, or a staged tree that quietly kept the Ruby
installer's shape.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def fail(checks: list[str], msg: str) -> None:
    checks.append(f"FAIL {msg}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--stage", default=str(HERE / "stage"))
    args = ap.parse_args()
    stage = Path(args.stage).resolve()
    v = args.version
    problems: list[str] = []

    # 1. The version triple must agree: pyproject, __init__, and the iss
    #    AppVersion. A mismatch ships an installer whose name lies about
    #    what is inside it.
    pyproject = (REPO_ROOT / "python" / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version = "([^"]+)"', pyproject, re.M)
    if not m or m.group(1) != v:
        fail(problems, f"pyproject version {m and m.group(1)!r} != {v!r}")
    init = (REPO_ROOT / "python" / "btap" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__ = "([^"]+)"', init)
    if not m or m.group(1) != v:
        fail(problems, f"btap.__version__ {m and m.group(1)!r} != {v!r}")
    iss = (HERE / "btap-compliance.iss").read_text(encoding="utf-8")
    m = re.search(r'#define AppVersion "([^"]+)"', iss)
    if not m or m.group(1) != v:
        fail(problems, f"iss AppVersion {m and m.group(1)!r} != {v!r}")

    # 2. The payload must actually contain a runnable interpreter and the
    #    packages, not just a directory that looks right.
    for rel in ("python/python.exe", "python/python312.dll",
                "python/Lib/site-packages/btap",
                "python/Lib/site-packages/openstudio",
                "python/Lib/site-packages/canmet_energyplus",
                "btap-compliance.cmd", "LICENSE",
                "THIRD-PARTY-NOTICES.txt", "PROVENANCE.json", "weather"):
        if not (stage / rel).exists():
            fail(problems, f"staged tree is missing {rel}")

    # 3. site-packages must be ENABLED in the embeddable runtime, or the
    #    tree is unimportable on the user's machine and nowhere else.
    pth = stage / "python" / "python312._pth"
    if pth.is_file():
        text = pth.read_text(encoding="utf-8")
        if "Lib\\site-packages" not in text or "import site" not in text:
            fail(problems, "python312._pth does not enable Lib\\site-packages")
    else:
        fail(problems, "python312._pth is missing from the runtime")

    # 4. Every distribution must have a licence text, and the provenance must
    #    record the exact openstudio wheel — a later upload under the same
    #    version must not be able to change installer bytes unnoticed.
    prov_file = stage / "PROVENANCE.json"
    if prov_file.is_file():
        prov = json.loads(prov_file.read_text(encoding="utf-8"))
        if prov.get("canmet_btap_version") != v:
            fail(problems, f"PROVENANCE version {prov.get('canmet_btap_version')!r} != {v!r}")
        gaps = [d["name"] for d in prov.get("distributions", [])
                if not d.get("license_files")]
        if gaps:
            fail(problems, f"distributions with no licence text: {gaps}")
        os_dist = [d for d in prov.get("distributions", [])
                   if d["name"] == "openstudio"]
        if not os_dist:
            fail(problems, "PROVENANCE records no openstudio distribution")
        elif "win_amd64" not in (os_dist[0].get("wheel_tag") or ""):
            fail(problems, f"openstudio wheel tag is {os_dist[0].get('wheel_tag')!r}, "
                           "not a win_amd64 build — the stage was not cross-platform")
    else:
        fail(problems, "PROVENANCE.json is missing from the staged tree")

    # 5. The Ruby installer's shape must be GONE, not merely unused: a stray
    #    gems tree would ship dead weight and confuse the uninstaller.
    if (stage / "gems").exists():
        fail(problems, "the staged tree still contains a gems/ directory")
    if (stage / "openstudio").exists():
        fail(problems, "the staged tree contains a top-level openstudio/ tree "
                       "(the SDK now arrives as a wheel in site-packages)")

    for p in problems:
        print(p, file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} guard(s) failed — not releasable", file=sys.stderr)
        return 1
    print(f"release guards ok: version {v} agrees across pyproject, "
          "btap.__version__ and the iss; the payload carries a runnable "
          "runtime with site-packages enabled; every distribution has a "
          "licence text; the openstudio wheel is a win_amd64 build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
