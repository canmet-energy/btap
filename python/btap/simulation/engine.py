"""The EnergyPlus engine provisioner (M2, D-79).

The openstudio PyPI wheel carries the SDK and the ForwardTranslator but NO
EnergyPlus binary and NO CLI — running a simulation needs an engine from
somewhere. This module answers `ensure_energyplus() -> Path` (the energyplus
executable), resolving in order:

1. ``BTAP_ENERGYPLUS`` — explicit escape hatch: the binary itself or an
   EnergyPlus install directory. Verified, never blindly trusted; set-but-
   invalid RAISES rather than falling through.
2. The ``btap-energyplus`` COMPANION package (R5, D-83) — on supported
   platforms a hard dependency carrying the pinned engine as package
   data. FAIL-CLOSED once importable: genuine absence is the only
   fall-through; a broken, mismatched, or unrunnable companion raises.
   Outranks the cache deliberately (the cache rung is unverified).
3. The btap cache (``~/.cache/btap/energyplus/<version>`` on Linux, the
   platform-conventional cache dir elsewhere) from an earlier provision.
4. ``BTAP_ENERGYPLUS_ARCHIVE`` — a locally supplied release archive
   (the TLS-intercepted-network side-load), sha256-verified against the pin.
5. Download from the official NREL GitHub release, sha256-verified.

The version is LOCKED to the wheel's own IDD generation (openstudio 3.11 <=>
EnergyPlus 25.2): a resolved binary whose reported version disagrees with
``openstudio.energyPlusVersion()`` is refused, loudly — version skew used to
fail opaquely ~20 minutes into a run. Every error names its remedy.

Stdlib only; ``import openstudio`` happens lazily (only to learn the wheel's
E+ version) so the module stays importable without the SDK.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

#: The one pinned engine generation (matches the openstudio~=3.11.0 wheel).
PINNED_VERSION = "25.2.0"
_BUILD_SHA = "cf7368216c"

#: (system, machine) -> (release asset, sha256). Digests read from the
#: official NREL/EnergyPlus v25.2.0 release via the GitHub API (2026-08-26).
_ASSETS = {
    ("linux", "x86_64"): (
        f"EnergyPlus-{PINNED_VERSION}-{_BUILD_SHA}-Linux-Ubuntu22.04-x86_64.tar.gz",
        "e454fecd0f40be2e7ad8b574722b58ef8b9adc15aadfa31716f1c70a93ced4da",
    ),
    ("linux", "aarch64"): (
        f"EnergyPlus-{PINNED_VERSION}-{_BUILD_SHA}-Linux-Ubuntu22.04-arm64.tar.gz",
        "b5247538b4ecbaec9ea57754b55d5d8cd3e07059b3c485db387b5430a8fa1f5a",
    ),
    ("darwin", "x86_64"): (
        f"EnergyPlus-{PINNED_VERSION}-{_BUILD_SHA}-Darwin-macOS12.1-x86_64.tar.gz",
        "7994e64bde2ca1be781a414a5ff91b7499068b7e26cb481ec06882a9cff0d930",
    ),
    ("darwin", "arm64"): (
        f"EnergyPlus-{PINNED_VERSION}-{_BUILD_SHA}-Darwin-macOS13-arm64.tar.gz",
        "e7976e82509d961bcf484963a1a7109db4cae318dfc318898f97183f4097deda",
    ),
    ("windows", "amd64"): (
        f"EnergyPlus-{PINNED_VERSION}-{_BUILD_SHA}-Windows-x86_64.zip",
        "4136901f7e1708f6536d84278e26ad88b414c7efc905febf6d49c2539a36f3cd",
    ),
}

_DOWNLOAD_BASE = "https://github.com/NREL/EnergyPlus/releases/download"

_resolved: Path | None = None  # per-process memo (verification runs the binary)


class EngineError(RuntimeError):
    """Provisioning failed; the message names the remedy."""


def wheel_energyplus_version() -> str:
    """The E+ generation the installed openstudio wheel translates for —
    the version everything else must match. Falls back to the pin when the
    SDK is absent (so the provisioner is usable stand-alone)."""
    try:
        import openstudio
        return str(openstudio.energyPlusVersion())
    except ImportError:
        return PINNED_VERSION


def _companion_binary(version: str) -> "Path | None":
    """The btap-energyplus COMPANION package's engine (R5, D-83): on
    supported platforms it is a hard dependency carrying the pinned E+ as
    package data, so `pip install btap` needs no engine thought at all.

    FAIL-CLOSED once present: only a genuine top-level ImportError (the
    optional-platform case — macOS, unsupported Linux) falls through to
    the later rungs. Once the package imports, ANY defect raises — a
    broken companion is a corrupted install and must never hide behind a
    stale cache or a network download.
    """
    try:
        import btap_energyplus
    except ModuleNotFoundError as exc:
        if exc.name == "btap_energyplus":
            return None  # genuinely absent — the optional-platform case
        # A submodule failed to import: the package IS installed and IS
        # broken — corruption must not masquerade as absence.
        raise EngineError(
            "the btap-energyplus companion package is installed but broken "
            f"(missing {exc.name}) — reinstall it (pip install "
            "--force-reinstall btap-energyplus)"
        ) from exc
    except ImportError as exc:
        raise EngineError(
            "the btap-energyplus companion package is installed but failed "
            f"to import ({exc}) — reinstall it (pip install "
            "--force-reinstall btap-energyplus)"
        ) from exc

    try:
        companion_version = btap_energyplus.ENERGYPLUS_VERSION
        binary = Path(btap_energyplus.binary_path())
    except Exception as exc:  # nested import/data failure = corruption
        raise EngineError(
            "the btap-energyplus companion package is installed but broken "
            f"({exc.__class__.__name__}: {exc}) — reinstall it (pip install "
            "--force-reinstall btap-energyplus)"
        ) from exc
    if companion_version != version:
        raise EngineError(
            f"the btap-energyplus companion carries EnergyPlus "
            f"{companion_version}, but this btap release pins {version} — "
            "upgrade the matching companion release (a repackaging always "
            "ships with a corresponding btap release)"
        )
    if not binary.is_file():
        raise EngineError(
            f"the btap-energyplus companion names {binary} but no such "
            "binary exists — the install is corrupted; reinstall it"
        )
    return binary


def ensure_energyplus() -> Path:
    """Resolve (provisioning if necessary) a verified EnergyPlus binary of
    the pinned version. Memoized per process."""
    global _resolved
    if _resolved is not None:
        return _resolved

    version = wheel_energyplus_version()
    if version != PINNED_VERSION:
        raise EngineError(
            f"the installed openstudio wheel wants EnergyPlus {version}, but this btap "
            f"release pins {PINNED_VERSION}. Install openstudio~=3.11.0, or update btap."
        )

    override = os.environ.get("BTAP_ENERGYPLUS", "").strip()
    if override:
        binary = _binary_in(Path(override))
        if binary is None:
            raise EngineError(
                f"BTAP_ENERGYPLUS={override!r} is neither an energyplus binary nor an "
                "EnergyPlus install directory containing one. Point it at the executable "
                "(or its directory), or unset it to use the managed engine."
            )
        _verify_version(binary, version, source="BTAP_ENERGYPLUS")
        _resolved = binary
        return binary

    # The companion outranks the cache: the cache rung below returns
    # UNVERIFIED, and the pip-hash-verified companion is the shipped truth.
    companion = _companion_binary(version)
    if companion is not None:
        _verify_version(companion, version, source="btap-energyplus companion")
        _resolved = companion
        return companion

    cached = _binary_in(cache_dir(version))
    if cached is not None:
        _resolved = cached
        return cached

    archive = os.environ.get("BTAP_ENERGYPLUS_ARCHIVE", "").strip()
    if archive:
        _install_archive(Path(archive), version)
    else:
        _download_and_install(version)

    binary = _binary_in(cache_dir(version))
    if binary is None:
        raise EngineError(
            f"provisioning completed but no energyplus binary landed under {cache_dir(version)} "
            "— the archive layout was not the official release layout."
        )
    _verify_version(binary, version, source="provisioned engine")
    _resolved = binary
    return binary


def cache_dir(version: str) -> Path:
    """Platform-conventional per-user cache: engines are ~230 MB and shared
    across projects, so they never live in a run directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "btap" / "cache" / "energyplus" / version
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "btap" / "energyplus" / version
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "btap" / "energyplus" / version


