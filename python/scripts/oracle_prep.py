#!/usr/bin/env python3
"""Build the PREP MODELS for the Leg-C oracle export (D-80).

python-prep / ruby-probe: every oracle-golden input whose preparation chain
contains a btap-gem call is built HERE, by the verified Python
implementation, and handed to the slimmed gem-free Ruby exporter
(verification/oracle/export_goldens.rb) as an .osm plus this manifest.
SDK-only prep (weather attachment, the synthetic daylighting boxes) stays in
the exporter.

Deliberately OUTSIDE the ``btap`` package include: verification
infrastructure must never enlarge the shipped wheel.

  .venv/bin/python scripts/oracle_prep.py --out DIR [--canonical]

``--canonical`` marks the run as feeding a COMMITTED goldens export: it
refuses a dirty source tree (override: --allow-dirty, recorded), and
refuses an --out inside the repository (a canonical export must not see its
own outputs as dirt).

Every .osm entry in prep_manifest.json carries its COMPOSITION CONTRACT:
the Python operations applied, the existing gate that verifies each
operation in isolation, the exact oracle operation the model is input to,
and a structural signature. Provenance identifies the source tree and the
OpenStudio build so the exporter can hard-fail on version skew.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from importlib import resources
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))  # runnable from anywhere

import openstudio  # noqa: E402

from btap._sdk import load_model  # noqa: E402
from btap.audit import AuditLog  # noqa: E402
from btap.necb import envelope, lighting, loads  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OFFICE = ["Space Function", "Office enclosed > 25 m2"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def seed_path():
    return str(resources.files("btap.modeling.hvac") / "data" / "5ZoneNoHVAC.osm")


def first_outdoor_wall_sdk_order(model):
    """The FIRST outdoor wall in SDK ITERATION ORDER — the historical probe
    recipe (Surface 8 on the seed), deliberately NOT sorted-by-name: any
    canonicalization to a sorted selection is its own adjudicated golden
    change (D-80), never a side effect of decoupling."""
    for surface in model.getSurfaces():
        if (surface.outsideBoundaryCondition() == "Outdoors"
                and surface.surfaceType() == "Wall"):
            return surface
    raise RuntimeError("seed has no outdoor wall")


def office_tagged(model):
    mapping = {s.nameString(): OFFICE
               for s in sorted(model.getSpaces(), key=lambda s: s.nameString())}
    loads.assign_space_types(model, mapping, vintage="2020", audit=AuditLog())
    return model


def signature(model):
    return {
        "spaces": len(model.getSpaces()),
        "surfaces": len(model.getSurfaces()),
        "sub_surfaces": len(model.getSubSurfaces()),
        "constructions": len(model.getConstructions()),
        "space_types": len(model.getSpaceTypes()),
        "lights": len(model.getLightss()),
        "floor_area_m2": round(model.getBuilding().floorArea(), 6),
    }


def save(model, out_dir, name):
    path = out_dir / name
    model.save(openstudio.toPath(str(path)), True)
    return path


def build_tbd_rsi(out_dir):
    model = load_model(seed_path())
    envelope.apply_prescriptive(model, vintage="2020", hdd=3890, audit=AuditLog())
    wall = first_outdoor_wall_sdk_order(model)
    wall_name = wall.nameString()
    wall.setWindowToWallRatio(0.3)
    envelope.apply_prescriptive(model, vintage="2020", hdd=3890, audit=AuditLog())
    path = save(model, out_dir, "tbd_rsi.osm")
    return path, {
        "operations": [
            "apply_prescriptive(vintage='2020', hdd=3890)",
            f"setWindowToWallRatio(0.3) on first outdoor wall in SDK "
            f"iteration order = {wall_name!r}",
            "apply_prescriptive(vintage='2020', hdd=3890)",
        ],
        "operation_gates": [
            "python/tests/necb/test_oracle_goldens_envelope.py (prescriptive conductances)",
            "python/tests/necb/test_envelope_prescriptive.py",
        ],
        "oracle_operation": "TBD.rsi over every exterior/ground layered "
                            "construction (costing_envelope.tbd_rsi)",
        "wwr_wall": wall_name,
        "signature": signature(model),
    }


def build_daylighting_controls(out_dir):
    model = office_tagged(load_model(seed_path()))
    wall = first_outdoor_wall_sdk_order(model)
    wall_name = wall.nameString()
    wall.setWindowToWallRatio(0.4)
    path = save(model, out_dir, "daylighting_controls.osm")
    return path, {
        "operations": [
            "assign_space_types(all spaces -> Space Function/Office enclosed "
            "> 25 m2, vintage='2020')",
            f"setWindowToWallRatio(0.4) on first outdoor wall in SDK "
            f"iteration order = {wall_name!r}",
        ],
        "operation_gates": [
            "python/tests/necb/test_loads_apply.py (assign_space_types)",
        ],
        "oracle_operation": "std daylighting-controls placement "
                            "(lighting_daylighting.controls_on_fixture)",
        "wwr_wall": wall_name,
        "signature": signature(model),
    }


def build_lighting_costing(out_dir):
    model = office_tagged(load_model(seed_path()))
    lighting.apply_lights(model, vintage="2020", lights_type="LED",
                          audit=AuditLog())
    model.getBuilding().setStandardsTemplate("NECB2020")
    path = save(model, out_dir, "lighting_costing.osm")
    return path, {
        "operations": [
            "assign_space_types(all spaces -> Space Function/Office enclosed "
            "> 25 m2, vintage='2020')",
            "apply_lights(vintage='2020', lights_type='LED')",
            "Building.setStandardsTemplate('NECB2020')",
        ],
        "operation_gates": [
            "python/tests/necb/test_loads_apply.py (assign_space_types)",
            "python/tests/necb/test_oracle_goldens_lighting.py (apply_lights LED)",
        ],
        "oracle_operation": "BTAP lighting coster total at ONTARIO/TORONTO "
                            "(lighting_costing.led_2020_total)",
        "signature": signature(model),
    }


def build_shw(out_dir):
    model = office_tagged(load_model(seed_path()))
    path = save(model, out_dir, "shw.osm")
    return path, {
        "operations": [
            "assign_space_types(all spaces -> Space Function/Office enclosed "
            "> 25 m2, vintage='2020')",
        ],
        "operation_gates": [
            "python/tests/necb/test_loads_apply.py (assign_space_types)",
        ],
        "oracle_operation": "legacy SWH demand census (shw.swh)",
        "signature": signature(model),
    }


BUILDERS = {
    "tbd_rsi.osm": build_tbd_rsi,
    "daylighting_controls.osm": build_daylighting_controls,
    "lighting_costing.osm": build_lighting_costing,
    "shw.osm": build_shw,
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--canonical", action="store_true",
                    help="this prep feeds a COMMITTED goldens export")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="explicit dev override for --canonical on a dirty tree "
                         "(recorded in the manifest)")
    args = ap.parse_args(argv)

    # Provenance FIRST — dirty state is captured before any output exists.
    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    if args.canonical and dirty and not args.allow_dirty:
        sys.exit("REFUSED: --canonical on a dirty source tree — committed "
                 "goldens must be reproducible from a commit SHA. Commit "
                 "first, or pass --allow-dirty (recorded) for development.")

    out_dir = Path(args.out).resolve()
    if args.canonical and REPO_ROOT in out_dir.parents:
        sys.exit(f"REFUSED: --canonical output {out_dir} is inside the "
                 "repository — a canonical export must not see its own "
                 "outputs as dirt. Use a directory outside the repo.")
    out_dir.mkdir(parents=True, exist_ok=True)

    request_manifest = REPO_ROOT / "verification/oracle/request_manifest.json"
    models = {}
    for name in sorted(BUILDERS):
        path, contract = BUILDERS[name](out_dir)
        contract["sha256"] = sha256(path)
        models[name] = contract
        print(f"  built {name} ({path.stat().st_size} bytes)")

    manifest = {
        "provenance": {
            "commit": commit,
            "dirty": dirty,
            "canonical": args.canonical,
            "allow_dirty_override": bool(args.canonical and dirty),
            "oracle_prep_sha256": sha256(__file__),
            "request_manifest_sha256": sha256(request_manifest),
            "seed_sha256": sha256(seed_path()),
            "seed": "btap.modeling.hvac data 5ZoneNoHVAC.osm",
            "openstudio": {
                "sdk_version": openstudio.openStudioVersion(),
                "build_sha": openstudio.openStudioVersionBuildSHA(),
            },
        },
        "models": models,
    }
    (out_dir / "prep_manifest.json").write_text(
        json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"prep_manifest.json written — commit {commit[:12]}"
          f"{' DIRTY' if dirty else ''}, sdk "
          f"{manifest['provenance']['openstudio']['sdk_version']}")


if __name__ == "__main__":
    main()
