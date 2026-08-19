# Building the Windows installer

Two steps, both runnable from the Linux devcontainer. Only the second needs
wine, and only the *testing* needs an actual Windows machine.

```bash
# 1. assemble the payload (~790 MB with OpenStudio, ~8 MB without)
curl -LO https://github.com/NREL/OpenStudio/releases/download/v3.11.0/OpenStudio-3.11.0%2B241b8abb4d-Windows.tar.gz
tar xzf OpenStudio-3.11.0+241b8abb4d-Windows.tar.gz
rake windows:stage OPENSTUDIO_WINDOWS=$PWD/OpenStudio-3.11.0+241b8abb4d-Windows

# 2. compile it
bash .devcontainer/setup.sh --wine     # once: wine + Inno Setup 6
rake windows:installer                 # -> packaging/windows/Output/*.exe
```

## Why it is built this way

**OpenStudio is bundled, not a prerequisite.** The recipient installs one
thing. That also deletes the CLI detection, the version gate and the PATH
handling from the launcher, and removes version skew — a user on OpenStudio 3.9
would otherwise fail ~20 minutes into a run with an opaque engine error, because
neither OpenStudio nor EnergyPlus translates backward.

**The Windows payload is assembled on Linux.** NREL publishes a
`...-Windows.tar.gz` alongside the `.exe` installer, and it unpacks cleanly on
Linux — `bin/openstudio.exe` is a normal PE32+ x86-64 binary. Nothing needs a
Windows machine to *stage*.

**`Python/`, `include/`, `Radiance/` and `Examples/` are dropped** (218 MB of
1000). The gems are Ruby-only and reference no Radiance. `Perl/` is kept because
EnergyPlus ships it. `OPENSTUDIO_FULL=1` stages the whole tree if anything
misbehaves.

**Per-user install, no admin.** `PrivilegesRequired=lowest` means no UAC prompt
and it works where the user cannot elevate; `{autopf}` then resolves to
`%LOCALAPPDATA%\Programs` on its own. Someone with admin can still choose a
machine-wide install from the dialog.

**The priced costing tables are excluded** — `--costs-csv` injects a licensed
one. A test in `openstudio-necb/test/test_cli.rb` renames them aside and runs
the CLI to prove the compliance path never needs them.

## Wine notes (each cost time to establish)

- **Inno Setup 6's `ISCC.exe` is 32-bit** (`PE32, Intel 80386`), so it needs
  `wine32:i386` and the i386 architecture enabled.
- **Inno Setup 7 has a native x64 build** that would avoid multiarch entirely,
  but it refuses to install under wine 9 — "This program does not support the
  version of Windows your computer is running" — at every Windows version wine
  can be made to report, including win11 (10.0.22000). Do not spend time on it.
- **wine needs a display even for a silent install.** `xvfb-run -a` supplies
  one; without it wine dies with "X connection broken".

## What still requires real Windows

Wine compiles the installer; it does not validate it. Before shipping, run
through the checklist in the repository plan on an actual Windows machine:
a clean VM with no OpenStudio, a VM that already has a *different* OpenStudio,
install paths containing spaces, the report rendering non-ASCII glyphs
correctly, exit codes, and uninstall.