def _binary_in(path: Path) -> Path | None:
    """Accept the binary itself, an install dir, or a dir holding one
    extracted release (the cache layout)."""
    exe = "energyplus.exe" if sys.platform == "win32" else "energyplus"
    if path.is_file():
        return path
    if not path.is_dir():
        return None
    direct = path / exe
    if direct.is_file():
        return direct
    hits = sorted(path.glob(f"*/{exe}"))
    return hits[0] if hits else None


def _verify_version(binary: Path, version: str, source: str) -> None:
    """Run `energyplus --version` and demand the pinned generation — skew
    between the wheel's IDD and the engine fails opaquely mid-run otherwise."""
    try:
        out = subprocess.run([str(binary), "--version"], capture_output=True,
                             text=True, timeout=30).stdout
    except OSError as e:
        raise EngineError(f"{source}: {binary} is not runnable ({e})") from e
    found = re.search(r"Version\s+(\d+\.\d+\.\d+)", out)
    if not found:
        raise EngineError(
            f"{source}: {binary} did not identify itself as EnergyPlus "
            f"(--version said: {out.strip()[:200]!r})"
        )
    if found.group(1) != version:
        raise EngineError(
            f"{source}: {binary} is EnergyPlus {found.group(1)}, but the openstudio wheel "
            f"translates for {version}. Mixed versions fail opaquely mid-run, so this is "
            f"refused. Point BTAP_ENERGYPLUS at an EnergyPlus {version} install, or unset "
            "it to use the managed engine."
        )


