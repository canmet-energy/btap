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

SIZING by default, and `--annual` for the stronger claim. What a sizing run
establishes is **no Severe or Fatal error on the DESIGN DAYS** — not "a model
EnergyPlus can start", which is how I first put it and which overstates it.

Fable's `234` built the counterexample, with controls:

    run                                   clean  severe  s
    mutated VRF CoolCapFT, SIZING         True        0  2.6
    mutated VRF CoolCapFT, ANNUAL         False       5  16.8
    unmodified VRF, annual (control)      True        0  14.3

The curve is positive at every design-day condition and negative below 17 C,
so the design days never consult the broken part. That is the same FAMILY as
the VRF defrost-EIR incident this verdict exists to catch, which makes the
gap a real one rather than a theoretical one.

Annual costs 14-19 s per system against ~4.7 s for sizing — about 28 minutes
for the whole catalogue, not the "hours" I claimed. `--annual` is therefore
affordable, and the verdict records which mode produced it so a reader is
never left guessing which claim the rows support.

Usage::

    python3 python/scripts/simulate_all_systems.py              # all rows
    python3 python/scripts/simulate_all_systems.py --name "VRF" # substring
    python3 python/scripts/simulate_all_systems.py --limit 5    # first N
    python3 python/scripts/simulate_all_systems.py --check      # no writes

ONE AT A TIME, always. Each run loads the SDK and starts EnergyPlus, and
this repository has already taken a 32 GB VM down by running several at once
(CLAUDE.md, Traps). An earlier version of this docstring advertised a
`--jobs N` flag that was never implemented (Sol, `234`); there is no
parallel mode, and ~8 minutes for the whole catalogue is the cost.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
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

#: Severity markers in `eplusout.err`, as REGEXES. EnergyPlus pads them
#: differently — `** Severe  **` has one leading space and `**  Fatal  **`
#: has two — and my first version wrote both as literals with one, so the
#: fatal count was structurally always 0 (Sol, `234`). `is_clean_run` got
#: this right with `\*\*\s*Fatal\s*\*\*`; the counts now use the same
#: shape rather than a second, worse copy of the same knowledge.
SEVERE_RE = re.compile(r"\*\*\s*Severe\s*\*\*")
FATAL_RE = re.compile(r"\*\*\s*Fatal\s*\*\*")
COMPLETED = "EnergyPlus Completed Successfully"


def catalogue_rows():
    rows = json.loads(CATALOGUE.read_text(encoding="utf-8"))["systems"]
    return [{"name": r["name"], "family": r.get("family")} for r in rows]


#: Bumped when the verdict's SHAPE changes, so both readers can refuse an
#: unknown format instead of failing accidentally on it. The rows moved
#: under a `systems` key once already and broke a reader that iterated the
#: top level as a list.
SCHEMA_VERSION = 1

#: The statuses `simulate_one` can return. A closed vocabulary, so a row
#: carrying something else is a malformed verdict rather than a new state
#: nobody has to handle.
STATUSES = ("ok", "build_error", "simulation_error", "sweep_error",
            "fixture_error")


def _sha256(path):
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _probe(command):
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=60)
        return (done.stdout + done.stderr).strip().splitlines()[0][:120]
    except Exception:                                         # noqa: BLE001
        return "unknown"


def producer_identity(annual=False):
    """What produced this verdict, and from WHICH inputs.

    A record, never a gate: nothing compares it against the machine reading
    it, because evidence produced on one supported host must stay readable on
    another. That is not the same as recording nothing useful, and the first
    version recorded the wrong things (Sol, `234`):

    - it named the OpenStudio SDK and an `openstudio` CLI probe, though the
      product does not use that CLI to simulate;
    - it OMITTED EnergyPlus — the program whose success IS the verdict;
    - it omitted the DDY that supplies the design days, recording only the
      EPW;
    - it carried no source revision and no input digests, so a reader could
      not tell which builder implementation or which weather bytes the rows
      attest to;
    - and it had no timestamp, while this module's own introduction cited the
      old file's missing timestamp as part of the problem.
    """
    try:
        import openstudio
        sdk = openstudio.openStudioLongVersion()
    except Exception:                                         # noqa: BLE001
        sdk = "unknown"
    try:
        revision = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=60).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            capture_output=True, text=True, timeout=120).stdout.strip())
    except Exception:                                         # noqa: BLE001
        revision, dirty = "unknown", True
    return {
        "schema_version": SCHEMA_VERSION,
        "openstudio_sdk": sdk,
        # The program whose Severe/Fatal count this verdict reports.
        "energyplus": _probe(["energyplus", "--version"]),
        "mode": ("annual (full run period from the EPW)" if annual else
                 "sizing-only (design days from the DDY; no run period)"),
        # WHAT WAS VERIFIED. A catalogue row edited under its own name
        # leaves every name-based check green, which is the stale-artifact
        # attack both reviewers landed (Sol's `234` B1, Fable's `234`). This
        # is a digest of the catalogue DATA the rows describe — not of the
        # builder source, which is the machinery-hash pattern D-103 retired
        # and which would prove the code changed rather than that the
        # systems still simulate.
        "catalogue": CATALOGUE.name,
        "catalogue_sha256": _sha256(CATALOGUE),
        "fixture": FIXTURE.name,
        "fixture_sha256": _sha256(FIXTURE),
        "epw": EPW.name,
        "epw_sha256": _sha256(EPW),
        "ddy": DDY.name,
        "ddy_sha256": _sha256(DDY),
        "source_revision": revision,
        "source_dirty": dirty,
        "generated_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).replace(
                microsecond=0).isoformat(),
    }


