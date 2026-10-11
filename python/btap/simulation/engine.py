"""The EnergyPlus engine provisioner (M2, D-79).

The openstudio PyPI wheel carries the SDK and the ForwardTranslator but NO
EnergyPlus binary and NO CLI — running a simulation needs an engine from
somewhere. This module answers `ensure_energyplus() -> Path` (the energyplus
executable), resolving in order:

1. ``BTAP_ENERGYPLUS`` — explicit escape hatch: the binary itself or an
   EnergyPlus install directory. Verified, never blindly trusted; set-but-
   invalid RAISES rather than falling through.
2. The ``canmet-energyplus`` COMPANION package (R5, D-83) — on supported
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

import contextlib
import errno
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
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

#: `flock`/`locking` errnos that mean the FILESYSTEM cannot lock, as opposed
#: to the lock being held by someone else. Waiting cannot resolve these.
_LOCK_UNSUPPORTED_ERRNOS = frozenset(
    code for code in (getattr(errno, name, None)
                      for name in ("ENOLCK", "EOPNOTSUPP", "ENOTSUP",
                                   "EINVAL", "ENOSYS", "EPERM"))
    if code is not None)

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
    """The canmet-energyplus COMPANION package's engine (R5, D-83): on
    supported platforms it is a hard dependency carrying the pinned E+ as
    package data, so `pip install btap` needs no engine thought at all.

    FAIL-CLOSED once present: only a genuine top-level ImportError (the
    optional-platform case — macOS, unsupported Linux) falls through to
    the later rungs. Once the package imports, ANY defect raises — a
    broken companion is a corrupted install and must never hide behind a
    stale cache or a network download.
    """
    try:
        import canmet_energyplus
    except ModuleNotFoundError as exc:
        if exc.name == "canmet_energyplus":
            return None  # genuinely absent — the optional-platform case
        # A submodule failed to import: the package IS installed and IS
        # broken — corruption must not masquerade as absence.
        raise EngineError(
            "the canmet-energyplus companion package is installed but broken "
            f"(missing {exc.name}) — reinstall it (pip install "
            "--force-reinstall canmet-energyplus)"
        ) from exc
    except ImportError as exc:
        raise EngineError(
            "the canmet-energyplus companion package is installed but failed "
            f"to import ({exc}) — reinstall it (pip install "
            "--force-reinstall canmet-energyplus)"
        ) from exc

    try:
        companion_version = canmet_energyplus.ENERGYPLUS_VERSION
        binary = Path(canmet_energyplus.binary_path())
    except Exception as exc:  # nested import/data failure = corruption
        raise EngineError(
            "the canmet-energyplus companion package is installed but broken "
            f"({exc.__class__.__name__}: {exc}) — reinstall it (pip install "
            "--force-reinstall canmet-energyplus)"
        ) from exc
    if companion_version != version:
        raise EngineError(
            f"the canmet-energyplus companion carries EnergyPlus "
            f"{companion_version}, but this btap release pins {version} — "
            "upgrade the matching companion release (a repackaging always "
            "ships with a corresponding btap release)"
        )
    if not binary.is_file():
        raise EngineError(
            f"the canmet-energyplus companion names {binary} but no such "
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
        _verify_version(companion, version, source="canmet-energyplus companion")
        _resolved = companion
        return companion

    cached = _binary_in(cache_dir(version))
    if cached is not None:
        _resolved = cached
        return cached

    # PROVISION UNDER A LOCK, re-checking the cache inside it.
    #
    # The cache lookup above and the install below are a check-then-act over a
    # directory shared by every process on the machine, and `pytest -n auto`
    # starts a cold job with N workers that all reach here at once. They then
    # extract the same ~230 MB release over each other, and a worker running
    # the binary another worker is rewriting gets:
    #
    #     OSError: [Errno 26] Text file busy: '.../energyplus'
    #
    # which is a provisioning race reported as a test failure, non-
    # deterministically, in whichever test happened to be scheduled there.
    #
    # The re-check INSIDE the lock is what makes this correct rather than
    # merely serialised: the workers that wait find the engine already
    # installed and return it, instead of taking turns re-extracting it.
    archive = os.environ.get("BTAP_ENERGYPLUS_ARCHIVE", "").strip()
    with _provision_lock(version):
        cached = _binary_in(cache_dir(version))
        if cached is None:
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


#: How long to wait for another process to finish provisioning. Sized for the
#: operation it waits on — a ~230 MB download and extraction — not for a
#: lock that is merely held briefly.
PROVISION_LOCK_TIMEOUT_S = 900.0
PROVISION_LOCK_POLL_S = 0.25


@contextlib.contextmanager
def _provision_lock(version: str, timeout: float = PROVISION_LOCK_TIMEOUT_S):
    """Exclusive, cross-PROCESS lock over one version's cache directory.

    Cross-process because the racing parties are xdist workers, which are
    separate interpreters — a threading lock would not see them.

    It does NOT fail open. The first version caught every locking error and
    then yielded the critical section unlocked, which meant Windows'
    `msvcrt.LK_LOCK` giving up after about ten seconds, or a filesystem
    without advisory locking, silently resumed the racy behaviour this exists
    to remove — and a fallback like that cannot support a claim of exclusive
    provisioning (Sol, `214`). Instead:

    * contention WAITS, bounded by `timeout` and sized for a 230 MB download
      and extraction rather than for a briefly held lock; and
    * a lock that cannot be taken at all raises `EngineError`, naming the two
      overrides that skip provisioning entirely.

    Raising is the right failure here because the alternative is a silent
    return to a known defect. A reader is protected regardless by
    `_extract_atomically`, which publishes the install in one `os.replace`;
    this lock is what stops two processes doing the same 230 MB of work and
    replacing each other's result.
    """
    target = cache_dir(version)
    lock_path = target.parent / f".{target.name}.provision.lock"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+")
    except OSError as error:
        raise EngineError(
            f"cannot open the provisioning lock {lock_path} ({error}). The "
            "engine cache is not usable for concurrent provisioning; set "
            "BTAP_ENERGYPLUS to an existing install, or "
            "BTAP_ENERGYPLUS_ARCHIVE to the downloaded release asset."
        ) from error

    if sys.platform == "win32":
        import msvcrt

        def acquire():
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

        def release():
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        def acquire():
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

        def release():
            fcntl.flock(handle, fcntl.LOCK_UN)

    deadline = time.monotonic() + timeout
    held = False
    try:
        while True:
            try:
                acquire()
                held = True
                break
            except OSError as error:
                # A filesystem that does not support advisory locking at all
                # reports it distinctly from contention, and no amount of
                # waiting will change it.
                if error.errno in _LOCK_UNSUPPORTED_ERRNOS:
                    raise EngineError(
                        f"advisory locking is unavailable on {lock_path} "
                        f"({error}). Provisioning cannot be made exclusive "
                        "there, and proceeding would let concurrent processes "
                        "install over each other; set BTAP_ENERGYPLUS to an "
                        "existing install, or BTAP_ENERGYPLUS_ARCHIVE to the "
                        "downloaded release asset."
                    ) from error
                if time.monotonic() >= deadline:
                    raise EngineError(
                        f"waited {timeout:.0f}s for another process to "
                        f"finish provisioning EnergyPlus {version} "
                        f"({lock_path} is still held). If no such process is "
                        "running, delete that lock file."
                    ) from error
                time.sleep(PROVISION_LOCK_POLL_S)
        yield
    finally:
        if held:
            with contextlib.suppress(OSError):
                release()
        handle.close()


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
            f"canmet-energyplus companion; on this platform install EnergyPlus {version} "
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
    _extract_atomically(archive, cache_dir(version))


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
        _extract_atomically(tmp, cache_dir(version))
    finally:
        tmp.unlink(missing_ok=True)


def _extract_atomically(archive: Path, dest: Path) -> None:
    """Extract so a CONCURRENT READER never sees a partial install.

    The provisioning lock serialises WRITERS, and the failure it was added for
    is a READER: `ensure_energyplus` checks the cache BEFORE taking the lock,
    so a process arriving mid-extraction found `release/energyplus` the moment
    tar created the entry and ran `--version` on a binary still being written
    (Fable, `214`). Serialising the installs does not help that process —
    it never reaches the lock.

    So the tree is built in a sibling staging directory and moved into place
    with one `os.replace`. A reader then sees either no cache directory at all,
    and takes the lock, or a complete one. The staging directory is a sibling
    rather than a child so the rename stays within one filesystem, and it is
    OUTSIDE `dest`, so `_binary_in`'s glob cannot find a half-written binary
    in it.

    Removing an existing `dest` is safe because every caller holds the
    provisioning lock: the only `dest` that can be there is a partial install
    from a crashed earlier run.
    """
    _stage(lambda into: _extract(archive, into), dest)


def _stage(build, dest: Path) -> None:
    """Run `build(staging)` and move the result onto `dest` in one step.

    Separate from `_extract_atomically` so a test can drive the real staging
    with its own `build` instead of reimplementing the part under test.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{dest.name}.staging-",
                                    dir=dest.parent))
    try:
        build(staging)
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(staging, dest)
        staging = None
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


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
