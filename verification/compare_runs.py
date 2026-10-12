#!/usr/bin/env python3
"""Leg-B run differ (D-78): compare two btap-compliance run directories'
audit.json + report.json under the normalization/tolerance rules of spec.json.

    python3 verification/compare_runs.py RUN_A RUN_B [--spec verification/spec.json]

Exit 0: equivalent. Exit 1: differences (each printed as a path). Exit 2: usage.

Written in Python deliberately — the (now-complete) port owns this tool, and it works
today against two Ruby runs (the self-test), later Ruby-vs-Python. Stdlib only.

Rules (all data-driven from spec.json):
- keys in `strip_keys` are removed anywhere in report.json (absolute run paths);
- absent key == null (the Ruby writer's `.compact` drops nil-valued keys);
- numbers compare with `float_abs_tol` (per-path overrides in `tolerances`) —
  the writers pre-round the load-bearing fields, so this is belt-and-braces;
- strings are compared by FLOAT-TOKEN NORMALIZATION: embedded numbers compare
  numerically (`string_float_tol`), the non-numeric residue compares exactly —
  neutralizing Ruby Float#to_s vs Python repr() rendering differences;
- audit.json is an ORDERED sequence (pipeline order is the contract).
"""
import argparse
import json
import re
import sys
from pathlib import Path

NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


def load_spec(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def strip_keys(node, keys):
    if isinstance(node, dict):
        return {k: strip_keys(v, keys) for k, v in node.items() if k not in keys}
    if isinstance(node, list):
        return [strip_keys(v, keys) for v in node]
    return node


def tol_for(path, spec):
    for rule in spec.get("tolerances", []):
        if re.search(rule["path_regex"], path):
            return float(rule["abs"])
    return float(spec.get("float_abs_tol", 1e-9))


def numbers_equal(a, b, tol):
    return abs(float(a) - float(b)) <= tol


def exact_string(path, spec):
    """Is this path an identifier, exempt from the string-float tolerance?"""
    for pattern in spec.get("exact_string_paths", []):
        if re.search(pattern, path):
            return True
    return False


#: A dotted run of THREE or more components — `8.4.5.2`, `3.11.0` — which is
#: an identifier, never a measurement. A measured float has at most one dot.
DOTTED_ID_RE = re.compile(r"\d+(?:\.\d+){2,}")


def strings_equal(a, b, spec):
    """Equal as prose, with a float tolerance for the numbers inside it.

    The tolerance exists so an audit line reading "worst 58.750000" matches a
    re-run's "58.7500001". It is applied to NUMERIC TOKENS, and that made
    `4.1` and `4.10` the same number — so `8.4.4.1.(2)` and `8.4.4.10.(2)`,
    two DIFFERENT NECB articles, compared equal (Fable, `228`).

    `spec.exact_string_paths` fixed the citation AXES, where the whole string
    is an identifier. It did not fix a citation quoted INSIDE prose, and the
    frozen audits are full of those: `evidence` carries "Article 8.4.5.2.
    states FHeatPLC as a fuel-INPUT ratio", `boiler_count_subclause` carries
    "NOT ESTABLISHED: 8.4.4.9.(6) bands the requirement". Those keys need the
    tolerance for their measured floats and must not have it for their
    citations.

    So the discriminator is the TOKEN, not the field: a dotted run of three
    or more components is an identifier and is compared textually; one dot or
    none is a measurement and keeps the tolerance. `58.750000` is a
    measurement, `8.4.5.2` is not, and no field has to choose between them.
    """
    if a == b:
        return True
    # Identifiers first, textually, before any numeric reading of them.
    if DOTTED_ID_RE.findall(a) != DOTTED_ID_RE.findall(b):
        return False
    a, b = DOTTED_ID_RE.sub("\x00", a), DOTTED_ID_RE.sub("\x00", b)
    tol = float(spec.get("string_float_tol", 1e-6))
    na, nb = NUM_RE.findall(a), NUM_RE.findall(b)
    if len(na) != len(nb):
        return False
    if NUM_RE.sub("", a) != NUM_RE.sub("", b):
        return False
    return all(numbers_equal(x, y, tol) for x, y in zip(na, nb))


def diff(a, b, spec, path, out):
    if len(out) > 200:  # cap the flood; the first diffs are the story
        return
    null = (None,)
    if isinstance(a, dict) or isinstance(b, dict):
        if not (isinstance(a, dict) and isinstance(b, dict)):
            out.append(f"{path}: type {type(a).__name__} vs {type(b).__name__}")
            return
        for key in sorted(set(a) | set(b)):
            va = a.get(key)
            vb = b.get(key)
            if spec.get("absent_equals_null", True) and (
                (key not in a and vb is None) or (key not in b and va is None)
            ):
                continue
            diff(va, vb, spec, f"{path}/{key}", out)
        return
    if isinstance(a, list) or isinstance(b, list):
        if not (isinstance(a, list) and isinstance(b, list)):
            out.append(f"{path}: type {type(a).__name__} vs {type(b).__name__}")
            return
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} vs {len(b)}")
        for i, (va, vb) in enumerate(zip(a, b)):
            diff(va, vb, spec, f"{path}[{i}]", out)
        return
    if isinstance(a, bool) or isinstance(b, bool):
        if a is not b:
            out.append(f"{path}: {a!r} vs {b!r}")
        return
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not numbers_equal(a, b, tol_for(path, spec)):
            out.append(f"{path}: {a!r} vs {b!r}")
        return
    if isinstance(a, str) and isinstance(b, str):
        if exact_string(path, spec):
            # An IDENTIFIER, compared byte-for-byte. `strings_equal`
            # tokenises numbers so audit prose can carry a formatted float,
            # and a citation is not prose: `8.4.4.1.(2)` and
            # `8.4.4.10.(2)` tokenise to 4.1 and 4.10, numerically equal
            # with identical skeletons, so two DIFFERENT articles compared
            # the same (Fable, `228`).
            if a != b:
                out.append(f"{path}: {a!r} vs {b!r}")
            return
        if not strings_equal(a, b, spec):
            out.append(f"{path}: {a!r} vs {b!r}")
        return
    if a is not None or b is not None:
        if a != b:
            out.append(f"{path}: {a!r} vs {b!r}")


def compare_file(run_a, run_b, name, spec, out):
    pa, pb = Path(run_a) / name, Path(run_b) / name
    if pa.exists() != pb.exists():
        out.append(f"{name}: present in one run only ({pa.exists()} vs {pb.exists()})")
        return
    if not pa.exists():
        return
    with open(pa, encoding="utf-8") as f:
        a = json.load(f)
    with open(pb, encoding="utf-8") as f:
        b = json.load(f)
    keys = spec.get("strip_keys", [])
    diff(strip_keys(a, keys), strip_keys(b, keys), spec, name, out)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_a")
    parser.add_argument("run_b")
    parser.add_argument("--spec", default=str(Path(__file__).parent / "spec.json"))
    args = parser.parse_args(argv)

    spec = load_spec(args.spec)
    out = []
    for name in spec.get("files", ["audit.json", "report.json"]):
        compare_file(args.run_a, args.run_b, name, spec, out)

    if out:
        print(f"DIFF {args.run_a} vs {args.run_b}: {len(out)} difference(s)")
        for line in out[:200]:
            print(f"  {line}")
        return 1
    print(f"EQUIVALENT {args.run_a} vs {args.run_b}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
