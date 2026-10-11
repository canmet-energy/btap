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
import errno
import multiprocessing as mp
import os
import pathlib
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

    def extract(into):
        """Write the binary FIRST, then keep working — as tar does.

        The previous fake created the binary at the END, which made it atomic
        exactly where the real installer is not, and so it could not see a
        reader picking up a half-written binary (Fable, `214`). Writing it
        first and finishing afterwards is the shape that exposes it.

        """
        release = into / "release"
        release.mkdir(parents=True, exist_ok=True)
        binary = release / ("energyplus.exe" if sys.platform == "win32"
                            else "energyplus")
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755)
        time.sleep(INSTALL_SECONDS)                  # the rest of the release
        (release / "Energy+.idd").write_text("x", encoding="utf-8")

    def fake_install(version):
        with open(ledger, "a", encoding="utf-8") as handle:
            handle.write(f"enter {index}\n")
        # Through the REAL staging path, so what is under test is the
        # product's atomicity and not the fake's.
        engine._stage(extract, engine.cache_dir(version))
        with open(ledger, "a", encoding="utf-8") as handle:
            handle.write(f"leave {index}\n")

    engine._download_and_install = fake_install
    engine._install_archive = lambda path, version: fake_install(version)
    try:
        resolved = Path(engine.ensure_energyplus())
        if cache not in str(resolved):
            queue.put(("wrong-rung", index, str(resolved)))
        elif not (resolved.parent / "Energy+.idd").is_file():
            # The install writes the binary first and the rest afterwards, so
            # a resolution that lacks the later file came from a tree still
            # being built. This is the reader half of the race: the process
            # that sees a half-written binary never reaches the lock, so
            # serialising the writers cannot help it (Fable, `214`).
            queue.put(("partial", index, str(resolved)))
        else:
            queue.put(("ok", index, str(resolved)))
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
            partial = [r for r in results if r[0] == "partial"]
            self.assertEqual(
                [], partial,
                "these processes resolved a HALF-INSTALLED engine, which is "
                "what `Text file busy` is: the install must be moved into "
                f"place in one step, not built in place. {partial}")

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


class TestThePublishIsAtomic(unittest.TestCase):
    """A partial install is never VISIBLE at the cache path.

    This is the reader half of the race, and it does not need a race to
    test. `ensure_energyplus` checks the cache before taking the lock, so a
    process arriving mid-install resolves whatever is visible at that moment;
    the property that protects it is simply that nothing incomplete is ever
    visible there.

    I first tried to catch this by orchestrating four processes and timing
    them. Fable (`217`) measured that version escaping 2 runs in 25, and my
    attempt to fix it with a handshake made it escape 25 of 25 — the readers
    could not reach the cache inside the window at all, so the test became
    weaker while looking stronger. A race whose outcome depends on process
    scheduling cannot carry an invariant. Asking the question directly can:
    AT THE MOMENT the install has written its binary and nothing else, is
    anything resolvable at `cache_dir`?
    """

    def setUp(self):
        from btap.simulation import engine

        self.engine = engine
        self.work = tempfile.TemporaryDirectory(prefix="btap-atomic-")
        self.addCleanup(self.work.cleanup)
        self.target = pathlib.Path(self.work.name) / "cache" / "1.2.3"

    def test_nothing_is_resolvable_at_the_cache_PATH_mid_install(self):
        engine = self.engine
        seen = []

        def build(into):
            release = into / "release"
            release.mkdir(parents=True, exist_ok=True)
            binary = release / "energyplus"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o755)
            # The binary exists and the release does not. What would a
            # process checking the cache right now resolve?
            seen.append(engine._binary_in(self.target))
            (release / "Energy+.idd").write_text("x", encoding="utf-8")

        engine._stage(build, self.target)

        self.assertEqual(
            [None], seen,
            "mid-install, `_binary_in` resolved "
            f"{seen!r} at the cache path. A process checking the cache then "
            "returns that binary and runs `--version` on a file still being "
            "written — which is the `Text file busy` this fix exists to "
            "remove. The install must be published in ONE step")
        self.assertTrue(
            engine._binary_in(self.target),
            "and afterwards it must resolve, or the staging never landed")
        self.assertTrue(
            (engine._binary_in(self.target).parent / "Energy+.idd").is_file(),
            "with the whole release, not just the binary")

    def test_a_crashed_install_leaves_nothing_resolvable(self):
        """`_stage` must not publish a tree its builder failed to finish."""
        engine = self.engine

        def build(into):
            (into / "release").mkdir(parents=True, exist_ok=True)
            (into / "release" / "energyplus").write_text("x", encoding="utf-8")
            raise RuntimeError("download died")

        with self.assertRaises(RuntimeError):
            engine._stage(build, self.target)
        self.assertIsNone(
            engine._binary_in(self.target),
            "a failed install must leave the cache EMPTY, not half-published")
        self.assertEqual(
            [], list(self.target.parent.glob(".*staging-*")),
            "and it must not leave its staging directory behind")