def _read_err(run_dir):
    """`eplusout.err`, wherever under `run_dir` the backend left it.

    The local backend nests its own run directory, so the file is not always
    at the top level — and on a failed run there is no `Result` to ask for
    the path.
    """
    run_dir = pathlib.Path(run_dir)
    direct = run_dir / "eplusout.err"
    if direct.is_file():
        return direct.read_text(encoding="utf-8", errors="replace")
    for found in sorted(run_dir.rglob("eplusout.err")):
        return found.read_text(encoding="utf-8", errors="replace")
    return ""


def simulate_one(row, keep_dir=None, annual=False):
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

        # THE BACKEND RAISES on a failed run, so the evidence has to be
        # gathered on the exception path too. My first version read
        # `eplusout.err` only after a successful `simulation.run`, which
        # meant a system that failed in EnergyPlus — the exact defect class
        # this script exists to catch — returned `sweep_error` with no
        # severe count, no fatal count and no completion flag (Sol, `234`).
        # The advertised diagnostic was produced only for runs that did not
        # need it.
        run_dir = work / "run"
        failed_to_run = None
        try:
            result = simulation.run(model, run_dir=str(run_dir),
                                    weather={"epw": str(EPW),
                                             "ddy": str(DDY)},
                                    sizing_only=not annual)
            clean = result.is_clean()
            where = pathlib.Path(result.run_dir)
        except Exception as error:                            # noqa: BLE001
            clean = False
            failed_to_run = f"{type(error).__name__}: {error}"
            where = run_dir
        err = _read_err(where)
        severe = len(SEVERE_RE.findall(err))
        fatal = len(FATAL_RE.findall(err))
        verdict.update(status="ok" if clean else "simulation_error",
                       severe=severe, fatal=fatal,
                       completed=COMPLETED in err)
        if not clean:
            # The FIRST severe/fatal line, which is the one that explains the
            # rest. A verdict that says only "not clean" sends the next
            # reader back to a run directory this script deleted.
            for line in err.splitlines():
                if SEVERE_RE.search(line) or FATAL_RE.search(line):
                    verdict["detail"] = line.strip()[:300]
                    break
            if "detail" not in verdict:
                # No marker found: the run may not have reached EnergyPlus
                # at all. Say what went wrong rather than leaving a verdict
                # that reports a failure with no account of it.
                verdict["detail"] = (failed_to_run
                                     or "not clean, and eplusout.err holds "
                                        "no severity marker")
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
    ap.add_argument("--annual", action="store_true",
                    help="run a full year instead of design days only. "
                         "Catches curve-domain defects that the design days "
                         "never reach, at ~14-19 s per system against ~4.7 "
                         "(Fable, `234`). The verdict records the mode.")
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
        verdict = simulate_one(row, keep_dir=keep,
                               annual=args.annual)
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
        "produced_by": producer_identity(annual=args.annual),
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
        # EXACT SET, both directions — but only when the whole catalogue ran.
        # Comparing names present in the newly run set left a REMOVED
        # catalogue row's old verdict unexamined: the row sits in the file
        # describing a system that no longer exists, and nothing looked
        # (Sol, `234`).
        # Independent of what THIS invocation ran: comparing the committed
        # verdict's names against the catalogue needs no runs at all. My
        # first version gated it on a full sweep, so `--check --limit 1`
        # with a planted phantom row still said "no verdict moved" and
        # exited 0 (Fable, `234`).
        if True:
            catalogue = {row["name"] for row in catalogue_rows()}
            stale = sorted(set(previous) - catalogue)
            missing = sorted(catalogue - set(previous))
            if stale or missing:
                print("\nthe committed verdict does not describe this "
                      "catalogue:")
                for name in stale:
                    print(f"  verdict has a row for {name!r}, which the "
                          "catalogue does not")
                for name in missing:
                    print(f"  catalogue has {name!r}, which the verdict does "
                          "not")
                sys.exit(1)
        if moved:
            print("\nverdicts that MOVED against the committed file:")
            for name, (was, now) in sorted(moved.items()):
                print(f"  {name}: {was} -> {now}")
            sys.exit(1)
        print("\nno verdict moved")
        # Same rule: --check compares verdicts, and a system that FAILED in
        # this run is a failure whether or not its recorded status moved.
        # A newly-broken system whose committed status is already `ok` moves
        # nothing and must not exit 0.
        sys.exit(1 if failed else 0)

    if args.name or args.limit:
        print("\npartial sweep — NOT writing the verdict file. A verdict "
              "file is a claim about every catalogue row, and a subset "
              "cannot make it.")
        # EXIT STATUS STILL REPORTS THE FAILURE. The first version returned
        # here, so a smoke run that found a broken system printed FAIL and
        # exited 0 — invisible to a shell, a CI step or a `&&` chain, which
        # is every way this command is actually used (Sol, `234`). Not
        # writing the file is about the file; it says nothing about whether
        # what ran was healthy.
        sys.exit(1 if failed else 0)

    STATUS.write_text(json.dumps(payload, indent=2, ensure_ascii=False)
                      + "\n", encoding="utf-8")
    print(f"\nwrote {STATUS.relative_to(REPO_ROOT)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
