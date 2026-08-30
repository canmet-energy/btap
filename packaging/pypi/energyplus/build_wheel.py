#!/usr/bin/env python3
"""Build the btap-energyplus companion wheel(s) (R5, D-83).

    python3 packaging/pypi/energyplus/build_wheel.py \
        --platform {linux,windows,all} --iteration 1 --outdir dist/

Contract (the reviewed D-83 build discipline):
1. Download the official NREL release asset for the target platform and
   sha256-VERIFY IT BEFORE ANY MODIFICATION (the digests live in
   btap.simulation.engine._ASSETS — one home for the pins).
2. Extract; PRUNE-LIST (never keep-list, so unknown-but-needed files
   survive): remove ``python_lib/`` and ``pyenergyplus/`` only — btap
   drives EnergyPlus purely as a subprocess and ships no PythonPlugin
   runtime. libpython/pythonXY.dll are NEVER pruned: they are verified
   NEEDED dependencies of the energyplus binary itself, and the builder
   re-checks that linkage every run and aborts if it ever flips.
3. KEEP-LIST assertion: the binary, libenergyplusapi, libpython,
   Energy+.idd, Energy+.schema.epJSON, ExpandObjects, and (Windows) the
   runtime DLL set must all be present, or the build aborts.
4. Write PROVENANCE.json: source asset + digest, prune manifest, keep
   manifest with per-file sha256, builder git SHA, licenses note.
5. Write the wheel directly with zipfile: exec bits recorded in
   external_attr for the POSIX wheel; tags py3-none-{platform}. The
   manylinux tag is EARNED downstream: CI runs ``auditwheel show`` on
   the built Linux wheel and the reported tag must equal the tag baked
   here — a mismatch fails the build (never a mislabeled wheel).
6. Build-side validation (Linux artifact, on this host): scratch venv,
   BTAP_ENERGYPLUS unset, ensure_energyplus() must return the companion
   binary and a REAL sizing simulation must succeed. The Windows
   artifact is validated on windows-latest in publish.yml by exact
   digest (PE closure + real sizing) — Linux cannot execute it.
"""

import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from btap.simulation.engine import (
    _ASSETS,
    _BUILD_SHA,
    _DOWNLOAD_BASE,
    PINNED_VERSION,
)

DIST_NAME = "btap_energyplus"
PRUNE = ("python_lib", "pyenergyplus")
#: Tags: the Linux tag is asserted against `auditwheel show` in CI.
PLATFORMS = {
    "linux": {"asset_key": ("linux", "x86_64"),
              "wheel_tag": "py3-none-manylinux_2_35_x86_64",
              "binary": "energyplus", "libpython_glob": "libpython*"},
    "windows": {"asset_key": ("windows", "amd64"),
                "wheel_tag": "py3-none-win_amd64",
                "binary": "energyplus.exe", "libpython_glob": "python3*.dll"},
}
KEEP_REQUIRED = {
    "linux": ["energyplus", "libenergyplusapi.so*", "libeplus-python*",
              "Energy+.idd", "Energy+.schema.epJSON", "ExpandObjects"],
    "windows": ["energyplus.exe", "energyplusapi.dll", "python3*.dll",
                "Energy+.idd", "Energy+.schema.epJSON", "ExpandObjects.exe",
                "vcruntime*.dll"],
}
EXECUTABLE_PATTERNS = ("energyplus", "ExpandObjects", ".so")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def die(msg):
    sys.exit(f"BUILD REFUSED: {msg}")


def download_verified(platform_key, workdir):
    asset, expected = _ASSETS[platform_key]
    url = f"{_DOWNLOAD_BASE}/v{PINNED_VERSION}/{asset}"
    dest = workdir / asset
    if not dest.exists():
        print(f"downloading {url}", flush=True)
        urllib.request.urlretrieve(url, dest)
    actual = sha256(dest)
    if actual != expected:
        die(f"{asset}: sha256 {actual} != pinned {expected} — the official "
            "asset does not match btap's pin; nothing was modified or built")
    print(f"verified {asset} ({dest.stat().st_size // (1 << 20)} MB)")
    return dest


def extract(archive, workdir):
    out = workdir / "extracted"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(out)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(out, filter="data")
    roots = [p for p in out.rglob("*")
             if p.is_file() and p.name in ("energyplus", "energyplus.exe")]
    if not roots:
        die("no energyplus binary found in the extracted asset")
    return roots[0].parent


