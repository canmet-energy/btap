"""The frozen-scenario runner's API-worker timeout path (post-9a review
Medium): Python hands a TimeoutExpired's partial output back as BYTES even
under text=True, so the failure path must decode before it concatenates —
and the worker runs in its own process group so a descendant (an EnergyPlus
run, in real life) does not outlive the worker that was waiting on it."""

import importlib.util
import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from tests.support import REPO_ROOT

_SPEC = importlib.util.spec_from_file_location(
    "scenario_runner", REPO_ROOT / "verification" / "scenarios" / "runner.py")
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)


class TestApiWorkerTimeout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        # A stand-in worker: prints partial output, spawns a grandchild that
        # would outlive it, then hangs past the scenario's timeout.
        self.pid_file = root / "grandchild.pid"
        worker = root / "fake_worker.py"
        worker.write_text(textwrap.dedent(f"""
            import subprocess, sys, time
            print("partial out"); print("partial err", file=sys.stderr)
            sys.stdout.flush(); sys.stderr.flush()
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            open({str(self.pid_file)!r}, "w").write(str(child.pid))
            time.sleep(60)
            """), encoding="utf-8")
        self._orig = (runner.API_WORKER, runner.python_exe)
        runner.API_WORKER = worker
        runner.python_exe = lambda: sys.executable
        self.addCleanup(self._restore)

    def _restore(self):
        runner.API_WORKER, runner.python_exe = self._orig

    def test_timeout_is_a_failed_run_with_text_streams_and_no_survivors(self):
        scenario = {"id": "timeout-probe", "kind": "api", "api_call": {},
                    "env": {}, "timeout_s": 2}
        run_dir = Path(self.tmp.name) / "run"
        run = runner._execute_api(scenario, run_dir, {})
        self.assertIsNone(run.exit_code)
        self.assertIsInstance(run.stdout, str)
        self.assertIsInstance(run.stderr, str)
        self.assertIn("partial out", run.stdout)
        self.assertIn("TIMEOUT after 2s", run.stderr)
        self.assertIn("timed out", run.observations["error"])
        # The grandchild was in the worker's process group and died with it.
        self.assertTrue(self.pid_file.is_file(), "the fake worker never started")
        pid = int(self.pid_file.read_text())
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.kill(pid, 9)
            self.fail(f"grandchild {pid} survived the worker's timeout")


if __name__ == "__main__":
    unittest.main()
