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
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PYTHON_ROOT.parent


def companion_expected() -> bool:
    """Is canmet-energyplus a hard dependency on THIS platform?

    Computed from the platform, mirroring the marker in pyproject.toml —
    never from "did the import work", because gating a check on the thing it
    is testing is how a check silently becomes a no-op. (The companion checks
    below used to return early unless BTAP_COMPANION_WHEELHOUSE was set, which
    printed "ok" for work never done once the wheelhouse went away.)
    """
    return (sys.platform == "win32"
            or (sys.platform.startswith("linux")
                and platform.machine() == "x86_64"))


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

    print(f"companion expected on this platform: {companion_expected()} "
          f"({sys.platform}/{platform.machine()})")

    def companion_engine_resolves():
        # R5 (D-83): the installed btap wheel must resolve to the installed
        # companion's binary with no engine-resolution overrides.
        if not companion_expected():
            print("    (skipped: the marker excludes this platform)")
            return
        import canmet_energyplus  # noqa: I001
        from btap.simulation import engine

        companion_installed = Path(canmet_energyplus.__file__).resolve()
        if REPO_ROOT in companion_installed.parents:
            raise AssertionError(
                f"the SOURCE TREE shadowed the companion wheel ({companion_installed})")
        print(f"canmet-energyplus imported from: {companion_installed.parent}")

        os.environ.pop("BTAP_ENERGYPLUS", None)
        os.environ.pop("BTAP_ENERGYPLUS_ARCHIVE", None)
        engine._reset_memo()
        resolved = engine.ensure_energyplus()
        expected = canmet_energyplus.binary_path()
        assert str(resolved) == str(expected), (
            f"engine resolved {resolved}, not the companion {expected}")
    check("the companion engine resolves with no engine overrides (R5)",
          companion_engine_resolves)

    def companion_authority_agrees():
        # Two repositories now carry EnergyPlus identity: canmet-energyplus
        # owns which upstream build is REPACKAGED, btap owns the version it
        # is compatible with plus the assets its download rung fetches for
        # platforms the wheel does not cover. That duplication is deliberate,
        # so it has to be CHECKED — engine._verify_version compares only the
        # version string and would not notice a different asset or build.
        # This is the only environment in btap's CI with a genuinely
        # installed companion, so the check belongs here and nowhere else.
        if not companion_expected():
            print("    (skipped: the marker excludes this platform)")
            return
        import json
        from importlib.metadata import version as dist_version

        import canmet_energyplus

        from btap.simulation import engine

        assert canmet_energyplus.ENERGYPLUS_VERSION == engine.PINNED_VERSION, (
            f"companion carries E+ {canmet_energyplus.ENERGYPLUS_VERSION}, "
            f"btap pins {engine.PINNED_VERSION}")
        assert canmet_energyplus.BUILD_SHA == engine._BUILD_SHA, (
            f"companion built from {canmet_energyplus.BUILD_SHA}, "
            f"btap pins {engine._BUILD_SHA}")

        # The distribution version is metadata, NOT ENERGYPLUS_VERSION (which
        # is the three-part engine version by design).
        installed_dist = dist_version("canmet-energyplus")
        print(f"    canmet-energyplus {installed_dist}, engine "
              f"{canmet_energyplus.ENERGYPLUS_VERSION}, build "
              f"{canmet_energyplus.BUILD_SHA}")

        prov = json.loads(
            (Path(canmet_energyplus.__file__).parent / "PROVENANCE.json")
            .read_text(encoding="utf-8"))
        key = ("windows", "amd64") if sys.platform == "win32" else ("linux", "x86_64")
        _, btap_digest = engine._ASSETS[key]
        companion_digest = prov["source_asset"]["sha256"]
        assert companion_digest == btap_digest, (
            f"the companion repackaged an asset btap does not know: "
            f"{companion_digest} != {btap_digest}")
        print(f"    both repositories name the same upstream asset "
              f"({companion_digest[:16]}…)")
    check("the two repositories agree on the EnergyPlus identity (R5)",
          companion_authority_agrees)

    def installed_pair_sizes():
        # The release premise, exercised as users receive it: installed btap
        # drives the installed companion from outside the checkout. Inputs may
        # be fixtures; neither implementation is allowed to resolve from it.
        if not companion_expected():
            print("    (skipped: the marker excludes this platform)")
            return
        import canmet_energyplus

        venv_root = Path(sys.prefix).resolve()
        for package, module_path in (
                ("btap", Path(btap.__file__).resolve()),
                ("canmet-energyplus", Path(canmet_energyplus.__file__).resolve())):
            if not module_path.is_relative_to(venv_root):
                raise AssertionError(
                    f"{package} imported from {module_path}, outside scratch venv {venv_root}")
        exe = Path(sys.executable).parent / "btap-compliance"
        with tempfile.TemporaryDirectory(prefix="btap-installed-sizing-") as tmp:
            tmp = Path(tmp)
            run_dir = tmp / "run"
            env = {**os.environ, "XDG_CACHE_HOME": str(tmp / "cache")}
            for name in ("PYTHONPATH", "BTAP_ENERGYPLUS", "BTAP_ENERGYPLUS_ARCHIVE",
                         "BTAP_COMPANION_WHEELHOUSE"):
                env.pop(name, None)
            proc = subprocess.run(
                [str(exe),
                 str(modeling.hvac.catalog_report.FIXTURE),
                 "--simulate", "sizing",
                 "--epw", str(PYTHON_ROOT / "tests/fixtures/weather/"
                               "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw"),
                 "--hdd", "3890", "--storeys", "1", "--no-report", "--quiet",
                 "--space-type", "Space Function/Office enclosed > 25 m2",
                 "-o", str(run_dir)],
                cwd=str(tmp), env=env, capture_output=True, text=True, timeout=1200)
            assert proc.returncode == 6, (
                f"installed-pair sizing exited {proc.returncode}, expected 6 "
                f"(no determination): {proc.stderr[-1200:]}")
            assert (run_dir / "audit.json").is_file(), (
                "installed-pair sizing produced no audit.json")
            for name in ("proposed_sizing", "reference_sizing"):
                energyplus_run = run_dir / name / "run"
                sql = energyplus_run / "eplusout.sql"
                err = energyplus_run / "eplusout.err"
                assert sql.is_file() and sql.stat().st_size > 0, (
                    f"installed-pair {name} produced no non-empty eplusout.sql")
                assert err.is_file() and "EnergyPlus Completed Successfully" in (
                    err.read_text(encoding="utf-8", errors="replace")), (
                    f"installed-pair {name} did not complete EnergyPlus successfully")
            # The download rung must NOT have been the engine source: the
            # isolated cache stays EMPTY, proving the companion (already
            # asserted venv-resident) supplied EnergyPlus — no provisioning
            # occurred (review of the merged gate: closes the theoretical
            # absent-companion-falls-to-download false-green).
            provisioned = list((tmp / "cache").rglob("energyplus*"))
            assert not provisioned, (
                f"the isolated cache contains a provisioned engine "
                f"({provisioned[:2]}) — the run did NOT use the companion")
            print(f"installed-pair sizing used btap from {Path(btap.__file__).parent}")
            print("installed-pair sizing used companion from "
                  f"{Path(canmet_energyplus.__file__).parent}")
            print("installed-pair REAL sizing completed with isolated cache "
                "and no engine-resolution overrides")
    check("installed btap + installed companion complete real sizing (R5)",
          installed_pair_sizes)

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
        # The companion hard dep (R5, D-83) resolves from PyPI like any
        # other dependency now that canmet-energyplus is published from its
        # own repository; H-6 below proves the dependency is real by
        # withholding ONLY that package from an isolated index.
        # H-6, done HONESTLY (review round 4: an empty index fails for
        # every dependency, proving nothing about the companion). Build a
        # wheelhouse holding EVERY dependency EXCEPT the companion; the
        # failure must NAME the companion requirement. This no longer needs
        # a locally built companion — the dependency now comes from PyPI
        # like any other — but it DOES need the platform guard: where the
        # marker excludes the companion, resolution legitimately succeeds
        # and asserting failure would be a false alarm.
        if companion_expected():
            with tempfile.TemporaryDirectory(prefix="h6-") as deps_dir:
                subprocess.run(
                    [str(pip), "download", "-q", "-d", deps_dir,
                     "openstudio~=3.11.0"], check=True)
                h6 = subprocess.run(
                    [str(pip), "install", "--dry-run", "--no-index",
                     "--find-links", deps_dir, str(wheel)],
                    capture_output=True, text=True)
                blame = (h6.stdout + h6.stderr)
                if h6.returncode == 0:
                    print("H-6 FAILED: btap resolved without the companion")
                    return 1
                if "canmet-energyplus" not in blame:
                    print("H-6 FAILED: resolution failed but did NOT name "
                          f"canmet-energyplus:\n{blame[-800:]}")
                    return 1
                print("H-6 ok: with every dep present EXCEPT the companion, "
                      "resolution fails NAMING canmet-energyplus")
        else:
            print("H-6 skipped: the marker excludes the companion here")
        # Everything resolves from PyPI now — canmet-tbd 3.5.2 (which pins
        # py-topolys==0.1.0 transitively) and canmet-energyplus 25.2.0.2 are
        # published, so this install is EXACTLY what a user's `pip install
        # canmet-btap[tbd]` does. The tag-sourced interim installs are gone.
        subprocess.run([str(pip), "install", "-q",
                        "openstudio~=3.11.0", f"{wheel}[tbd]"], check=True)

        # CWD outside the repo: a local btap/ must not be importable.
        print(f"running checks from {work_dir} (outside the checkout)\n")
        return subprocess.run(
            [str(python), str(Path(__file__).resolve()), "--run-checks"],
            cwd=str(work_dir)).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
