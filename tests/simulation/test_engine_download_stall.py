"""A stalled download must not hold the provision lock forever (issue #105).

`urlopen` with no timeout blocks indefinitely on a socket that accepts and
then stops delivering. It is called INSIDE `_provision_lock`, so every other
process waits the full `PROVISION_LOCK_TIMEOUT_S` and is then told that a live
holder exists and should be found and stopped — true, and useless, because the
holder is alive and stuck on a socket with no diagnosis of its own.

These drive a REAL stalled server rather than patching the timeout in, because
the defect was the absence of an argument and a mock that asserts the argument
would pass against a `urlopen` call that ignored it.
"""

import socket
import threading
import time
import unittest
from pathlib import Path

from btap.simulation import engine
from btap.simulation.engine import EngineError


class StalledServer:
    """Accepts a connection, sends headers, then never sends a body."""

    def __init__(self, *, send_headers=True):
        self._send_headers = send_headers
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._held = []
        # Guards `_held` AND lets a test WAIT for accepts instead of assuming
        # them. A connection being MADE is not a connection being ACCEPTED:
        # the kernel completes TCP from the listen backlog, so the client can
        # connect, send, and time out before `accept()` returns — and
        # `thread.join()` in `BoundedFetch` synchronises the FETCH thread's
        # writes, not this one's. Reading `len(_held)` straight after the
        # fetch therefore measured scheduling latency, not an ordering, and
        # Fable made it fail on CORRECT product code by delaying `accept()`
        # by 0.6 s (`305` follow-up).
        self._accepted = threading.Condition()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with self._accepted:
                self._held.append(conn)
                self._accepted.notify_all()
            try:
                conn.recv(4096)
                if self._send_headers:
                    # A content length we never satisfy, so the client blocks
                    # in read() rather than seeing a clean EOF.
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Length: 1048576\r\n"
                        b"\r\n")
            except OSError:
                pass

    def wait_for_connections(self, count, timeout=2.0):
        """Block until `count` connections have been ACCEPTED, or give up.

        Returns the count seen, so the caller asserts on a settled number.
        The bounded wait closes the UNDER-count race without hiding a missing
        retry, which still shows as the wrong number once the wait expires.

        2.0 s is not a multiple of the stall timeout and must not be tied to
        it: the wait begins AFTER the fetch has returned, so it never overlaps
        a stall and covers only the accept thread's scheduling latency for
        connections already in the backlog. It costs nothing on the pass path
        (Fable, `305`).

        One residual window, documented rather than closed: `wait_for` returns
        at `>= count`, so a `count + 1`-th connection not yet accepted at that
        instant is invisible — the mirror race on the OVER-count side. No
        plausible mutation produces extra connections, because the loop bound
        is the pinned constant.
        """
        with self._accepted:
            self._accepted.wait_for(
                lambda: len(self._held) >= count, timeout)
            return len(self._held)

    def url(self, path="/stalls.tar.gz"):
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self):
        self._stop.set()
        for conn in self._held:
            try:
                conn.close()
            except OSError:
                pass
        try:
            # `close()` alone does NOT wake a thread blocked in `accept()` on
            # Linux, so every instance leaked a daemon thread and left its
            # port in LISTEN for the worker's lifetime. `shutdown` raises
            # ENOTCONN on an idle listener on some kernels (Fable, `305` F2).
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(2.0)


class BoundedFetch(unittest.TestCase):
    """Every test that drives a REAL stalling server inherits this.

    Calling `_fetch_with_stall_timeout` directly means that dropping the
    timeout argument HANGS the test instead of failing it — the original
    defect reproduced inside the suite, where nobody attributes it. The first
    version of this file fixed that for one test and then reintroduced it in
    two more as tests were added; the budget now lives in one place so a new
    test cannot forget it.
    """

    FETCH_BUDGET_S = 10.0

    def fetch(self, url, budget_s=None):
        """Run the fetch in a thread, returning its outcome or failing."""
        import tempfile

        budget = self.FETCH_BUDGET_S if budget_s is None else budget_s
        box = {}

        def run():
            with tempfile.TemporaryDirectory() as d:
                dest = Path(d) / "archive"
                try:
                    engine._fetch_with_stall_timeout(url, dest)
                    box["outcome"] = "returned"
                    box["bytes"] = dest.read_bytes() if dest.exists() else b""
                except BaseException as e:  # noqa: BLE001 - reported below
                    box["outcome"] = e

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(budget)
        self.assertFalse(
            thread.is_alive(),
            f"the fetch did not return within {budget:.0f}s against a "
            "stalled server — this is the issue-105 defect itself: a socket "
            "with no timeout, blocking while the provision lock is held")
        return box