def _pinned_asset(version: str) -> tuple[str, str]:
    key = (
        "windows" if sys.platform == "win32" else ("darwin" if sys.platform == "darwin" else "linux"),
        platform.machine().lower(),
    )
    if key not in _ASSETS:
        raise EngineError(
            f"no pinned EnergyPlus {version} build for platform {key}. On Windows x86-64 "
            "and supported Linux x86-64, `pip install btap` ships the engine as the "
            f"btap-energyplus companion; on this platform install EnergyPlus {version} "
            "yourself and set BTAP_ENERGYPLUS to its location."
        )
    return _ASSETS[key]


def _install_archive(archive: Path, version: str) -> None:
    asset, sha256 = _pinned_asset(version)
    if not archive.is_file():
        raise EngineError(f"BTAP_ENERGYPLUS_ARCHIVE={archive} does not exist")
    digest = _sha256(archive)
    if digest != sha256:
        raise EngineError(
            f"BTAP_ENERGYPLUS_ARCHIVE={archive} has sha256 {digest}, expected {sha256} "
            f"(the official {asset}). Download the exact release asset — a re-wrapped or "
            "partial archive is refused."
        )
    _extract(archive, cache_dir(version))


def _download_and_install(version: str) -> None:
    asset, sha256 = _pinned_asset(version)
    url = f"{_DOWNLOAD_BASE}/v{version}/{asset}"
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=Path(asset).suffix)
    tmp = Path(tmp_name)
    try:
        try:
            with urllib.request.urlopen(url) as response, open(tmp_fd, "wb") as out:
                shutil.copyfileobj(response, out)
        except OSError as e:
            raise EngineError(
                f"could not download {url} ({e}). On a network that intercepts TLS, download "
                "the archive with your browser and set BTAP_ENERGYPLUS_ARCHIVE to the file — "
                "or point BTAP_ENERGYPLUS at an existing EnergyPlus install."
            ) from e
        digest = _sha256(tmp)
        if digest != sha256:
            raise EngineError(
                f"downloaded {asset} has sha256 {digest}, expected {sha256} — refusing to "
                "install a tampered or truncated engine."
            )
        _extract(tmp, cache_dir(version))
    finally:
        tmp.unlink(missing_ok=True)


def _extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="data")  # 'data' blocks path traversal


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _reset_memo() -> None:
    """Test seam: forget the per-process resolution."""
    global _resolved
    _resolved = None
