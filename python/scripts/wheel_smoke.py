#!/usr/bin/env python3
"""Distribution-integrity gate: exercise btap as an INSTALLED WHEEL.

    python3 scripts/wheel_smoke.py            # build, install clean, smoke
    python3 scripts/wheel_smoke.py --run-checks   # (internal) the checks only

Why this exists: the test suite runs against the source checkout, where every
data file is present because the repository is present. A wheel is a different
artifact — setuptools ships only .py unless told otherwise — and the gap was
not hypothetical. `catalog_html()` resolved its seed model by walking OUTSIDE
the installed package, so from a wheel it silently produced a 1 MB document
with 97 'diagram unavailable' cards instead of a catalog. Nothing in CI could
have caught that, because nothing in CI ever installed the wheel.

The checks run in a throwaway venv whose CWD is OUTSIDE the repository, so a
local `btap/` directory cannot shadow the installed package — verified
explicitly rather than assumed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PYTHON_ROOT.parent


def run_checks() -> int:
    """Executed INSIDE the clean venv, with CWD outside the repo."""
    import btap
    import btap.modeling as modeling

    failures = []

    def check(label, fn):
        try:
            fn()
            print(f"  ok    {label}")
        except Exception as e:  # noqa: BLE001 - the gate reports, never crashes
            failures.append(f"{label}: {type(e).__name__}: {e}")
            print(f"  FAIL  {label}: {type(e).__name__}: {e}")

    installed = Path(btap.__file__).resolve()
    print(f"btap imported from: {installed.parent}")

    def not_shadowed():
        if REPO_ROOT in installed.parents:
            raise AssertionError(
                f"the SOURCE TREE shadowed the wheel ({installed}) — this gate proves "
                "nothing unless it runs outside the checkout")
    check("imported from the installed wheel, not the source tree", not_shadowed)

    def data_loads():
        from btap.necb import loads
        rules = loads.rules("2020")
        assert rules, "necb loads rules are empty"
        from btap.modeling.hvac import catalog
        rows = catalog.rows()
        assert len(rows) == 97, f"catalog has {len(rows)} systems, expected 97"
    check("packaged data loads (necb rules + the 97-system catalog)", data_loads)

    def costing_tables():
        from btap.costing.envelope.database import Database
        db = Database()
        assert db.materials_opaque, "costing envelope tables are empty"
        assert db.cost_record("070026"), "priced placeholder table not resolvable"
    check("packaged costing tables resolve", costing_tables)

    def catalog_html_is_real():
        html = modeling.catalog_html()
        unavailable = html.count("Diagram unavailable")
        svgs = html.count("<svg")
        if unavailable or svgs < 100:
            raise AssertionError(
                f"degraded catalog: {unavailable} 'Diagram unavailable', {svgs} svgs — "
                "the seed model did not resolve from the installed package")
    check("catalog_html() renders real diagrams (the regression this gate exists for)",
          catalog_html_is_real)

    def bad_seed_is_loud():
        try:
            modeling.catalog_html(fixture="/nonexistent/seed.osm")
        except ValueError:
            return
        raise AssertionError("an unreadable seed must RAISE, not degrade silently")
    check("an unreadable seed model fails loudly", bad_seed_is_loud)

    def domain_operation():
        from btap._sdk import load_model
        from btap.audit import AuditLog
        from btap.necb import loads
        model = load_model(modeling.hvac.catalog_report.FIXTURE)
        for st in model.getSpaceTypes():
            if st.spaces():
                st.setStandardsBuildingType("Space Function")
                st.setStandardsSpaceType("Office enclosed > 25 m2")
        audit = AuditLog()
        loads.apply_loads(model, vintage="2020", audit=audit)
        assert model.getPeoples(), "apply_loads produced no occupancy"
        assert audit.entries, "apply_loads wrote nothing to the audit"
    check("a real domain operation runs end to end (necb loads on the packaged seed)",
          domain_operation)

    def tbd_engine_operates():
        # M7 (D-79 Option A): the pinned py-tbd engine — installed via the
        # [tbd] extra — must import with the verified 3.5.2-compat identity
        # and run a REAL process operation on the packaged seed model.
        import tbd

        from btap.necb.envelope import thermal_bridging as tb
        assert tbd.VERSION == tb.PINNED_TBD_VERSION, (
            f"engine {tbd.VERSION} != pinned {tb.PINNED_TBD_VERSION}")
        assert tbd.UPSTREAM_SHA == tb.PINNED_TBD_UPSTREAM_SHA, "upstream SHA drift"
        from btap._sdk import load_model
        model = load_model(modeling.hvac.catalog_report.FIXTURE)
        tbd.oslg.clean()
        result = tbd.process(model, {"option": "efficient (BETBG)"})
        surfaces = result.get("surfaces") or {}
        derated = sum(1 for s in surfaces.values()
                      if abs(float(s.get("heatloss") or 0.0)) > 1e-9)
        assert derated > 0, "tbd.process derated nothing on the seed model"
    check("the pinned py-tbd engine installs and processes (M7)", tbd_engine_operates)

    def console_script_answers():
        # M6: the wheel declares the btap-compliance entry point. It must be
        # on the venv's bin path and --help must exit 0 — a broken entry
        # point is invisible to every in-process test.
        exe = Path(sys.executable).parent / "btap-compliance"
        if not exe.exists():
            raise AssertionError(f"console script not installed: {exe}")
        proc = subprocess.run([str(exe), "--help"], capture_output=True,
                              text=True, timeout=120)
        assert proc.returncode == 0, f"--help exited {proc.returncode}: {proc.stderr[-500:]}"
        assert "--epw" in proc.stdout, "help does not document --epw"
    check("the btap-compliance console script answers --help", console_script_answers)

    if failures:
        print(f"\nWHEEL SMOKE FAILED ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nWHEEL SMOKE OK — the installed distribution is self-sufficient")
    return 0


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-checks", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.run_checks:
        return run_checks()

    with tempfile.TemporaryDirectory(prefix="btap-wheel-gate-") as work:
        work_dir = Path(work)
        print("building the wheel...")
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(work_dir),
                        str(PYTHON_ROOT)], check=True, stdout=subprocess.DEVNULL)
        wheel = next(work_dir.glob("*.whl"))
        print(f"built {wheel.name}")

        venv = work_dir / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        pip, python = venv / "bin" / "pip", venv / "bin" / "python"
        print("installing into a clean venv...")
        # [tbd] pulls the PINNED py-tbd (git SHA, py-topolys pinned
        # transitively) — the M7 engine must install and operate from the
        # DISTRIBUTION, not just the checkout: a broken git pin, missing
        # package data or import-resolution failure in the optional extra is
        # invisible to every source-tree test.
        subprocess.run([str(pip), "install", "-q", "openstudio~=3.11.0",
                        f"{wheel}[tbd]"], check=True)

        # CWD outside the repo: a local btap/ must not be importable.
        print(f"running checks from {work_dir} (outside the checkout)\n")
        return subprocess.run(
            [str(python), str(Path(__file__).resolve()), "--run-checks"],
            cwd=str(work_dir)).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
