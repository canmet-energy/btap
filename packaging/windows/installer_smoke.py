#!/usr/bin/env python3
"""Prove the STAGED tree works with no checkout, no Python, no env vars.

    python3 packaging/windows/installer_smoke.py --stage <dir> [--full]

Deliberately NOT a frozen-scenario lane: this exercises packaging, not
compliance behaviour, and adding it to the sealed suite would edit a pinned
gate for no verification value.

The control that matters is H-9: the staged tree must run from a directory
the repository is not visible from. A recipient has no checkout, so anything
the payload resolves relatively — the weather files, the sample model, the
interpreter, site-packages — has to be inside it. Run from the repo root,
every one of those could resolve by accident and the test would pass while
proving nothing.

On Linux only the structure can be checked: the payload is Windows binaries.
On windows-latest the launcher is actually executed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def fail(msg: str) -> None:
    print(f"INSTALLER SMOKE FAILED: {msg}", file=sys.stderr)
    raise SystemExit(1)


def check_structure(stage: Path) -> None:
    """What must exist, and what must NOT."""
    required = [
        "bin/btap-compliance.cmd", "python/python.exe", "python/python312.dll",
        "python/python312._pth", "python/Lib/site-packages/btap/necb/cli.py",
        "python/Lib/site-packages/openstudio", "samples/run-demo.cmd",
        "samples/5ZoneNoHVAC.osm", "LICENSE", "THIRD-PARTY-NOTICES.txt",
        "PROVENANCE.json", "README-windows.txt",
    ]
    for rel in required:
        if not (stage / rel).exists():
            fail(f"the staged tree is missing {rel}")

    weather = sorted((stage / "weather").glob("*.epw"))
    if not weather:
        fail("no .epw in the staged weather/ — the CLI reads BTAP_HOME/weather "
             "and a recipient has no checkout to fall back on")

    # The engine must be INSIDE the payload. If it is absent the tool would
    # try to download 230 MB on first use, on a machine that may have no
    # network — the exact surprise this installer exists to prevent.
    engine = stage / "python/Lib/site-packages/canmet_energyplus/payload/energyplus.exe"
    if not engine.is_file():
        fail("the payload carries no energyplus.exe")

    # pip --target writes POSIX console-script shims that cannot run under the
    # embeddable runtime; the launcher uses -m instead, and leaving them would
    # invite a user to run something broken.
    strays = list((stage / "python" / "Lib" / "site-packages").glob("bin/*"))
    if strays:
        fail(f"POSIX console-script shims survived staging: {strays[:3]}")

    print(f"structure ok: {len(required)} required paths, "
          f"{len(weather)} weather file(s), engine in payload")


def check_isolated_run(stage: Path, full: bool) -> None:
    """H-9: run the launcher from OUTSIDE the checkout, with nothing set."""
    if sys.platform != "win32":
        print("isolated run: skipped (the payload is Windows binaries; "
              "windows-latest executes this leg)")
        return

    with tempfile.TemporaryDirectory(prefix="installer-smoke-") as tmp:
        tmp = Path(tmp)
        # COPY the tree elsewhere: running it in place, inside the checkout,
        # would let a relative path resolve against the repository and prove
        # nothing about what a recipient gets.
        installed = tmp / "BTAP Compliance"
        shutil.copytree(stage, installed)
        launcher = installed / "bin" / "btap-compliance.cmd"

        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("BTAP_", "PYTHON"))}
        env["USERPROFILE"] = str(tmp)
        env["LOCALAPPDATA"] = str(tmp / "cache")

        out = subprocess.run([str(launcher), "--help"], capture_output=True,
                             text=True, cwd=str(tmp), env=env, timeout=300)
        if out.returncode != 0 or "btap-compliance" not in out.stdout:
            fail(f"--help failed from outside the checkout (exit {out.returncode}):\n"
                 f"{(out.stdout + out.stderr)[-1200:]}")
        print("H-9 ok: the launcher answers --help from a copied tree with no "
              "checkout, no PYTHON* and no BTAP_* in the environment")

        if not full:
            return

        run_dir = tmp / "out"
        epw = sorted((installed / "weather").glob("*.epw"))[0]
        out = subprocess.run(
            [str(launcher), str(installed / "samples" / "5ZoneNoHVAC.osm"),
             "--simulate", "sizing", "--epw", str(epw),
             "--hdd", "3890", "--storeys", "1", "--no-report", "--quiet",
             "--space-type", "Space Function/Office enclosed > 25 m2",
             "-o", str(run_dir)],
            capture_output=True, text=True, cwd=str(tmp), env=env, timeout=2400)
        # 6 is "ran, no determination" for a sizing-only run.
        if out.returncode not in (0, 6):
            fail(f"the sample sizing run exited {out.returncode}:\n"
                 f"{(out.stdout + out.stderr)[-1500:]}")
        for expected in ("proposed_sizing", "reference_sizing", "audit.json"):
            if not (run_dir / expected).exists():
                fail(f"the sizing run produced no {expected}")
        provisioned = list((tmp / "cache").rglob("energyplus*"))
        if provisioned:
            fail(f"an engine was provisioned into the cache ({provisioned[:2]}) "
                 "— the payload did NOT supply it")
        print("full run ok: proposed + reference sizing completed from the "
              "installed tree, engine supplied by the payload (cache empty)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", default=str(HERE / "stage"))
    ap.add_argument("--full", action="store_true",
                    help="also run a real sizing simulation (windows only)")
    args = ap.parse_args()
    stage = Path(args.stage).resolve()
    if not stage.is_dir():
        fail(f"no staged tree at {stage}")

    prov = json.loads((stage / "PROVENANCE.json").read_text(encoding="utf-8"))
    print(f"smoking canmet-btap {prov['canmet_btap_version']} "
          f"(CPython {prov['cpython']['version']}, "
          f"{len(prov['distributions'])} distributions)")
    check_structure(stage)
    check_isolated_run(stage, args.full)
    print("INSTALLER SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
