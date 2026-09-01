# Building the Windows installer

**CI builds and publishes this automatically**: pushing a `v*` tag runs
`.github/workflows/release.yml`, which builds the wheel, stages the Windows
CPython payload on Linux, executes it on a Windows runner, compiles with
containerized Inno Setup, and attaches the exe to a GitHub release. Dispatching the workflow by hand
(`gh workflow run release.yml`) is the rehearsal: the identical build, but the
publish step only reports what it would upload.

The manual Linux path mirrors the workflow:

```bash
python3 -m build --wheel --outdir python/dist python/
python3 python/scripts/generate_samples.py packaging/windows/samples
python3 packaging/windows/stage_python.py --version 0.2.1
python3 packaging/windows/release_guards.py --version 0.2.1
python3 packaging/windows/installer_smoke.py
mkdir -p packaging/windows/Output
docker run --rm -v "$PWD:/work" amake/innosetup:latest \
  packaging/windows/btap-compliance.iss
```

## Why it is built this way

**CPython and all wheels are bundled, not prerequisites.** The recipient
installs one thing. OpenStudio and EnergyPlus arrive as pinned Python wheel
dependencies inside the staged `site-packages` tree.

**The Windows payload is assembled on Linux.** Cross-platform pip resolves the
complete `win_amd64` wheel set into the official CPython 3.12 embeddable
runtime. Nothing is compiled on the user's machine. A Windows runner executes
the staged CLI before the installer is allowed to publish.

**Per-user install, no admin.** `PrivilegesRequired=lowest` means no UAC prompt
and it works where the user cannot elevate; `{autopf}` then resolves to
`%LOCALAPPDATA%\Programs` on its own. Someone with admin can still choose a
machine-wide install from the dialog.

**The priced costing tables are excluded** — `--costs-csv` injects a licensed
one. Placeholder schemas remain available for the costing machinery.

## Compiler image

CI uses `amake/innosetup:latest`, which wraps a known-good ISCC-under-wine
environment. Local compilation should use the same image so host Wine versions
cannot change the installer bytes or fail on a different Inno Setup runtime.

## What still requires real Windows

CI executes the staged tree on Windows before compiling the installer. Release
acceptance should still cover installation behavior on a clean Windows VM:
a clean VM with no OpenStudio, a VM that already has a *different* OpenStudio,
install paths containing spaces, the report rendering non-ASCII glyphs
correctly, exit codes, and uninstall.