class TestAStalledDownloadIsBounded(BoundedFetch):
    def setUp(self):
        self.server = StalledServer()
        self.addCleanup(self.server.close)
        # Short enough to run as a test, exercising the SAME code path.
        self._timeout = engine.DOWNLOAD_STALL_TIMEOUT_S
        self._attempts = engine.DOWNLOAD_ATTEMPTS
        engine.DOWNLOAD_STALL_TIMEOUT_S = 0.4
        engine.DOWNLOAD_ATTEMPTS = 2
        self.addCleanup(self._restore)

    def _restore(self):
        engine.DOWNLOAD_STALL_TIMEOUT_S = self._timeout
        engine.DOWNLOAD_ATTEMPTS = self._attempts

    def test_a_stalled_socket_RAISES_instead_of_blocking(self):
        outcome = self.fetch(self.server.url())["outcome"]
        self.assertIsInstance(
            outcome, EngineError,
            f"a stalled download must raise, got {outcome!r}")

        message = str(outcome)
        self.assertIn("STALLED", message,
                      "the holder must name the stall, not blame TLS "
                      "interception as the generic OSError path does")
        self.assertIn(self.server.url(), message,
                      "the holder's own error must name the URL, so a stuck "
                      "provision is diagnosable without reading the waiters")
        self.assertIn("provision lock", message,
                      "the message must connect the stall to the lock that "
                      "made every other process wait 900s")

    def test_the_retry_budget_is_bounded_WELL_INSIDE_the_lock_timeout(self):
        """ONE holder on a ZERO-progress socket fails well before the waiters.

        The lock is held for every attempt, so if attempts x timeout reached
        `PROVISION_LOCK_TIMEOUT_S` the fix would reintroduce the symptom with
        extra steps.

        TWO LIMITS this does NOT guarantee, named because the first version of
        this test was called "cannot outlast the provision lock" and that
        overstated it (Fable, `305` F5):

        - WAITERS SERIALISE THEIR OWN RETRIES. When the holder fails at 180 s
          it releases; the next waiter acquires, re-checks the empty cache and
          runs its own 3 x 60 s. Waiter k acquires at 180k s against its own
          900 s deadline, so on a hard-down network with 8 concurrent
          processes — `PYTEST_XDIST_AUTO_NUM_WORKERS=8` — workers 6 and later
          STILL get "there IS a live holder". A bound for N waiters would be
          `N x attempts x timeout < lock`, about 37 s per attempt at 8
          workers. Not taken: by then the holder has produced its own named
          error, which is what #105 was actually about;
        - A TRICKLING SOCKET IS UNBOUNDED. One byte every 59 s never trips a
          60 s per-read timeout, so a malicious or pathological peer can hold
          the lock indefinitely. Bounding that needs a total-transfer budget,
          which is the thing deliberately NOT built here because it would
          abort honest slow networks.
        """
        self._restore()  # assert on the SHIPPED values, not the test's
        worst_case = engine.DOWNLOAD_STALL_TIMEOUT_S * engine.DOWNLOAD_ATTEMPTS

        self.assertLess(
            worst_case, engine.PROVISION_LOCK_TIMEOUT_S / 2.0,
            f"a stalled download can hold the lock for {worst_case:.0f}s "
            f"against a {engine.PROVISION_LOCK_TIMEOUT_S:.0f}s lock timeout; "
            "the holder must fail well before the waiters give up")


