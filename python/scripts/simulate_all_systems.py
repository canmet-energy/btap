#!/usr/bin/env python3
"""Simulate every catalogue system and write the verdict file from real runs.

`python/tests/modeling/test_system_simulation_status.py` asserts that every
catalogue system produces a model EnergyPlus will start. The defect class it
guards is a required performance-curve field left UNSET: the SDK models that
as merely absent, so every in-process assertion passes and the model looks
fine right up until E+ refuses it — the VRF defrost-EIR curve incident.

**That test reads a verdict this script produces, and this script did not
exist.** Its docstring named a Ruby twin at
`btap-modeling/test/fixtures/system_simulation_status.json` as the owner, and
the Ruby gems retired at R6 under D-84, so the file had no producer at all.
What it held was 97 rows of `{"family", "name", "status": "ok"}` — no run
directory, no error counts, no provenance, no timestamp — which is the
"handwritten `ok` entries" `docs/HVAC_MODERN_SYSTEMS_PLAN.md` warns against
in the same breath as it requires a sweep before new rows are added.

SIZING ONLY, deliberately. The property under test is that EnergyPlus starts
and gets through sizing with no Severe or Fatal error, which is exactly where
an unset curve field is refused. An annual run would cost hours and establish
the same thing about startup.

Usage::

    python3 python/scripts/simulate_all_systems.py              # all rows
    python3 python/scripts/simulate_all_systems.py --name "VRF" # substring
    python3 python/scripts/simulate_all_systems.py --limit 5    # first N
    python3 python/scripts/simulate_all_systems.py --check      # no writes

ONE AT A TIME by default. Each run loads the SDK and starts EnergyPlus, and
this repository has already taken a 32 GB VM down by running several at once
(CLAUDE.md, Traps). `--jobs N` is available and is not the default.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

CATALOGUE = (REPO_ROOT / "python" / "btap" / "modeling" / "hvac" / "data"
             / "systems.json")
FIXTURE = (REPO_ROOT / "python" / "btap" / "modeling" / "hvac" / "data"
           / "5ZoneNoHVAC.osm")
WEATHER_DIR = REPO_ROOT / "python" / "tests" / "fixtures" / "weather"
EPW = WEATHER_DIR / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw"
DDY = WEATHER_DIR / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy"
STATUS = REPO_ROOT / "python" / "tests" / "fixtures" / "system_simulation_status.json"

#: Severity markers `eplusout.err` uses. `is_clean_run` looks for these two
#: and for the completion line; this script records the COUNTS as well, so a
#: verdict says how badly a system failed and not merely that it did.
SEVERE = "** Severe  **"
FATAL = "** Fatal  **"
COMPLETED = "EnergyPlus Completed Successfully"


def catalogue_rows():
    rows = json.loads(CATALOGUE.read_text(encoding="utf-8"))["systems"]
    return [{"name": r["name"], "family": r.get("family")} for r in rows]


def producer_identity():
    """What produced this verdict, as far as it can be established.

    A record, never a gate: nothing compares it against the running machine,
    because a verdict produced on one host must stay readable on another.
    This is the same stance as `verification/scenarios/freeze.py`'s
    `produced_by`.
    """
    try:
        cli = subprocess.run(["openstudio", "openstudio_version"],
                             capture_output=True, text=True,
                             timeout=60).stdout.strip()
    except Exception:                                         # noqa: BLE001
        cli = "unknown"
    try:
        import openstudio
        sdk = openstudio.openStudioLongVersion()
    except Exception:                                         # noqa: BLE001
        sdk = "unknown"
    return {"openstudio_cli": cli, "openstudio_sdk": sdk,
            "fixture": FIXTURE.name, "weather": EPW.name,
            "mode": "sizing-only (design days)"}


def simulate_one(row, keep_dir=None):
    """Build one system on the fixture and run sizing. Returns a verdict dict.

    Every failure mode is CAUGHT and recorded rather than raised, because a
    sweep that stops at the first broken system tells you about one system.
    The distinction the verdict carries is between a system that could not be
    BUILT and one that built and then failed in EnergyPlus — different
    defects, in different code.
    """
    import openstudio

    import btap.modeling as modeling
    import btap.simulation as simulation

    started = time.time()
    verdict = {"name": row["name"], "family": row["family"]}
    work = pathlib.Path(keep_dir) if keep_dir else pathlib.Path(
        tempfile.mkdtemp(prefix="sweep-"))
    try:
        loaded = openstudio.osversion.VersionTranslator().loadModel(
            openstudio.toPath(str(FIXTURE)))
        if not loaded.is_initialized():
            verdict.update(status="fixture_error",
                           detail=f"{FIXTURE.name} did not load")
            return verdict
        model = loaded.get()
        zones = sorted(model.getThermalZones(),
                       key=lambda z: z.nameString())
        try:
            modeling.build_system(model, row["name"], zones)
        except Exception as error:                            # noqa: BLE001
            verdict.update(status="build_error",
                           detail=f"{type(error).__name__}: {error}"[:400],
                           traceback=traceback.format_exc()[-600:])
            return verdict

        result = simulation.run(model, run_dir=str(work / "run"),
                                weather={"epw": str(EPW), "ddy": str(DDY)},
                                sizing_only=True)
        err_path = pathlib.Path(result.run_dir) / "eplusout.err"
        err = (err_path.read_text(encoding="utf-8", errors="replace")
               if err_path.is_file() else "")
        severe, fatal = err.count(SEVERE), err.count(FATAL)
        verdict.update(
            status="ok" if result.is_clean() else "simulation_error",
            severe=severe, fatal=fatal,
            completed=COMPLETED in err)
        if not result.is_clean():
            # The FIRST severe/fatal line, which is the one that explains the
            # rest. A verdict that says only "not clean" sends the next
            # reader back to a run directory this script deleted.
            for line in err.splitlines():
                if SEVERE in line or FATAL in line:
                    verdict["detail"] = line.strip()[:300]
                    break
        return verdict
    except Exception as error:                                # noqa: BLE001
        verdict.update(status="sweep_error",
                       detail=f"{type(error).__name__}: {error}"[:400],
                       traceback=traceback.format_exc()[-600:])
        return verdict
    finally:
        verdict["seconds"] = round(time.time() - started, 1)
        if keep_dir is None:
            shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", action="append", default=None,
                    help="only systems whose name contains this (repeatable)")
    ap.add_argument("--limit", type=int, default=None,
                    help="only the first N rows, for a smoke run")
    ap.add_argument("--check", action="store_true",
                    help="run the sweep and DIFF against the committed "
                         "verdict without writing it")
    ap.add_argument("--keep", metavar="DIR", default=None,
                    help="keep run directories under DIR for inspection")
    args = ap.parse_args()

    for required in (CATALOGUE, FIXTURE, EPW, DDY):
        if not required.is_file():
            sys.exit(f"missing: {required}")

    rows = catalogue_rows()
    if args.name:
        rows = [r for r in rows
                if any(n.lower() in r["name"].lower() for n in args.name)]
    if args.limit:
        rows = rows[:args.limit]
    if not rows:
        sys.exit("no catalogue rows selected")

    print(f"sweeping {len(rows)} of {len(catalogue_rows())} catalogue "
          f"systems, sizing only, one at a time", flush=True)
    verdicts = []
    for index, row in enumerate(rows, 1):
        keep = (str(pathlib.Path(args.keep) / f"{index:03d}")
                if args.keep else None)
        verdict = simulate_one(row, keep_dir=keep)
        verdicts.append(verdict)
        mark = "ok  " if verdict["status"] == "ok" else "FAIL"
        print(f"  [{index:3d}/{len(rows)}] {mark} {verdict['seconds']:6.1f}s "
              f"{row['name'][:58]}", flush=True)
        if verdict["status"] != "ok":
            print(f"            {verdict['status']}: "
                  f"{verdict.get('detail', '')[:100]}", flush=True)

    failed = [v for v in verdicts if v["status"] != "ok"]
    print(f"\n{len(verdicts) - len(failed)}/{len(verdicts)} ok, "
          f"{len(failed)} failed")
    for verdict in failed:
        print(f"  {verdict['status']:18} {verdict['name']}")

    payload = {
        "produced_by": producer_identity(),
        "systems": sorted(verdicts, key=lambda v: v["name"]),
    }
    if args.check:
        committed = json.loads(STATUS.read_text(encoding="utf-8"))
        previous = ({v["name"]: v.get("status")
                     for v in committed.get("systems", committed)}
                    if committed else {})
        current = {v["name"]: v["status"] for v in verdicts}
        moved = {n: (previous.get(n), s) for n, s in current.items()
                 if previous.get(n) != s}
        if moved:
            print("\nverdicts that MOVED against the committed file:")
            for name, (was, now) in sorted(moved.items()):
                print(f"  {name}: {was} -> {now}")
            sys.exit(1)
        print("\nno verdict moved")
        return

    if args.name or args.limit:
        print("\npartial sweep — NOT writing the verdict file. A verdict "
              "file is a claim about every catalogue row, and a subset "
              "cannot make it.")
        return

    STATUS.write_text(json.dumps(payload, indent=2, ensure_ascii=False)
                      + "\n", encoding="utf-8")
    print(f"\nwrote {STATUS.relative_to(REPO_ROOT)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
