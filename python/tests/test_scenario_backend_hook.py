"""The scenario harness's backend selection, and the guard on freezing.

Local verification is governed by memory, not correctness: SDK workers plus
EnergyPlus runs took the 32 GB VM down on 2026-09-08, so a re-freeze collides
with anyone else's test run — it did, with Sol, on 2026-10-04. Running the
corpus on the hbix service removes that, and the measurement supports it: 112
annual runs in 270 s wall at peak concurrency 112, latency flat from 1 job to
112, and 14/16 sample models agreeing with local output to 0.000%.

The contract this pins is the SPLIT, which is what makes the capability safe:

* **verifying** against existing baselines may run remote — it changes nothing
  about what they attest;
* **freezing** may not — a baseline records the OpenStudio build that produced
  it, and a remote-produced freeze would attest to the service's stack instead.
  That is a freeze-contract question for Sol, so `freeze.py` refuses it rather
  than leaving the offline guarantee to whoever remembers.

Offline: nothing here runs a scenario or touches the network.
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SCENARIOS = Path(__file__).resolve().parents[2] / "verification" / "scenarios"


def _harness():
    """The harness modules, imported the way their own scripts do."""
    if str(SCENARIOS) not in sys.path:
        sys.path.insert(0, str(SCENARIOS))
    runner = importlib.import_module("runner")
    return importlib.reload(runner)


class TestBackendSelection(unittest.TestCase):
    def setUp(self):
        self.runner = _harness()

    def test_the_default_is_local(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BTAP_SCENARIO_BACKEND", None)
            self.assertEqual("local", self.runner.scenario_backend())

    def test_an_empty_value_is_local_not_empty(self):
        for value in ("", "   "):
            with self.subTest(value=repr(value)):
                with mock.patch.dict(os.environ,
                                     {"BTAP_SCENARIO_BACKEND": value}):
                    self.assertEqual("local", self.runner.scenario_backend())

    def test_remote_is_honoured(self):
        with mock.patch.dict(os.environ, {"BTAP_SCENARIO_BACKEND": "remote"}):
            self.assertEqual("remote", self.runner.scenario_backend())


class TestEnvIsolation(unittest.TestCase):
    """HBIX credentials reach a subprocess ONLY when remote is asked for.

    The allowlist excluded them outright, because a frozen scenario must be
    reproducible offline — the same reason the geometry gem stays SDK-only
    (D-71, D-72). Making the exception conditional preserves that default by
    construction; this pins both directions.
    """

    def setUp(self):
        self.runner = _harness()

    def test_credentials_do_NOT_leak_on_the_default_backend(self):
        with mock.patch.dict(os.environ, {"HBIX_API_KEY": "secret",
                                          "HBIX_SIM_ENDPOINT": "https://x"}):
            os.environ.pop("BTAP_SCENARIO_BACKEND", None)
            env = self.runner._base_env()
        self.assertNotIn("HBIX_API_KEY", env,
                         "an offline scenario must not inherit the key")
        self.assertNotIn("HBIX_SIM_ENDPOINT", env)

    def test_credentials_reach_the_subprocess_under_remote(self):
        with mock.patch.dict(os.environ, {"HBIX_API_KEY": "secret",
                                          "HBIX_SIM_ENDPOINT": "https://x",
                                          "BTAP_SCENARIO_BACKEND": "remote"}):
            env = self.runner._base_env()
        self.assertEqual("secret", env.get("HBIX_API_KEY"),
                         "remote cannot configure itself without the key")
        self.assertEqual("https://x", env.get("HBIX_SIM_ENDPOINT"))

    def test_nothing_else_was_added_to_the_allowlist(self):
        """The exception is exactly two variables, not a widening."""
        self.assertEqual(("HBIX_API_KEY", "HBIX_SIM_ENDPOINT"),
                         self.runner.REMOTE_ENV_ALLOWLIST)
        for name in self.runner.REMOTE_ENV_ALLOWLIST:
            self.assertNotIn(name, self.runner.ENV_ALLOWLIST,
                             "the default set must stay offline")


class TestCliThreading(unittest.TestCase):
    """`--backend remote` is threaded, not reinvented.

    The product already owns backend selection, so the harness passes the
    existing flag through.
    """

    def setUp(self):
        self.runner = _harness()

    def _argv_for(self, backend, scenario_argv):
        captured = {}

        class Proc:
            returncode, stdout, stderr = 0, "", ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return Proc()

        scenario = {"argv": scenario_argv, "env": {}}
        with mock.patch.dict(os.environ, {"BTAP_SCENARIO_BACKEND": backend}):
            with mock.patch.object(self.runner.subprocess, "run", fake_run):
                self.runner._execute_cli(scenario, Path("/tmp"), {})
        return captured["cmd"]

    def test_local_adds_nothing(self):
        cmd = self._argv_for("local", ["--city", "toronto"])
        self.assertNotIn("--backend", cmd,
                         "the default must leave the invocation untouched")

    def test_remote_appends_the_product_flag(self):
        cmd = self._argv_for("remote", ["--city", "toronto"])
        self.assertIn("--backend", cmd)
        self.assertEqual("remote", cmd[cmd.index("--backend") + 1])

    def test_a_scenario_that_sets_its_own_backend_wins(self):
        """A scenario authored with an explicit backend is not overridden."""
        cmd = self._argv_for("remote", ["--backend", "local", "--city", "t"])
        self.assertEqual(1, cmd.count("--backend"),
                         "the harness must not append a second --backend")
        self.assertEqual("local", cmd[cmd.index("--backend") + 1])


class TestFreezeRefusesRemote(unittest.TestCase):
    """The guard that keeps the freeze contract intact.

    Without it the capability's first accidental use is a committed baseline
    attesting to a stack nobody chose.
    """

    def test_freeze_source_refuses_a_non_local_backend(self):
        source = (SCENARIOS / "freeze.py").read_text(encoding="utf-8")
        self.assertIn("scenario_backend()", source,
                      "freeze.py must consult the selector")
        self.assertIn("a freeze may only run on the", source,
                      "and refuse with a message naming the reason")

    def test_freezing_remote_dies_before_any_work(self):
        import subprocess

        env = dict(os.environ, BTAP_SCENARIO_BACKEND="remote")
        proc = subprocess.run(
            [sys.executable, str(SCENARIOS / "freeze.py")],
            capture_output=True, text=True, env=env, timeout=120)
        self.assertNotEqual(0, proc.returncode,
                            "a remote freeze must fail, not proceed")
        combined = proc.stdout + proc.stderr
        self.assertIn("may only run on the local backend", combined)
        self.assertNotIn("frozen 45 scenarios", combined,
                         "it must refuse BEFORE doing the work")


if __name__ == "__main__":
    unittest.main(verbosity=2)
