#!/usr/bin/env python3
"""ONE-TIME bootstrap of verification/oracle/request_manifest.json (D-80).

The request manifest is the implementation-INDEPENDENT statement of what the
oracle is asked and what shape the answers must have — so that Python never
defines both the question and the expected result. It is bootstrapped ONCE
(from the committed goldens' structure plus the gem-derived inventories in
dump_bootstrap_inputs.rb's output) with provenance recorded, and thereafter
immutable except by adjudicated update. This script is kept for provenance
and re-adjudication only — nothing in CI runs it.

  ruby verification/oracle/dump_bootstrap_inputs.rb > /tmp/bootstrap_inputs.json
  python3 verification/oracle/bootstrap_request_manifest.py /tmp/bootstrap_inputs.json
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from inventory import build_skeleton

HERE = Path(__file__).parent
GOLDENS = HERE / "goldens"

# Every list path that is NOT compared by index, with its stable identity.
# Everything else (hourly value arrays, schedule rules, id_layers, ...) is
# "ordered": position is the contract.
LIST_RULES = {
    "loads_merged_tables": {
        ("space_types",): ("keyed", ["building_type", "space_type"]),
        ("schedules",): ("keyed", ["name", "day_types"]),
    },
    "lighting_daylighting": {
        ("controls_on_fixture",): ("keyed", ["name"]),
    },
}

GROUPS = [
    "envelope_lookups", "envelope_prescriptive", "envelope_u_table",
    "costing_envelope", "loads_schedules", "loads_apply",
    "loads_merged_tables", "lighting_lights", "lighting_daylighting",
    "lighting_costing", "shw",
]

PYTEST_FILES = [
    "tests/necb/test_oracle_goldens_envelope.py",
    "tests/necb/test_oracle_goldens_loads.py",
    "tests/necb/test_oracle_goldens_shw.py",
    "tests/necb/test_oracle_goldens_lighting.py",
    "tests/costing/test_oracle_goldens_envelope.py",
]


def main():
    inputs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    golden_inventory = {}
    for group in GROUPS:
        data = json.loads((GOLDENS / f"{group}.json").read_text(encoding="utf-8"))
        golden_inventory[group] = build_skeleton(data, LIST_RULES.get(group, {}))

    collected = subprocess.run(
        [".venv/bin/python", "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", *PYTEST_FILES],
        cwd=HERE.parent.parent / "python", capture_output=True, text=True, check=True)
    count = int([ln for ln in collected.stdout.splitlines()
                 if "tests collected" in ln or "test collected" in ln][-1].split()[0])

    manifest = {
        "_doc": "D-80 oracle request manifest — the implementation-independent "
                "statement of every oracle probe request and the recursive shape "
                "of its answer. Immutable except by ADJUDICATED update "
            "(see docs/necb_decisions.md D-80).",
        "schedule_names": inputs["schedule_names"],
        "costing_candidates": inputs["costing_candidates"],
        "golden_groups": GROUPS,
        "golden_inventory": golden_inventory,
        "pytest": {"files": PYTEST_FILES, "collected": count},
        "bootstrap_provenance": {
            "note": "schedule_names and costing_candidates were derived ONCE from "
                    "the gem data (the last gem-derived act); golden_inventory from "
                    "the committed goldens exported at the pinned oracle.",
            "commit": inputs["commit"],
            "source_hashes": inputs["source_hashes"],
            "goldens_manifest_sha256": hashlib.sha256(
                (GOLDENS / "manifest.json").read_bytes()).hexdigest(),
            "review": "docs/d80_retirement_plan_review.md",
        },
    }
    out = HERE / "request_manifest.json"
    out.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes), "
          f"{len(inputs['schedule_names'])} schedules, "
          f"{len(inputs['costing_candidates'])} candidates, "
          f"{len(GROUPS)} groups, {count} tests")


if __name__ == "__main__":
    main()
