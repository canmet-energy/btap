#!/usr/bin/env python3
"""Stage the Windows installer payload — on Linux, without a Windows machine.

    python3 packaging/windows/stage_python.py --version 0.2.1 [--outdir stage]

The installer ships a PRE-INSTALLED tree, never a setup-time `pip install`:
the bytes are then deterministic, the install works offline, and no
dependency resolution can fail on a user's machine at the worst moment.
That is possible because every dependency publishes a wheel, so a Linux
host can resolve the Windows ones with pip's cross-platform flags
(`--platform win_amd64 --implementation cp --python-version 3.12
--only-binary=:all:`) and simply place them.

The runtime is CPython's official embeddable distribution, pinned by
sha256. It is a real `python.exe`, which matters: the report renderer
spawns `sys.executable`.

Everything downloaded is recorded in PROVENANCE.json with its digest, and
every installed distribution must account for its licence or the stage
fails — the installer redistributes CPython, OpenStudio, EnergyPlus and
the tbd chain, and that obligation is wider than this project's own LGPL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

#: CPython 3.12 because BOTH openstudio (cp312-cp312-win_amd64) and rpds-py
#: pin that minor for Windows — the version is forced by the dependencies,
#: not chosen. Digest verified before extraction, never after.
CPYTHON_VERSION = "3.12.10"
CPYTHON_URL = (f"https://www.python.org/ftp/python/{CPYTHON_VERSION}"
               f"/python-{CPYTHON_VERSION}-embed-amd64.zip")
CPYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"

#: Licence files a distribution may ship, in the order we look for them.
LICENCE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE",
                 "LICENCE.txt", "COPYING", "COPYING.txt", "NOTICE",
                 "LICENSE.rst", "PythonLicense.txt")


def die(msg: str) -> None:
    print(f"STAGE REFUSED: {msg}", file=sys.stderr)
    raise SystemExit(1)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch_runtime(workdir: Path) -> Path:
    dest = workdir / f"python-{CPYTHON_VERSION}-embed-amd64.zip"
    if not dest.exists():
        print(f"downloading {CPYTHON_URL}", flush=True)
        urllib.request.urlretrieve(CPYTHON_URL, dest)
    actual = sha256(dest)
    if actual != CPYTHON_SHA256:
        die(f"CPython embeddable sha256 {actual} != pinned {CPYTHON_SHA256}")
    print(f"verified CPython {CPYTHON_VERSION} embeddable "
          f"({dest.stat().st_size // 1024} KB)")
    return dest


def unpack_runtime(zip_path: Path, python_dir: Path) -> None:
    python_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(python_dir)
    # The embeddable distribution deliberately ships site-packages DISABLED:
    # its ._pth file replaces normal path setup and omits site. Adding the
    # directory and re-enabling `import site` is what makes an installed
    # tree importable at all.
    pth = python_dir / "python312._pth"
    if not pth.is_file():
        die("python312._pth missing from the embeddable distribution")
    text = pth.read_text(encoding="utf-8")
    if "Lib\\site-packages" not in text:
        text = text.replace("import site", "").rstrip() + \
            "\nLib\\site-packages\nimport site\n"
        pth.write_text(text, encoding="utf-8")
    print(f"runtime staged: {python_dir.name}/ (site-packages enabled)")


def install_tree(wheel: Path, site_packages: Path) -> None:
    """Resolve the WINDOWS dependency set from a Linux host and place it."""
    site_packages.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pip", "install", "--quiet",
           "--target", str(site_packages),
           "--platform", "win_amd64", "--implementation", "cp",
           "--python-version", "3.12", "--only-binary=:all:",
           f"{wheel}[tbd]"]
    print("staging the windows dependency set (cross-platform pip)…",
          flush=True)
    subprocess.run(cmd, check=True)
    # pip --target leaves a bin/ of POSIX console scripts that cannot work
    # under the embeddable runtime; the launcher calls `-m` instead.
    shutil.rmtree(site_packages / "bin", ignore_errors=True)


def distributions(site_packages: Path) -> list[dict]:
    """Every installed distribution, with the wheel tag and licence text."""
    out = []
    for info in sorted(site_packages.glob("*.dist-info")):
        meta = (info / "METADATA").read_text(encoding="utf-8", errors="replace")
        name = version = licence = ""
        for line in meta.splitlines():
            if line.startswith("Name: ") and not name:
                name = line[6:].strip()
            elif line.startswith("Version: ") and not version:
                version = line[9:].strip()
            elif line.startswith("License: ") and not licence:
                licence = line[9:].strip()
            elif line.startswith("Classifier: License ::"):
                licence = licence or line.split("::")[-1].strip()
            elif not line.strip():
                break
        tag = ""
        wheel_file = info / "WHEEL"
        if wheel_file.is_file():
            for line in wheel_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("Tag: "):
                    tag = line[5:].strip()
                    break
        # A shipped licence FILE is what actually satisfies redistribution;
        # the metadata field alone is a claim, not a notice.
        texts = [str(p.relative_to(site_packages))
                 for p in info.rglob("*")
                 if p.is_file() and p.name in LICENCE_NAMES]
        texts += [str(p.relative_to(site_packages))
                  for p in (site_packages / name.replace("-", "_")).rglob("*")
                  if p.is_file() and p.name in LICENCE_NAMES] \
            if (site_packages / name.replace("-", "_")).is_dir() else []
        out.append({"name": name, "version": version, "license": licence,
                    "wheel_tag": tag, "license_files": sorted(set(texts))})
    return out


#: Licence texts WE supply for distributions that declare a licence but ship
#: no notice file. Redistribution obliges us to carry the text; we cannot add
#: it to someone else's wheel, so it is curated here and copied into the
#: installation. A file here is a deliberate, reviewable act — never a way to
#: paper over an unknown licence.
CURATED_LICENCES = HERE / "licenses"


def write_inventory(dists: list[dict], stage: Path) -> None:
    unknown = [d["name"] for d in dists
               if not d["license"] and not d["license_files"]]
    if unknown:
        die("these installed distributions declare no licence and ship no "
            f"licence file: {unknown}. The installer redistributes them; "
            "account for each before releasing.")

    # Declaring a licence is a CLAIM; shipping its text is what satisfies
    # redistribution. Anything that declares but does not ship must have a
    # curated text here, or the stage fails.
    notices = stage / "licenses"
    notices.mkdir(exist_ok=True)
    missing = []
    for d in dists:
        if d["license_files"]:
            continue
        curated = CURATED_LICENCES / f"{d['name'].replace('-', '_')}.txt"
        if not curated.is_file():
            missing.append(f"{d['name']} (declares '{d['license']}')")
            continue
        shutil.copy2(curated, notices / curated.name)
        d["license_files"] = [f"licenses/{curated.name} (supplied by this installer)"]
    if missing:
        die("these distributions declare a licence but ship no notice, and "
            f"no curated text exists for them: {missing}. Add the upstream "
            f"licence text to {CURATED_LICENCES.relative_to(REPO_ROOT)}/.")
    lines = ["THIRD-PARTY SOFTWARE IN THIS INSTALLER",
             "=" * 38, "",
             "This installer redistributes the following, each under its own",
             "terms. Licence texts ship inside the installation; the paths",
             "below are relative to python\\Lib\\site-packages.", "",
             f"CPython {CPYTHON_VERSION} (embeddable distribution) — PSF-2.0",
             f"  {CPYTHON_URL}", ""]
    for d in dists:
        lines.append(f"{d['name']} {d['version']} — {d['license'] or 'see licence file'}")
        lines.append(f"  wheel: {d['wheel_tag']}")
        for f in d["license_files"]:
            lines.append(f"  licence: {f}")
        lines.append("")
    (stage / "THIRD-PARTY-NOTICES.txt").write_text(
        "\n".join(lines), encoding="utf-8")
    print(f"third-party inventory: {len(dists)} distributions, all accounted")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True, help="canmet-btap version")
    ap.add_argument("--wheel", help="path to the built canmet_btap wheel")
    ap.add_argument("--outdir", default=str(HERE / "stage"))
    ap.add_argument("--workdir", default=str(HERE / ".stage-cache"))
    args = ap.parse_args()

    stage = Path(args.outdir).resolve()
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    wheel = Path(args.wheel).resolve() if args.wheel else None
    if wheel is None:
        dist = REPO_ROOT / "python" / "dist"
        matches = sorted(dist.glob(f"canmet_btap-{args.version}-*.whl"))
        if not matches:
            die(f"no canmet_btap-{args.version} wheel in {dist}; "
                "build it first or pass --wheel")
        wheel = matches[-1]
    print(f"staging {wheel.name}")

    python_dir = stage / "python"
    unpack_runtime(fetch_runtime(workdir), python_dir)
    site_packages = python_dir / "Lib" / "site-packages"
    install_tree(wheel, site_packages)

    # Weather: the CLI reads BTAP_HOME/weather, so the installed tree must
    # carry it — a user has no checkout to fall back on.
    weather_src = REPO_ROOT / "python" / "tests" / "fixtures" / "weather"
    shutil.copytree(weather_src, stage / "weather")

    # The LAYOUT is load-bearing: the iss Start-menu shortcut puts {app}\bin
    # on PATH, run-demo.cmd calls ..\bin\btap-compliance.cmd, and the
    # launcher derives BTAP_HOME from its own directory's parent. Keep it
    # identical to the Ruby installer this succeeds.
    (stage / "bin").mkdir()
    shutil.copy2(HERE / "btap-compliance.cmd", stage / "bin" / "btap-compliance.cmd")
    shutil.copy2(HERE / "README-windows.txt", stage / "README-windows.txt")
    # The installer's own licence page (iss LicenseFile) and the LGPL text
    # this project ships under.
    shutil.copy2(REPO_ROOT / "LICENSE", stage / "LICENSE")

    # The sample models are GENERATED (and gitignored), so a fresh checkout
    # has none. Demand them rather than skipping quietly: a silent skip here
    # produced an installer whose Start-menu "Sample compliance run" pointed
    # at nothing, and the failure surfaced three lines later as a confusing
    # copy error into a directory that was never created.
    samples = HERE / "samples"
    models = sorted(samples.glob("*.osm")) if samples.is_dir() else []
    if not models:
        die(f"no sample models in {samples.relative_to(REPO_ROOT)}. Generate "
            "them first:\n  python3 python/scripts/generate_samples.py "
            f"{samples.relative_to(REPO_ROOT)}\n(needs the openstudio SDK "
            "importable)")
    shutil.copytree(samples, stage / "samples")
    print(f"samples: {len(models)} generated model(s)")
    shutil.copy2(HERE / "run-demo.cmd", stage / "samples" / "run-demo.cmd")
    # The demo model run-demo.cmd names.
    shutil.copy2(REPO_ROOT / "verification" / "oracle" / "fixtures" / "5ZoneNoHVAC.osm",
                 stage / "samples" / "5ZoneNoHVAC.osm")

    dists = distributions(site_packages)
    write_inventory(dists, stage)

    prov = {
        "canmet_btap_version": args.version,
        "cpython": {"version": CPYTHON_VERSION, "url": CPYTHON_URL,
                    "sha256": CPYTHON_SHA256},
        "wheel": {"filename": wheel.name, "sha256": sha256(wheel)},
        "distributions": dists,
        "note": ("Staged on Linux with cross-platform pip; every dependency "
                 "publishes a wheel, so nothing is compiled here and nothing "
                 "is resolved on the user's machine. The exact openstudio "
                 "wheel filename and tag are recorded above so a later "
                 "upload under the same version cannot silently change "
                 "installer bytes."),
    }
    (stage / "PROVENANCE.json").write_text(
        json.dumps(prov, indent=1) + "\n", encoding="utf-8")

    total = sum(f.stat().st_size for f in stage.rglob("*") if f.is_file())
    print(f"staged {stage} — {total / 1e6:.0f} MB, "
          f"{len(dists)} distributions, CPython {CPYTHON_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