MANYLINUX_ALLOWLIST = {
    "libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1",
    "libgcc_s.so.1", "libstdc++.so.6", "ld-linux-x86-64.so.2", "libutil.so.1",
    "libcrypt.so.1", "libnsl.so.1", "libX11.so.6", "libXext.so.6",
    "libXrender.so.1", "libICE.so.6", "libSM.so.6", "libGL.so.1",
    "libgobject-2.0.so.0", "libgthread-2.0.so.0", "libglib-2.0.so.0",
    "libz.so.1", "libexpat.so.1",
}


def patch_libpython(eplus_root):
    """Rename the bundled libpython and patch DT_NEEDED (linux only).

    PEP 600 forbids manylinux wheels from linking libpythonX.Y — the
    policy targets HOST-python dependence, but EnergyPlus links its own
    BUNDLED copy (for the PythonPlugin API btap never uses). Renaming
    the bundled file and patching the two NEEDED entries makes the
    non-dependence on host python explicit and mechanical; auditwheel
    then certifies the manylinux tag (verified empirically: the patched
    binary runs and `auditwheel show` grades manylinux_2_35_x86_64).
    """
    libs = list(eplus_root.glob("libpython*.so*"))
    real = [p for p in libs if not p.is_symlink()]
    if not real:
        return None
    src = real[0]
    renamed = src.with_name(src.name.replace("libpython", "libeplus-python"))
    shutil.move(src, renamed)
    for stale in [p for p in libs if p.is_symlink()]:
        stale.unlink()
    venv_patchelf = Path(sys.executable).parent / "patchelf"
    patchelf = (str(venv_patchelf) if venv_patchelf.exists()
                else shutil.which("patchelf")) or die(
        "patchelf is required to build the linux companion (pip install "
        "patchelf)")
    for target in ("energyplus-*", "libenergyplusapi.so*"):
        for f in eplus_root.glob(target):
            if f.is_symlink() or not f.is_file():
                continue
            subprocess.run([patchelf, "--replace-needed", src.name,
                            renamed.name, str(f)], check=True)
    return {"renamed": src.name, "to": renamed.name,
            "patched": ["energyplus", "libenergyplusapi"]}


def elf_closure(eplus_root):
    """RECURSIVE dependency closure over every shipped ELF: each NEEDED
    entry must resolve INSIDE the payload or be on the manylinux
    allowlist. ldd failures, 'not found', and host-only resolution all
    abort — a one-machine green must never stand in for closure."""
    payload_names = {f.name for f in eplus_root.iterdir() if f.is_file()}
    problems = []
    elves = [f for f in eplus_root.iterdir() if f.is_file()
             and (f.suffix in ("", ".so") or ".so." in f.name)
             and f.read_bytes()[:4] == b"\x7fELF"]
    if not elves:
        die("no ELF files found in the payload — wrong tree?")
    for elf in elves:
        out = subprocess.run(["readelf", "-d", str(elf)],
                             capture_output=True, text=True, check=False)
        if out.returncode != 0:
            problems.append(f"{elf.name}: readelf failed")
            continue
        needed = re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]",
                            out.stdout)
        runpath = re.findall(r"\((?:RUNPATH|RPATH)\)[^\[]*\[([^\]]+)\]",
                            out.stdout)
        for lib in needed:
            if lib in payload_names:
                if not runpath or "$ORIGIN" not in runpath[0]:
                    problems.append(
                        f"{elf.name}: needs bundled {lib} but has no "
                        f"$ORIGIN RUNPATH ({runpath})")
            elif lib in MANYLINUX_ALLOWLIST:
                pass
            elif lib.startswith("libpython"):
                problems.append(
                    f"{elf.name}: still links HOST {lib} — the patchelf "
                    "step failed")
            else:
                problems.append(
                    f"{elf.name}: non-allowlisted external {lib} — would "
                    "resolve from the build host, not the wheel")
    if problems:
        die("ELF closure failed:\n  " + "\n  ".join(problems[:20]))
    print(f"ELF closure ok: {len(elves)} shipped ELFs, every NEEDED "
          "resolved in-payload (with $ORIGIN) or allowlisted")


def prune(eplus_root):
    removed = []
    for name in PRUNE:
        target = eplus_root / name
        if target.exists():
            size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
            removed.append({"path": name, "bytes": size})
            shutil.rmtree(target)
    return removed


def assert_keep(eplus_root, plat):
    missing = [pat for pat in KEEP_REQUIRED[plat]
               if not list(eplus_root.glob(pat))]
    if missing:
        die(f"keep-list assertion failed — missing {missing}")


