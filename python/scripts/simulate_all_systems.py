#!/usr/bin/env python3
"""Build EVERY catalog system and put each through a real EnergyPlus sizing
run — the Python twin of btap-modeling/scripts/simulate_all_systems.rb, on
the M2 engine backend instead of the openstudio CLI.

    .venv/bin/python scripts/simulate_all_systems.py [--jobs N]
        [--only SUBSTRING] [--out PATH] [--check]

Why a SIMULATION and not a unit assertion: the defect class this exists to
catch is a required field left unset (the VRF defrost-EIR curve incident) —
every in-process check ignores it because the SDK models an unset optional
field as simply absent. EnergyPlus is the only thing that calls it what it
is. Sizing-only: this proves the input is VALID, not that annual energy is
right.

The base model needs thermostats/loads, which come from btap.necb's loads
domain — an M5 port. Until then a ONE-TIME Ruby prep step bakes the loaded,
systemless base model to disk (identical input to what the Ruby sweep
rebuilds per system); everything from build_system onward is pure Python.

One system per CHILD PROCESS (like the Ruby's fork): a build or a translate
can abort the interpreter outright, and one bad system must not take the
sweep with it. --check compares the verdict against the committed Ruby one
(btap-modeling/test/fixtures/system_simulation_status.json) — the two
runners must agree system by system.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON_ROOT = HERE.parent
sys.path.insert(0, str(PYTHON_ROOT))  # runnable from anywhere; children too
REPO_ROOT = PYTHON_ROOT.parent
FIXTURES = REPO_ROOT / "btap-modeling" / "test" / "fixtures"
EPW = FIXTURES / "weather" / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw"
DDY = FIXTURES / "weather" / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy"
SEED_OSM = (REPO_ROOT / "btap-modeling" / "lib" / "btap_modeling" / "hvac"
            / "data" / "5ZoneNoHVAC.osm")
RUBY_STATUS = FIXTURES / "system_simulation_status.json"

PREP_RUBY = """
require File.expand_path('btap-audit/lib/btap_audit', ARGV[0])
require File.expand_path('btap-necb/lib/btap_necb/loads', ARGV[0])
model = OpenStudio::Model::Model.load(OpenStudio::Path.new(ARGV[1])).get
model.getSpaceTypes.select { |st| st.spaces.any? }.each do |st|
  st.setStandardsBuildingType('Space Function')
  st.setStandardsSpaceType('Office enclosed > 25 m2')
end
BtapNECB::Loads.apply_loads(model, vintage: '2020', audit: BtapAudit::AuditLog.new)
model.save(OpenStudio::Path.new(ARGV[2]), true)
"""


def prepared_base(work_dir: Path) -> Path:
    """Bake the loaded base model once (Ruby, see module docstring)."""
    base = work_dir / "loaded_base.osm"
    if base.is_file():
        return base
    script = work_dir / "prep.rb"
    script.write_text(PREP_RUBY, encoding="utf-8")
    result = subprocess.run(
        ["ruby", "-ropenstudio", str(script), str(REPO_ROOT),
         str(SEED_OSM), str(base)],
        capture_output=True, text=True)
    if result.returncode != 0 or not base.is_file():
        raise SystemExit(f"base-model prep failed (needs ruby + the Ruby gems):\n{result.stderr[-2000:]}")
    return base


def run_one(name: str, base_osm: str) -> dict:
    """Child-process body: build the system on the base model, sizing-run it."""
    import btap.modeling as modeling
    from btap._compat import sorted_by_name
    from btap._sdk import load_model
    from btap.simulation import runner

    try:
        with tempfile.TemporaryDirectory() as run_dir:
            model = load_model(base_osm)
            modeling.build_system(model, name, sorted_by_name(model.getThermalZones()))
            runner.attach_weather(model, epw=str(EPW), ddy=str(DDY))
            runner.run_energyplus(model, run_dir, sizing_only=True)
            return {"status": "ok"}
    except Exception as e:  # the Ruby rescues StandardError just as broadly
        severe = re.search(r"\*\* Severe {2}\*\*(.+?)(?:\n|\Z)", str(e), re.S)
        detail = severe.group(1).strip() if severe else str(e)
        return {"status": "fail", "error": detail[:220]}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=max((os.cpu_count() or 6) - 4, 2))
    parser.add_argument("--only")
    parser.add_argument("--out", default=None)
    parser.add_argument("--check", action="store_true",
                        help="compare the verdict against the committed Ruby one")
    parser.add_argument("--one", help=argparse.SUPPRESS)  # child mode
    parser.add_argument("--base", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.one:
        print(json.dumps(run_one(args.one, args.base)))
        return 0

    from btap.modeling.hvac import catalog

    systems = [(r["name"], r["family"]) for r in catalog.rows()]
    if args.only:
        systems = [(n, f) for n, f in systems if args.only in n]
    print(f"{len(systems)} systems, {args.jobs} at a time")

    with tempfile.TemporaryDirectory() as work:
        base = prepared_base(Path(work))
        results = []
        pending = list(systems)
        running = {}  # Popen -> (name, family)
        while pending or running:
            while pending and len(running) < args.jobs:
                name, family = pending.pop(0)
                child = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()),
                     "--one", name, "--base", str(base)],
                    cwd=str(PYTHON_ROOT), stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True)
                running[child] = (name, family)
            done = [c for c in running if c.poll() is not None]
            if not done:
                next(iter(running)).wait()
                done = [c for c in running if c.poll() is not None]
            for child in done:
                name, family = running.pop(child)
                raw = (child.stdout.read() or "").strip()
                try:
                    outcome = json.loads(raw.splitlines()[-1])
                except (json.JSONDecodeError, IndexError):
                    outcome = {"status": "crash", "error": f"child exited {child.returncode} with no verdict"}
                outcome.update({"name": name, "family": family})
                results.append(outcome)
                print(".", end="", flush=True)
        print()

    bad = sorted((x for x in results if x["status"] != "ok"),
                 key=lambda x: (str(x["family"]), str(x["name"])))
    print(f"\n{len(results) - len(bad)}/{len(results)} systems produce a simulate-able model")
    if bad:
        print(f"\nFAILING ({len(bad)}):")
        for x in bad:
            print("  %-22s %-62s %s" % (x["family"], x["name"], x.get("error", "")))

    out = Path(args.out) if args.out else Path(tempfile.gettempdir()) / "python_system_simulation_status.json"
    out.write_text(json.dumps(sorted(results, key=lambda x: str(x["name"])), indent=2) + "\n",
                   encoding="utf-8")
    print(f"\nwrote {out}")

    if args.check:
        ruby = {r["name"]: r["status"] for r in json.loads(RUBY_STATUS.read_text(encoding="utf-8"))}
        mine = {r["name"]: r["status"] for r in results}
        disagreements = sorted(n for n in mine if ruby.get(n) != mine[n])
        if disagreements:
            print(f"\nCHECK FAILED — verdicts disagree with the Ruby sweep for: {', '.join(disagreements)}")
            return 1
        print(f"\nCHECK OK — all {len(mine)} verdicts agree with the committed Ruby sweep")

    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
