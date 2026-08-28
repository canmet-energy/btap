#!/usr/bin/env python3
"""Fresh-vs-committed goldens comparator (D-80).

Live Leg C proves TWO things: Python ≡ live oracle (the pytest run over the
fresh export) AND committed goldens ≡ live oracle (THIS check — checksums
only catch hand-edits, never staleness). Both directories are validated
against the request manifest's recursive inventory first, then compared
value-by-value.

  python3 verification/oracle/compare_goldens.py FRESH_DIR [COMMITTED_DIR]

Exit 0: identical within the declared semantic tolerances. Exit 1: any
inventory violation or value difference, each named by group and path.

Tolerances: everything is EXACT (same oracle, same pin, same probe code)
except costing_envelope's tbd_rsi subtree, absorbed at 1e-6 for the
prep-model .osm round trip. Beyond that is a genuine parity finding.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from inventory import validate

HERE = Path(__file__).parent
TBD_RSI_TOL = 1e-6


def tolerance(group, path):
    if group == "costing_envelope" and path.startswith("$/tbd_rsi/"):
        return TBD_RSI_TOL
    return 0.0


def diff_values(group, fresh, committed, path="$"):
    errors = []
    if isinstance(fresh, dict) and isinstance(committed, dict):
        for k in sorted(set(fresh) | set(committed)):
            if k not in fresh:
                errors.append(f"{group}: {path}/{k} only in committed")
            elif k not in committed:
                errors.append(f"{group}: {path}/{k} only in fresh")
            else:
                errors.extend(diff_values(group, fresh[k], committed[k], f"{path}/{k}"))
        return errors
    if isinstance(fresh, list) and isinstance(committed, list):
        if len(fresh) != len(committed):
            return [f"{group}: {path} length {len(fresh)} != {len(committed)}"]
        for i, (f, c) in enumerate(zip(fresh, committed)):
            errors.extend(diff_values(group, f, c, f"{path}[{i}]"))
        return errors
    if isinstance(fresh, (int, float)) and isinstance(committed, (int, float)) \
            and not isinstance(fresh, bool) and not isinstance(committed, bool):
        tol = tolerance(group, path)
        if abs(fresh - committed) > tol:
            return [f"{group}: {path} fresh {fresh!r} != committed {committed!r}"
                    + (f" (tol {tol})" if tol else "")]
        return []
    if fresh != committed:
        return [f"{group}: {path} fresh {fresh!r} != committed {committed!r}"]
    return []


def main(argv):
    if not 2 <= len(argv) <= 3:
        sys.exit(__doc__)
    fresh_dir = Path(argv[1])
    committed_dir = Path(argv[2]) if len(argv) == 3 else HERE / "goldens"
    request = json.loads((HERE / "request_manifest.json").read_text(encoding="utf-8"))

    errors = []
    for group in request["golden_groups"]:
        sides = {}
        for label, base in (("fresh", fresh_dir), ("committed", committed_dir)):
            path = base / f"{group}.json"
            if not path.is_file():
                errors.append(f"{group}: {label} file missing ({path})")
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            errors.extend(f"{group} [{label}]: {e}"
                          for e in validate(data, request["golden_inventory"][group]))
            sides[label] = data
        if len(sides) == 2:
            errors.extend(diff_values(group, sides["fresh"], sides["committed"]))

    if errors:
        print(f"COMMITTED GOLDENS DISAGREE WITH THE LIVE ORACLE "
              f"({len(errors)} differences):")
        for e in errors[:80]:
            print(f"  {e}")
        if len(errors) > 80:
            print(f"  … and {len(errors) - 80} more")
        print("A staleness diff means the committed goldens no longer describe the "
              "pinned oracle: re-export via the goldens dispatch and adjudicate.")
        return 1
    print(f"fresh export ≡ committed goldens across "
          f"{len(request['golden_groups'])} groups (tbd_rsi tol {TBD_RSI_TOL})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
