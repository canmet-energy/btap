# Building the Windows installer

**CI builds and publishes this automatically**: pushing a `v*` tag runs
`.github/workflows/release.yml`, which builds the wheel, stages the Windows
CPython payload on Linux, executes it on a Windows runner, compiles it with
the Windows runner's own Inno Setup 6, and attaches the exe to a GitHub release. Dispatching the workflow by hand
(`gh workflow run release.yml`) is the rehearsal: the identical build, but the
publish step only reports what it would upload.

The manual path mirrors the workflow. Staging runs on Linux:

```bash
V=$(sed -n 's/#define AppVersion *"\(.*\)"/\1/p' packaging/windows/btap-compliance.iss)
python3 -m build --wheel --outdir dist .
python3 scripts/generate_samples.py packaging/windows/samples
python3 packaging/windows/stage_python.py --version "$V"
python3 packaging/windows/release_guards.py --version "$V"
python3 packaging/windows/installer_smoke.py
```

and compilation on Windows, with Inno Setup 6 installed:

```bat
iscc packaging\windows\btap-compliance.iss
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

## Compiler

CI compiles with the native Inno Setup 6 that GitHub's Windows runner image
ships, and requires major version 6 (the script uses IS6 directives); the exact
version is printed in the job log. It used to run ISCC under Wine on Linux, via
the `amake/innosetup` image, and that broke three times — two Wine versions
that could not run IS6, then in 2026-11 an unchanged image that stopped
starting on a newer `ubuntu-latest` (#233). The script was always written for
Windows; Wine was only a way to run it from Linux.

## What still requires real Windows

CI executes the staged tree on Windows before compiling the installer. Release
acceptance should still cover installation behavior on a clean Windows VM:
a clean VM with no OpenStudio, a VM that already has a *different* OpenStudio,
install paths containing spaces, the report rendering non-ASCII glyphs
correctly, exit codes, and uninstall.
