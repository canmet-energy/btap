"""Size every AUTHORED sample and refuse any Severe or Fatal error.

    python3 python/scripts/simulate_all_samples.py            # writes the verdict
    python3 python/scripts/simulate_all_samples.py --check     # re-derives, no writes

## Why this exists beside the catalogue sweep

`simulate_all_systems.py` proves each catalogue SYSTEM on the shared bare
fixture. It does not prove the GENERATED SAMPLE, which is that system built
onto a seed, with NECB loads applied and sample-specific setup run. Issue #68
lived in exactly that gap: `FPFC MAU DX Coils with Scroll Chiller` is `ok`
with `severe: 0` in the catalogue verdict, and sample `04-fancoil-chiller` —
the same system — shipped with a `Coil:Cooling:Water` design-UA Severe for
two orders of magnitude longer than it should have, because nothing sized the
artifact we actually ship.

The rule this enforces is CLAUDE.md's: a sample WE author should be clean,
because shipping one with a known Severe teaches the wrong thing. A
submitter's proposed model is governed by the opposite policy — a Severe does
not stop the run — and this script has no opinion about those.

Sol required it in `313` as part of the #68 correction: "Run the generated
sample corpus through a serial sizing sweep and require zero Severe and Fatal
errors."

Serial by construction. Each sizing run is ~12 s and the corpus is 22 models,
so a full sweep is about four and a half minutes; running them concurrently
would put several SDK-loaded processes and several EnergyPlus runs on one host
at once, which is the trap CLAUDE.md records taking a 32 GB VM down.
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

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = REPO_ROOT / "python"
GENERATOR = PYTHON_ROOT / "scripts" / "generate_samples.py"
MANIFEST = PYTHON_ROOT / "scripts" / "sample_manifest.json"
STATUS = PYTHON_ROOT / "tests" / "fixtures" / "sample_simulation_status.json"
EPW = (PYTHON_ROOT / "tests" / "fixtures" / "weather"
       / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw")

SEVERE_RE = re.compile(r"\*\*\s*Severe\s*\*\*")
FATAL_RE = re.compile(r"\*\*\s*Fatal\s*\*\*")
COMPLETED = "EnergyPlus Completed Successfully"

#: `--simulate sizing` cannot reach a determination, so exit 6 is the SUCCESS
#: code here. Treating a non-zero exit as failure would fail every sample.
SIZING_EXIT_OK = frozenset({0, 6})

SCHEMA = 1


def python_exe() -> str:
    venv = PYTHON_ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def expected_slugs() -> list[str]:
    return sorted(json.loads(MANIFEST.read_text(encoding="utf-8"))["samples"])


def generate_corpus(out: pathlib.Path) -> None:
    proc = subprocess.run(
        [python_exe(), str(GENERATOR), str(out)],
        capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(
            f"sample generation failed:\n{proc.stderr[-2000:]}")
    produced = sorted(p.stem for p in out.glob("*.osm"))
    expected = expected_slugs()
    if produced != expected:
        raise SystemExit(
            "generated corpus does not match sample_manifest.json:\n"
            f"  missing: {sorted(set(expected) - set(produced))}\n"
            f"  extra:   {sorted(set(produced) - set(expected))}")


def size_one(osm: pathlib.Path) -> dict:
    """Size one sample and read its `eplusout.err` for Severe and Fatal."""
    run_dir = pathlib.Path(tempfile.mkdtemp(prefix="sample-sizing-"))
    try:
        cli = PYTHON_ROOT / ".venv" / "bin" / "btap-compliance"
        command = ([str(cli)] if cli.is_file()
                   else [python_exe(), "-m", "btap.codes.cli"])
        proc = subprocess.run(
            command + [str(osm), "--simulate", "sizing", "--epw", str(EPW),
                       "--hdd", "3890", "--no-report", "--quiet",
                       "-o", str(run_dir)],
            capture_output=True, text=True, check=False)
        errs = sorted(run_dir.rglob("eplusout.err"))
        if not errs:
            return {"name": osm.stem, "status": "sizing_error",
                    "severe": 0, "fatal": 0, "completed": False,
                    "exit": proc.returncode,
                    "detail": (proc.stderr or proc.stdout)[-300:]}
        text = errs[0].read_text(encoding="utf-8", errors="replace")
        severe = len(SEVERE_RE.findall(text))
        fatal = len(FATAL_RE.findall(text))
        completed = COMPLETED in text
        clean = (severe == 0 and fatal == 0 and completed
                 and proc.returncode in SIZING_EXIT_OK)
        return {"name": osm.stem,
                "status": "ok" if clean else "simulation_error",
                "severe": severe, "fatal": fatal, "completed": completed,
                "exit": proc.returncode}
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def sweep() -> dict:
    with tempfile.TemporaryDirectory(prefix="sample-corpus-") as scratch:
        corpus = pathlib.Path(scratch)
        generate_corpus(corpus)
        rows = []
        for slug in expected_slugs():
            row = size_one(corpus / f"{slug}.osm")
            flag = "" if row["status"] == "ok" else "   <-- DIRTY"
            print(f"  {slug:38} severe={row['severe']} "
                  f"fatal={row['fatal']}{flag}", flush=True)
            rows.append(row)
    return {"schema": SCHEMA, "samples": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="re-derive the verdict and diff it, writing nothing")
    args = ap.parse_args()

    if not EPW.is_file():
        raise SystemExit(f"weather file missing: {EPW}")

    payload = sweep()
    dirty = [r for r in payload["samples"] if r["status"] != "ok"]

    if args.check:
        if not STATUS.is_file():
            print(f"no committed verdict at {STATUS}", file=sys.stderr)
            return 1
        committed = json.loads(STATUS.read_text(encoding="utf-8"))
        if committed != payload:
            print("the committed sample verdict is STALE:", file=sys.stderr)
            was = {r["name"]: r for r in committed.get("samples", [])}
            now = {r["name"]: r for r in payload["samples"]}
            for name in sorted(set(was) | set(now)):
                if was.get(name) != now.get(name):
                    print(f"  {name}: {was.get(name)} -> {now.get(name)}",
                          file=sys.stderr)
            return 1
        print(f"sample sweep: {len(payload['samples'])} samples, "
              f"{len(dirty)} dirty, verdict up to date")
    else:
        STATUS.write_text(json.dumps(payload, indent=1) + "\n",
                          encoding="utf-8")
        print(f"wrote {STATUS.relative_to(REPO_ROOT)}")

    if dirty:
        print("\nREFUSED: a sample WE author must size cleanly. "
              "Shipping one with a known Severe teaches the wrong thing.",
              file=sys.stderr)
        for row in dirty:
            print(f"  {row['name']}: severe={row['severe']} "
                  f"fatal={row['fatal']} exit={row['exit']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
