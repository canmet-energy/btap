"""Provisioning an engine is EXCLUSIVE across processes.

`ensure_energyplus` looks the cache up and then installs into it, and that
check-then-act is shared by every process on the machine. `pytest -n auto`
starts a cold job with N workers that all reach it at once, so they extracted
the same ~230 MB release over each other and a worker executing the binary
another was rewriting got:

    OSError: [Errno 26] Text file busy: '.../energyplus'

reported as a test failure, in whichever test happened to be scheduled there
(CI run `38148719706`, exposed by this branch's new engine-backed tests).

The guard is a real race, not a stand-in for one: SEPARATE PROCESSES on a cold
cache, because the racing parties are xdist workers and a threading lock would
not see them. It counts INSTALLS rather than timing them — with the lock's
re-check inside it exactly one process installs and the rest find the engine
already there, and with the lock neutralised all of them install at once
(measured 8 of 8, max concurrency 8).

The engine itself is never downloaded here. The companion lookup and the
version verification are suppressed and the install is a fake that sleeps and
writes a stub, so what is under test is the exclusion, not the provisioner.
"""
import multiprocessing as mp
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

WORKERS = 4
INSTALL_SECONDS = 0.6


def _worker(index, cache, ledger, queue):
    """Reach the provisioning path, recording entry to and exit from it.

    The environment is set explicitly rather than inherited. A spawned child
    inherits its parent's `os.environ`, the parent here is an xdist worker,
    and `test_engine.py` sets `BTAP_ENERGYPLUS` to a deliberately nonexistent
    path — so under `-n 8` these children took the override rung and nothing
    installed. The test caught it ("0 of them installed") because it counts
    installs instead of trusting the run to have reached them, but a guard
    whose preconditions depend on sibling test order is not a guard.
    """
    os.environ["XDG_CACHE_HOME"] = cache
    for leaked in ("BTAP_ENERGYPLUS", "BTAP_ENERGYPLUS_ARCHIVE"):
        os.environ.pop(leaked, None)
    from btap.simulation import engine

    engine._companion_binary = lambda version: None
    engine._verify_version = lambda *args, **kwargs: None

    def fake_install(version):
        with open(ledger, "a", encoding="utf-8") as handle:
            handle.write(f"enter {index}\n")
        time.sleep(INSTALL_SECONDS)
        release = engine.cache_dir(version) / "release"
        release.mkdir(parents=True, exist_ok=True)
        binary = release / ("energyplus.exe" if sys.platform == "win32"
                            else "energyplus")
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755)
        with open(ledger, "a", encoding="utf-8") as handle:
            handle.write(f"leave {index}\n")

    engine._download_and_install = fake_install
    engine._install_archive = lambda path, version: fake_install(version)
    try:
        resolved = Path(engine.ensure_energyplus())
        inside = cache in str(resolved)
        queue.put(("ok" if inside else "wrong-rung", index, str(resolved)))
    except Exception as error:                              # noqa: BLE001
        queue.put(("error", index, f"{type(error).__name__}: {error}"))


class TestProvisioningIsExclusiveAcrossProcesses(unittest.TestCase):
    def test_a_cold_cache_is_provisioned_ONCE_by_concurrent_processes(self):
        if sys.platform == "win32":
            self.skipTest("spawn + advisory locking differ on win32; the "
                          "POSIX path is what CI races on")
        with tempfile.TemporaryDirectory(prefix="btap-provision-") as work:
            cache = str(Path(work) / "cache")
            ledger = str(Path(work) / "ledger")
            Path(cache).mkdir()

            context = mp.get_context("spawn")
            queue = context.Queue()
            workers = [context.Process(target=_worker,
                                       args=(n, cache, ledger, queue))
                       for n in range(WORKERS)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=120)

            results = [queue.get(timeout=10) for _ in range(WORKERS)]
            failures = [r for r in results if r[0] == "error"]
            self.assertEqual(
                [], failures,
                f"every process must resolve an engine; got {failures}")
            # Which RUNG answered. Without this a zero-install result reads as
            # "the lock worked" when it actually means the processes resolved
            # an engine from somewhere else and never raced at all.
            elsewhere = [r for r in results if r[0] == "wrong-rung"]
            self.assertEqual(
                [], elsewhere,
                "these processes resolved an engine OUTSIDE the temporary "
                f"cache, so they never reached the racing path: {elsewhere}")

            lines = (Path(ledger).read_text(encoding="utf-8").splitlines()
                     if Path(ledger).exists() else [])
            installs = [line for line in lines if line.startswith("enter")]
            depth = concurrent = 0
            for line in lines:
                depth += 1 if line.startswith("enter") else -1
                concurrent = max(concurrent, depth)

            self.assertEqual(
                1, len(installs),
                f"{WORKERS} processes raced a cold cache and "
                f"{len(installs)} of them installed. The lock's re-check "
                "must leave exactly one installing while the others find the "
                "engine already there — otherwise they extract over each "
                "other and one gets 'Text file busy'")
            self.assertEqual(
                1, concurrent,
                f"peak concurrent installs was {concurrent}; concurrent "
                "extraction into one cache directory IS the defect")


if __name__ == "__main__":
    unittest.main()
