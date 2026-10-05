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
        """The exception is exactly three variables, not a widening.

        `BTAP_SCENARIO_BACKEND` joined the two credentials because the API
        path reads it INSIDE the worker — see the seam test below, which is
        what should have caught its absence.
        """
        self.assertEqual(("HBIX_API_KEY", "HBIX_SIM_ENDPOINT",
                          "BTAP_SCENARIO_BACKEND"),
                         self.runner.REMOTE_ENV_ALLOWLIST)
        for name in self.runner.REMOTE_ENV_ALLOWLIST:
            self.assertNotIn(name, self.runner.ENV_ALLOWLIST,
                             "the default set must stay offline")


class TestUnknownValueIsRefused(unittest.TestCase):
    """A typo must not silently run locally and match every baseline.

    `BTAP_SCENARIO_BACKEND=remtoe` would otherwise verify the whole corpus
    locally and report success — the typo producing the exact opposite of what
    was asked (Sol, PR #79).
    """

    def setUp(self):
        self.runner = _harness()

    def test_a_misspelling_raises_rather_than_defaulting(self):
        for value in ("remtoe", "REMOTE", "localhost", "both"):
            with self.subTest(value=value):
                with mock.patch.dict(os.environ,
                                     {"BTAP_SCENARIO_BACKEND": value}):
                    with self.assertRaises(SystemExit) as caught:
                        self.runner.scenario_backend()
                    self.assertIn(value, str(caught.exception))

    def test_the_supported_set_is_declared(self):
        self.assertEqual(("local", "remote"), self.runner.SCENARIO_BACKENDS)

    def test_the_two_supported_values_still_work(self):
        for value in self.runner.SCENARIO_BACKENDS:
            with self.subTest(value=value):
                with mock.patch.dict(os.environ,
                                     {"BTAP_SCENARIO_BACKEND": value}):
                    self.assertEqual(value, self.runner.scenario_backend())