def provenance(plat, asset, removed, eplus_root, version):
    keep = {}
    for f in sorted(eplus_root.rglob("*")):
        if f.is_file():
            keep[str(f.relative_to(eplus_root))] = sha256(f)
    builder_sha = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False).stdout.strip()
    return {
        "energyplus_version": PINNED_VERSION,
        "energyplus_build_sha": _BUILD_SHA,
        "distribution_version": version,
        "platform": plat,
        "source_asset": {"name": asset.name, "sha256": sha256(asset),
                        "url": f"{_DOWNLOAD_BASE}/v{PINNED_VERSION}/{asset.name}"},
        "pruned": removed,
        "kept_files": keep,
        "builder_commit": builder_sha,
        "note": "PythonPlugin runtime removed (python_lib, pyenergyplus): "
                "btap drives EnergyPlus purely as a subprocess. libpython "
                "ships — it is a NEEDED link-time dependency of the "
                "energyplus binary. Runtime integrity = pip's RECORD "
                "hashes. EnergyPlus is distributed under its own BSD-style "
                "license (payload/licenses); this packaging adds no code "
                "to it.",
    }


def wheel_bytes(plat_cfg, version, eplus_root, prov):
    """Assemble the wheel in memory-ish (spooled to disk via zipfile)."""
    tag = plat_cfg["wheel_tag"]
    name_ver = f"{DIST_NAME}-{version}"
    dist_info = f"{name_ver}.dist-info"
    records = []

    def arcname_mode(rel):
        base = rel.split("/")[-1]
        if any(p in base for p in EXECUTABLE_PATTERNS):
            return 0o100755
        return 0o100644

    fd, buf_name = tempfile.mkstemp(suffix=".whl")
    import os as _os
    _os.close(fd)
    with zipfile.ZipFile(buf_name, "w", zipfile.ZIP_DEFLATED) as zf:
        def add(arc, data, mode=0o100644):
            info = zipfile.ZipInfo(arc)
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
            digest = base64.urlsafe_b64encode(
                hashlib.sha256(data).digest()).rstrip(b"=").decode()
            records.append(f"{arc},sha256={digest},{len(data)}")

        add(f"{DIST_NAME}/__init__.py",
            (HERE / "src" / DIST_NAME / "__init__.py").read_bytes())
        add(f"{DIST_NAME}/PROVENANCE.json",
            json.dumps(prov, indent=1).encode())
        for f in sorted(eplus_root.rglob("*")):
            if not f.is_file():
                continue
            rel = f"{DIST_NAME}/payload/{f.relative_to(eplus_root)}"
            add(rel, f.read_bytes(), arcname_mode(rel))

        metadata = "\n".join([
            "Metadata-Version: 2.1",
            "Name: btap-energyplus",
            f"Version: {version}",
            "Summary: The pinned EnergyPlus engine for btap, as package data",
            "License: BSD-3-Clause AND LGPL-3.0-or-later",
            "Requires-Python: >=3.11",
            "",
            ("The btap companion engine wheel. See PROVENANCE.json "
             "inside the package for the full build provenance."), ""])
        add(f"{dist_info}/METADATA", metadata.encode())
        wheel_meta = "\n".join([
            "Wheel-Version: 1.0",
            "Generator: btap-build-wheel",
            "Root-Is-Purelib: false",
            f"Tag: {tag}", ""])
        add(f"{dist_info}/WHEEL", wheel_meta.encode())
        record_arc = f"{dist_info}/RECORD"
        records.append(f"{record_arc},,")
        info = zipfile.ZipInfo(record_arc)
        info.external_attr = 0o100644 << 16
        zf.writestr(info, "\n".join(records) + "\n")
    return Path(buf_name), f"{name_ver}-{tag}.whl"


def build_platform(plat, version, outdir, workdir):
    cfg = PLATFORMS[plat]
    asset = download_verified(cfg["asset_key"], workdir)
    eplus_root = extract(asset, workdir / plat)
    removed = prune(eplus_root)
    patch_note = None
    if plat == "linux":
        patch_note = patch_libpython(eplus_root)
        elf_closure(eplus_root)
    assert_keep(eplus_root, plat)
    prov = provenance(plat, asset, removed, eplus_root, version)
    if patch_note:
        prov["libpython_patch"] = patch_note
    tmp, final_name = wheel_bytes(cfg, version, eplus_root, prov)
    outdir.mkdir(parents=True, exist_ok=True)
    dest = outdir / final_name
    shutil.move(str(tmp), dest)
    mb = dest.stat().st_size / (1 << 20)
    print(f"built {dest.name} ({mb:.1f} MB)"
          + ("  ⚠ >=95 MB — PyPI size-exemption territory" if mb >= 95 else ""))
    if plat == "linux":
        audit_wheel_gate(dest, cfg["wheel_tag"])
    return dest