class TestTheLockDoesNotFailOpen(unittest.TestCase):
    """Contention WAITS; an unlockable filesystem RAISES.

    The first version caught every locking error and yielded the critical
    section unlocked, so Windows' `LK_LOCK` giving up after ten seconds, or a
    filesystem without advisory locking, silently resumed the racy behaviour
    the lock exists to remove (Sol, `214`). These are the tests he asked for
    in place of skipping the path and assuming it was equivalent.
    """

    def setUp(self):
        from btap.simulation import engine

        self.engine = engine
        self.work = tempfile.TemporaryDirectory(prefix="btap-lock-")
        self.addCleanup(self.work.cleanup)
        self._cache_dir = engine.cache_dir
        engine.cache_dir = lambda version: (
            pathlib.Path(self.work.name) / "cache" / version)
        self.addCleanup(lambda: setattr(engine, "cache_dir", self._cache_dir))

    def test_a_held_lock_makes_the_second_caller_WAIT_then_give_up(self):
        """Bounded, and it must not proceed.

        Driven with a tiny timeout so the test is fast; the shipped value is
        sized for a 230 MB download instead.
        """
        engine = self.engine
        with engine._provision_lock("1.2.3"):
            started = time.monotonic()
            with self.assertRaises(engine.EngineError) as caught:
                with engine._provision_lock("1.2.3", timeout=0.75):
                    self.fail(
                        "the second caller entered the critical section while "
                        "the first still held the lock — that is the race")
            waited = time.monotonic() - started
        self.assertIn("waited", str(caught.exception).lower())
        self.assertGreaterEqual(
            waited, 0.7,
            f"it must WAIT for the operation, not fail at once (waited "
            f"{waited:.2f}s of a 0.75s budget)")

    def test_an_unlockable_filesystem_RAISES_instead_of_proceeding(self):
        """`ENOLCK` is not contention and no wait resolves it."""
        engine = self.engine
        if sys.platform == "win32":
            self.skipTest("the POSIX errno path is what this asserts")
        import fcntl

        real = fcntl.flock

        def refuses(*args, **kwargs):
            raise OSError(errno.ENOLCK, "no locks available")

        fcntl.flock = refuses
        self.addCleanup(lambda: setattr(fcntl, "flock", real))
        with self.assertRaises(engine.EngineError) as caught:
            with engine._provision_lock("1.2.3", timeout=5.0):
                self.fail("an unlockable filesystem must not yield the "
                          "critical section — that is the silent fallback")
        message = str(caught.exception)
        self.assertIn("advisory locking is unavailable", message)
        self.assertIn(
            "BTAP_ENERGYPLUS to an existing", message,
            "and it must name the override that skips provisioning, so the "
            "refusal leaves the user a way forward")
        # The remedy must actually BYPASS the failed operation.
        # `BTAP_ENERGYPLUS_ARCHIVE` does not: `ensure_energyplus` reads it and
        # then enters this lock, calling `_install_archive` INSIDE it — so
        # offering it as a way out of a locking failure sends the reader back
        # into the thing that just failed (Sol, `217`).
        self.assertIn(
            "does NOT help", message,
            "and it must say that the archive variable is not a way out")

    def test_the_refusals_name_only_remedies_that_actually_BYPASS(self):
        """Checked against the resolution ORDER, not against the prose.

        `BTAP_ENERGYPLUS` is read at the first rung and returns before any
        locking or provisioning. `BTAP_ENERGYPLUS_ARCHIVE` is read just before
        the lock and consumed inside it. A message may therefore offer the
        first as an escape and must not offer the second.
        """
        import inspect

        source = inspect.getsource(self.engine.ensure_energyplus)
        override = source.index('"BTAP_ENERGYPLUS"')
        archive = source.index("BTAP_ENERGYPLUS_ARCHIVE")
        lock = source.index("_provision_lock")
        install = source.index("_install_archive")
        self.assertLess(
            override, lock,
            "the override must resolve before the lock for the message to be "
            "true; if this moved, the refusals need rewriting")
        self.assertLess(
            lock, install,
            "and the archive is installed INSIDE the lock, which is why it "
            "cannot be offered as an escape from a locking failure")
        self.assertLess(archive, lock)

    def test_the_lock_does_not_LEAK_when_the_body_raises(self):
        """A failed install must not block the next attempt.

        What this does NOT prove: that the explicit `release()` is doing the
        work. Deleting it leaves this green, because closing the file handle
        drops a `flock` on POSIX anyway — so the explicit unlock is
        defensive, not load-bearing, and I am not going to claim a mutation
        it survives. The property asserted is the one that matters to a
        caller: after a raising body, the lock is available again.
        """
        engine = self.engine
        with self.assertRaises(ValueError):
            with engine._provision_lock("1.2.3"):
                raise ValueError("boom")
        with engine._provision_lock("1.2.3", timeout=2.0):
            pass


if __name__ == "__main__":
    unittest.main()