class TestAStallIsCaughtInEVERYPHASE(BoundedFetch):
    """The timeout is phase-dependent and the catch must cover both shapes.

    `AbstractHTTPHandler.do_open` wraps `h.request()` in
    `except OSError: raise URLError(err)` and leaves `h.getresponse()`
    outside it. So a stall during TCP connect or the TLS handshake arrives as
    `URLError(reason=TimeoutError)` and a stall before headers or mid-body
    arrives raw. Catching only the raw form gave the first two ONE attempt and
    the TLS-interception message — and the handshake case is precisely what an
    intercepting corporate proxy produces (Fable, `305` F1).
    """

    def setUp(self):
        # send_headers=False: it must answer the ClientHello with SILENCE.
        # Replying with HTTP bytes makes TLS fail fast on WRONG_VERSION_NUMBER
        # instead of stalling, which tests the wrong thing.
        self.server = StalledServer(send_headers=False)
        self.addCleanup(self.server.close)
        self._timeout = engine.DOWNLOAD_STALL_TIMEOUT_S
        self._attempts = engine.DOWNLOAD_ATTEMPTS
        engine.DOWNLOAD_STALL_TIMEOUT_S = 0.4
        engine.DOWNLOAD_ATTEMPTS = 2
        self.addCleanup(self._restore)

    def _restore(self):
        engine.DOWNLOAD_STALL_TIMEOUT_S = self._timeout
        engine.DOWNLOAD_ATTEMPTS = self._attempts

    def test_a_HANDSHAKE_phase_stall_is_a_stall_not_a_TLS_problem(self):
        """`https://` to a socket that never answers ClientHello.

        This is the phase the raw-only catch missed. The server is the same
        plain socket; speaking TLS to it means the handshake never completes,
        which is what a proxy that swallows the connection does.
        """
        url = f"https://127.0.0.1:{self.server.port}/stalls.tar.gz"
        outcome = self.fetch(url)["outcome"]
        self.assertIsInstance(
            outcome, EngineError,
            f"a handshake stall must raise EngineError, got {outcome!r}")

        message = str(outcome)
        self.assertIn("STALLED", message,
                      "a handshake stall must be reported as a stall; before "
                      "the URLError branch it got the TLS-interception text, "
                      "which sends the reader after the wrong cause")
        self.assertIn("provision lock", message)
        # NOT `assertIn(str(DOWNLOAD_ATTEMPTS), message)`: "2" occurs in
        # `127.0.0.1`, so that assertion was satisfied by a ONE-attempt
        # message and proved nothing (Fable, `305` follow-up). Count the
        # connections the server actually accepted instead.
        seen = self.server.wait_for_connections(engine.DOWNLOAD_ATTEMPTS)
        self.assertEqual(
            engine.DOWNLOAD_ATTEMPTS, seen,
            "a handshake stall must be RETRIED like any other stall; the "
            f"server accepted {seen} connection(s) where "
            f"{engine.DOWNLOAD_ATTEMPTS} were expected")