def audit_wheel_gate(wheel, baked_tag):
    """The tag is EARNED: `auditwheel show` on the COMPLETED wheel must
    grade exactly the platform tag baked into the filename."""
    out = subprocess.run([sys.executable, "-m", "auditwheel", "show",
                          str(wheel)], capture_output=True, text=True,
                         check=False)
    if out.returncode != 0:
        die(f"auditwheel show failed:\n{out.stderr[-800:]}")
    expected = baked_tag.split("py3-none-")[-1]
    m = re.search(r'consistent with the following platform tag: "([^"]+)"',
                  out.stdout)
    grade = m.group(1) if m else "UNPARSEABLE"
    if grade != expected:
        die(f"auditwheel grades this wheel {grade!r}, but the filename "
            f"claims {expected!r} — a mislabeled tag must never ship")
    print(f"auditwheel gate ok: grade {grade} == baked tag")


def validate_linux_wheel(wheel):
    """Validate the companion against source btap before wheel smoke later
    validates the installed btap + installed companion distribution pair."""
    import os
    with tempfile.TemporaryDirectory(prefix="companion-validate-") as tmp:
        tmp = Path(tmp)
        venv = tmp / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        pip = venv / "bin" / "pip"
        py = venv / "bin" / "python"
        subprocess.run([str(pip), "install", "-q", str(wheel),
                        "openstudio~=3.11.0"], check=True)
        env = {**os.environ,
               "PYTHONPATH": str(REPO_ROOT / "python"),
               "XDG_CACHE_HOME": str(tmp / "cache")}  # cache isolated
        env.pop("BTAP_ENERGYPLUS", None)
        run_dir = tmp / "sizing"
        proc = subprocess.run(
            [str(py), "-m", "btap.necb.cli",
             str(REPO_ROOT / "verification/oracle/fixtures/5ZoneNoHVAC.osm"),
             "--simulate", "sizing",
             "--epw", str(REPO_ROOT / "python/tests/fixtures/weather/"
                          "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw"),
             "--hdd", "3890", "--storeys", "1", "--no-report", "--quiet",
             "--space-type", "Space Function/Office enclosed > 25 m2",
             "-o", str(run_dir)],
            capture_output=True, text=True, env=env, timeout=1200,
            check=False)
        if proc.returncode != 6:
            die(f"source-btap companion sizing run exited {proc.returncode}, "
                f"expected 6 (no determination):\n{proc.stderr[-1200:]}")
        for expected in ("proposed_sizing", "reference_sizing", "audit.json"):
            if not (run_dir / expected).exists():
                die(f"source-btap companion sizing run produced no {expected}")
        print("build-side validation ok: source btap + installed companion "
              "REAL sizing run (proposed+reference), isolated cache")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--platform", choices=["linux", "windows", "all"],
                    default="all")
    ap.add_argument("--iteration", type=int, default=1)
    ap.add_argument("--outdir", default=str(HERE / "dist"))
    ap.add_argument("--skip-validation", action="store_true",
                    help="skip the scratch-venv sizing validation (CI cache "
                         "restores are digest-verified instead)")
    ap.add_argument("--workdir", default=None,
                    help="cache dir for downloaded assets (default: temp)")
    args = ap.parse_args()

    version = f"{PINNED_VERSION}.{args.iteration}"
    outdir = Path(args.outdir)
    workdir = Path(args.workdir) if args.workdir else Path(
        tempfile.mkdtemp(prefix="btap-eplus-build-"))
    workdir.mkdir(parents=True, exist_ok=True)

    plats = ["linux", "windows"] if args.platform == "all" else [args.platform]
    wheels = [build_platform(p, version, outdir, workdir) for p in plats]
    if not args.skip_validation:
        for w in wheels:
            if "manylinux" in w.name:
                validate_linux_wheel(w)
    manifest = {w.name: sha256(w) for w in wheels}
    (outdir / "DIGESTS.json").write_text(json.dumps(manifest, indent=1) + "\n",
                                         encoding="utf-8")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