class TestTheApiSeam(unittest.TestCase):
    """build_env -> api_worker._select_backend -> set_default_backend(Remote).

    THE EXECUTED SEAM, not a helper's return value. The previous version of
    this class called `runner.build_env(...)` and asserted what the returned
    dict contained — so deleting the worker's `_select_backend()` call, or
    changing its guard to skip `"remote"`, left all 17 tests green while both
    annual API scenarios ran LOCALLY and the run claimed remote verification.
    Sol found that, and I reproduced it: with the call removed the suite still
    passed 17/17.

    That is the seventh time in this session I wrote a check that models a
    property instead of exercising it — and this one was written IN RESPONSE
    to Sol finding the same seam untested. So these tests run the worker's own
    selection against the environment the harness actually hands it, with a
    fake `Remote`, and the mutations below are the evidence.
    """

    def setUp(self):
        self.runner = _harness()
        self.worker = self._worker_module()

    def _worker_module(self):
        """`api_worker` loaded the way the harness invokes it."""
        import importlib.util

        path = SCENARIOS / "api_worker.py"
        spec = importlib.util.spec_from_file_location("api_worker_seam", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        return module

    def _select_with(self, parent_env):
        """Run the WORKER's selection under the env the harness would pass.

        Returns the backend `set_default_backend` received, or None.
        """
        from unittest import mock

        with mock.patch.dict(os.environ, parent_env, clear=False):
            if "BTAP_SCENARIO_BACKEND" not in parent_env:
                os.environ.pop("BTAP_SCENARIO_BACKEND", None)
            env = self.runner.build_env({"kind": "api"}, {})

        installed = []

        class FakeRemote:
            def __init__(self, *a, **k):
                pass

            def is_configured(self):
                return True

        import btap.simulation
        import btap.simulation.runner as product_runner

        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(btap.simulation, "Remote", FakeRemote):
                with mock.patch.object(product_runner, "set_default_backend",
                                       installed.append):
                    self.worker._select_backend()
        return installed[0] if installed else None

    def test_the_worker_INSTALLS_a_remote_backend(self):
        """The whole point: the env the harness passes must make the worker
        call `set_default_backend`."""
        installed = self._select_with({"BTAP_SCENARIO_BACKEND": "remote",
                                       "HBIX_API_KEY": "k",
                                       "HBIX_SIM_ENDPOINT": "https://x"})
        self.assertIsNotNone(
            installed,
            "the worker did not install a backend — the API path would run "
            "LOCALLY while the run claims remote verification")
        self.assertEqual("FakeRemote", type(installed).__name__)

    def test_the_worker_MAIN_invokes_the_selection(self):
        """THE CALL SITE. Calling `_select_backend()` from a test proves the
        function works, not that `main()` runs it.

        Sol's probe is precisely this: delete the call from `main()` and the
        suite stays green while both annual API scenarios run locally. My
        rewrite of this class still survived that mutation, because every test
        invoked the helper directly — the eighth time in this session I tested
        a function instead of its caller. So this drives `main()` with a real
        call file and a stubbed pipeline, and asserts the backend was
        installed.
        """
        import json as _json
        import shutil
        import tempfile
        from unittest import mock

        installed = []

        class FakeRemote:
            def __init__(self, *a, **k):
                pass

            def is_configured(self):
                return True

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        call = directory / "call.json"
        call.write_text(_json.dumps({"code": "necb2020",
                                     "simulate": "none"}), encoding="utf-8")
        run_dir = directory / "run"

        import btap.simulation
        import btap.simulation.runner as product_runner

        with mock.patch.dict(os.environ,
                             {"BTAP_SCENARIO_BACKEND": "remote",
                              "HBIX_API_KEY": "k",
                              "HBIX_SIM_ENDPOINT": "https://x"}, clear=False):
            with mock.patch.object(btap.simulation, "Remote", FakeRemote):
                with mock.patch.object(product_runner, "set_default_backend",
                                       installed.append):
                    # stub the pipeline: this test is about the selection
                    with mock.patch.object(self.worker, "run",
                                           lambda call, out: {"ok": True}):
                        code = self.worker.main(
                            ["api_worker", str(call), str(run_dir)])

        self.assertEqual(0, code,
                         f"the worker failed: "
                         f"{(run_dir / 'observations.json').read_text()[:300]
                            if (run_dir / 'observations.json').exists() else ''}")
        self.assertEqual(
            1, len(installed),
            "main() did not install a backend — deleting its "
            "_select_backend() call must fail this test")

    def test_the_worker_installs_NOTHING_by_default(self):
        self.assertIsNone(self._select_with({"HBIX_API_KEY": "k"}),
                          "the default must leave the product's backend alone")

    def test_an_unconfigured_remote_refuses_rather_than_running_locally(self):
        """Silently falling back to local would be the same false claim."""
        from unittest import mock

        class Unconfigured:
            def __init__(self, *a, **k):
                pass

            def is_configured(self):
                return False

        import btap.simulation

        with mock.patch.dict(os.environ,
                             {"BTAP_SCENARIO_BACKEND": "remote"}, clear=True):
            with mock.patch.object(btap.simulation, "Remote", Unconfigured):
                with self.assertRaises(SystemExit) as caught:
                    self.worker._select_backend()
        self.assertIn("not configured", str(caught.exception))

    def test_the_credentials_reach_the_worker_env(self):
        """Still worth asserting, but it is no longer the whole test."""
        from unittest import mock

        with mock.patch.dict(os.environ,
                             {"BTAP_SCENARIO_BACKEND": "remote",
                              "HBIX_API_KEY": "k",
                              "HBIX_SIM_ENDPOINT": "https://x"}):
            env = self.runner.build_env({"kind": "api"}, {})
        self.assertEqual("k", env.get("HBIX_API_KEY"))
        self.assertEqual("https://x", env.get("HBIX_SIM_ENDPOINT"))
        self.assertEqual("remote", env.get("BTAP_SCENARIO_BACKEND"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