class TestEachAttemptTRUNCATES(BoundedFetch):
    """A retry must not append to the previous attempt's bytes.

    `"wb"` -> `"ab"` passes the whole suite otherwise (Fable, `305` F4). The
    sha256 check would catch the corruption eventually, but it reports
    "tampered or truncated engine", which names the wrong cause and discards
    a download that was merely retried badly.
    """

    def setUp(self):
        self._timeout = engine.DOWNLOAD_STALL_TIMEOUT_S
        self._attempts = engine.DOWNLOAD_ATTEMPTS
        engine.DOWNLOAD_STALL_TIMEOUT_S = 0.4
        engine.DOWNLOAD_ATTEMPTS = 3
        self.addCleanup(self._restore)

    def _restore(self):
        engine.DOWNLOAD_STALL_TIMEOUT_S = self._timeout
        engine.DOWNLOAD_ATTEMPTS = self._attempts

    def test_a_partial_attempt_leaves_NOTHING_behind(self):
        # DERIVED from `shutil.COPY_BUFSIZE`, never hardcoded. `copyfileobj`
        # asks `read(COPY_BUFSIZE)` and `BufferedReader` loops raw recvs to
        # fill it, so a stall inside that loop discards everything it had
        # pulled along with the exception and NOTHING reaches the file. The
        # partial must therefore exceed one whole buffer to force a real
        # write before the stall — and the buffer is 64 KiB on Linux but
        # 1 MiB on Windows, where the engine also provisions. A hardcoded
        # 120 KB partial exceeded the Linux buffer and NOT the Windows one,
        # so `"ab"` failed here and passed there: the test silently stopped
        # discriminating on the platform nobody runs it on (Fable, `305`
        # follow-up, confirmed by simulating the larger buffer).
        import shutil

        buffer_size = shutil.COPY_BUFSIZE
        body = b"X" * (buffer_size * 3)
        partial = b"Y" * (buffer_size * 3 // 2)
        self.assertGreaterEqual(
            len(partial), buffer_size,
            "the partial must exceed one copy buffer or this test cannot "
            "tell truncation from appending — refusing rather than passing")
        state = {"n": 0}
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        port = sock.getsockname()[1]
        self.addCleanup(sock.close)

        def handle(conn, n):
            try:
                conn.recv(4096)
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: "
                    + str(len(body)).encode() + b"\r\n\r\n")
                if n == 1:
                    conn.sendall(partial)       # a FULL copy buffer, then stall
                    time.sleep(5.0)
                else:
                    conn.sendall(body)          # the real thing
                conn.close()
            except OSError:
                pass

        def serve():
            # ONE THREAD PER CONNECTION. A serial accept loop cannot serve
            # attempt 2 while attempt 1's handler is still sleeping out its
            # stall, so the test hung on its own fixture and then failed.
            while True:
                try:
                    conn, _ = sock.accept()
                except OSError:
                    return
                state["n"] += 1
                worker = threading.Thread(
                    target=handle, args=(conn, state["n"]), daemon=True)
                worker.start()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()

        box = self.fetch(f"http://127.0.0.1:{port}/a.tar.gz")
        self.assertEqual("returned", box["outcome"],
                         f"the retry should have succeeded: {box['outcome']!r}")
        written = box["bytes"]

        self.assertGreaterEqual(state["n"], 2, "the first attempt must stall")
        self.assertEqual(
            body, written,
            f"the retry appended instead of truncating: got {len(written)} "
            f"bytes where {len(body)} were expected")


class TestTheShippedTimeoutIsUSABLE(unittest.TestCase):
    """The behavioural tests patch the constant, so none of them sees the
    SHIPPED value. `DOWNLOAD_STALL_TIMEOUT_S = None` restores the original
    defect — `urlopen(timeout=None)` blocks forever — and passed every test
    in this file, tripping only the budget test's arithmetic as a `TypeError`
    about NoneType (Fable, `305` Q3). Asserted here for the right reason.

    This replaces a test that grepped `inspect.getsource` for the keyword.
    That one detected nothing the behavioural test did not already catch, and
    missed `None`, a second untimed `urlopen` elsewhere, and any
    reformatting — the proxy-for-the-target pattern from `303`.
    """

    def test_the_shipped_timeout_is_a_positive_finite_number(self):
        import math

        value = engine.DOWNLOAD_STALL_TIMEOUT_S
        self.assertIsInstance(value, (int, float))
        self.assertNotIsInstance(value, bool)
        self.assertTrue(math.isfinite(value),
                        f"a non-finite timeout ({value!r}) blocks forever, "
                        "which is the defect this module exists to prevent")
        self.assertGreater(value, 0.0)

    def test_the_shipped_attempt_count_is_a_positive_int(self):
        self.assertIsInstance(engine.DOWNLOAD_ATTEMPTS, int)
        self.assertNotIsInstance(engine.DOWNLOAD_ATTEMPTS, bool)
        self.assertGreaterEqual(
            engine.DOWNLOAD_ATTEMPTS, 1,
            "zero attempts would skip the download and fall through to the "
            "sha256 check on an empty file")


class TestOnlyASTALLIsTreatedAsOne(unittest.TestCase):
    """The catch must not widen into "any URLError is a stall".

    Catching `URLError` WITHOUT unwrapping `reason` passes the whole suite
    (Fable's `m6`), and would retry a 404 three times and then report it as a
    stall — advice that sends the reader looking for a network problem that is
    not there.
    """

    def setUp(self):
        self._timeout = engine.DOWNLOAD_STALL_TIMEOUT_S
        self._attempts = engine.DOWNLOAD_ATTEMPTS
        engine.DOWNLOAD_STALL_TIMEOUT_S = 0.4
        engine.DOWNLOAD_ATTEMPTS = 2
        self.addCleanup(self._restore)

    def _restore(self):
        engine.DOWNLOAD_STALL_TIMEOUT_S = self._timeout
        engine.DOWNLOAD_ATTEMPTS = self._attempts

    def test_a_NON_timeout_URLError_is_re_raised_not_called_a_stall(self):
        import tempfile
        import urllib.error

        calls = []
        real = engine.urllib.request.urlopen

        def refusing(*a, **kw):
            calls.append(kw.get("timeout"))
            raise urllib.error.URLError(OSError("connection refused"))

        engine.urllib.request.urlopen = refusing
        self.addCleanup(setattr, engine.urllib.request, "urlopen", real)

        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(urllib.error.URLError):
                engine._fetch_with_stall_timeout(
                    "http://127.0.0.1:1/never", Path(d) / "archive")

        self.assertEqual(
            1, len(calls),
            "a non-timeout URLError must NOT be retried as though it were a "
            f"stall; it was attempted {len(calls)} times")
        self.assertEqual(
            [engine.DOWNLOAD_STALL_TIMEOUT_S], calls,
            "and the timeout keyword must reach the call — this observes the "
            "CALL rather than grepping the source for it")


class TestTheRemoteTransportIsAlsoTimed(unittest.TestCase):
    """`backends.Http._request` was the SIBLING of issue #105.

    The module had exactly two untimed `urlopen` calls; fixing one and leaving
    the other is how the defect existed in the first place. Nothing imports
    `backends.Http` in the suite — `test_remote.py` drives a fake transport —
    so the new timeout had no witness at all (Fable, `305` follow-up).

    Note `Http.__init__`'s default binds at IMPORT, so patching
    `backends.HTTP_STALL_TIMEOUT_S` does not reach an instance built
    afterwards. These assert the instance's own value and the call's kwarg,
    which is what actually reaches the socket.
    """

    def test_the_default_transport_passes_its_timeout_to_urlopen(self):
        import urllib.request

        from btap.simulation import backends

        seen = {}
        real = urllib.request.urlopen

        class FakeResponse:
            status = 200

            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def recording(req, *a, **kw):
            seen["timeout"] = kw.get("timeout", "ABSENT")
            return FakeResponse()

        urllib.request.urlopen = recording
        self.addCleanup(setattr, urllib.request, "urlopen", real)

        http = backends.Http(api_key=None)
        http.get_json("http://127.0.0.1:1/status")

        self.assertEqual(
            http._timeout, seen["timeout"],
            "the transport must pass ITS OWN timeout to urlopen; "
            f"got {seen['timeout']!r}")
        self.assertIsInstance(seen["timeout"], (int, float))
        self.assertGreater(
            seen["timeout"], 0.0,
            "an absent or zero timeout is the issue-105 defect in the "
            "remote transport rather than the engine download")

    def test_the_shipped_transport_timeout_is_bounded_by_its_callers(self):
        """60 s is right because outer bounds exist, not because it was reused.

        `_with_retry` makes five attempts with 1/2/4/8 s backoff and `_poll`
        honours a `timeout_seconds` deadline — an UNTIMED socket meant neither
        was ever reached. The socket bound only has to stay well inside them.
        """
        import math

        from btap.simulation import backends

        value = backends.HTTP_STALL_TIMEOUT_S
        self.assertTrue(math.isfinite(value) and value > 0.0)
        self.assertLess(
            value * 5, 3600.0,
            "five retried attempts at this bound must stay inside the "
            "default poll deadline, or a dead socket outlasts the thing "
            "meant to catch it")
