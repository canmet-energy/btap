"""Port of btap-simulation/test/test_backends.rb: the execution abstraction /
local-vs-cloud seam WITHOUT EnergyPlus — the runner prepares the dir, then
delegates to an injected backend. (The Ruby CLI-path tests have no Python
analogue: the Local backend runs the provisioned engine, not the CLI; their
replacement lives in test_engine.py.)"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from btap.simulation import Backend, Local, Remote, Result, run, runner
from tests.support import load_fixture, needs_sdk


class FakeBackend(Backend):
    """Asserts the runner prepared the dir, records the call, and lands the
    two artifacts the contract requires (canned, no E+)."""

    def __init__(self, test):
        self.test = test
        self.called_with = None

    def execute(self, run_dir):
        # Contract precondition: the runner must have written in.osm + in.osw
        # BEFORE handing the dir to the backend.
        self.test.assertTrue((Path(run_dir) / "in.osm").is_file(),
                             "backend called before in.osm written")
        self.test.assertTrue((Path(run_dir) / "in.osw").is_file(),
                             "backend called before in.osw written")
        self.called_with = str(run_dir)
        out = Path(run_dir) / "run"
        out.mkdir(parents=True, exist_ok=True)
        (out / "eplusout.err").write_text("EnergyPlus Completed Successfully\n")
        (out / "eplusout.sql").write_text("")  # placeholder — no results parsed here


@needs_sdk
class TestBackends(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_dir(self, name):
        return str(Path(self.tmp.name) / name)

    def test_custom_backend_is_invoked_with_prepared_dir(self):
        model = load_fixture()
        target = self.run_dir("custom")
        fake = FakeBackend(self)

        result = runner.run_energyplus(model, target, sizing_only=True, backend=fake)

        self.assertEqual(target, fake.called_with, "backend.execute was not called with the run dir")
        self.assertTrue((Path(target) / "in.osm").is_file(), "runner did not write in.osm")
        self.assertTrue((Path(target) / "in.osw").is_file(), "runner did not write in.osw")
        self.assertEqual(str(Path(target) / "run"), result)
        self.assertTrue(runner.is_clean_run(result), "is_clean_run should read the canned err")

    def test_facade_uses_injected_backend(self):
        model = load_fixture()
        target = self.run_dir("facade")
        fake = FakeBackend(self)

        result = run(model, run_dir=target, sizing_only=True, backend=fake)

        self.assertEqual(target, fake.called_with)
        self.assertIsInstance(result, Result)
        self.assertTrue(result.is_clean())
        self.assertIsNone(result.energy, "sizing_only run has no energy results")
        self.assertIsNone(result.unmet_hours, "sizing_only run has no unmet hours")

    def test_local_is_the_default_backend(self):
        model = load_fixture()
        target = self.run_dir("default")
        called = []

        def fake_execute(backend_self, d):
            called.append(True)
            self.assertTrue((Path(d) / "in.osw").is_file(),
                            "default backend called before in.osw written")
            out = Path(d) / "run"
            out.mkdir(parents=True, exist_ok=True)
            (out / "eplusout.err").write_text("EnergyPlus Completed Successfully\n")
            (out / "eplusout.sql").write_text("")

        runner.set_default_backend(None)  # rebuild the default from scratch
        try:
            with mock.patch.object(Local, "execute", autospec=True, side_effect=fake_execute):
                runner.run_energyplus(model, target, sizing_only=True)  # no backend arg
        finally:
            runner.set_default_backend(None)

        self.assertTrue(called, "default backend was not a Local instance")

    def test_backend_base_execute_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError) as ctx:
            Backend().execute("/nope")
        self.assertIn("execute", str(ctx.exception))

    def test_remote_requires_a_prepared_directory(self):
        remote = Remote(endpoint="https://example.test", api_key="k")
        with self.assertRaises(RuntimeError) as ctx:
            remote.execute("/nope")
        self.assertIn("in.osm is missing", str(ctx.exception))

    def test_remote_without_configuration_refuses_before_touching_the_network(self):
        import os
        cleared = {k: "" for k in ("HBIX_SIM_ENDPOINT", "HBIX_API_KEY",
                                   "OS_SIM_REMOTE_ENDPOINT", "OS_SIM_REMOTE_API_KEY")}
        with mock.patch.dict(os.environ, cleared):
            with self.assertRaises(RuntimeError) as ctx:
                Remote(endpoint=None, api_key=None).execute("/nope")
            self.assertIn("not configured", str(ctx.exception))
            self.assertIn("HBIX_SIM_ENDPOINT", str(ctx.exception))
            self.assertIn("HBIX_API_KEY", str(ctx.exception))

    def test_backends_share_the_interface(self):
        self.assertIsInstance(Local(), Backend)
        self.assertIsInstance(Remote(), Backend)
        self.assertTrue(callable(Local().execute))
        self.assertTrue(callable(Remote().execute))


if __name__ == "__main__":
    unittest.main()


class TestPhaseErrorsAreReadable(unittest.TestCase):
    """The service returns STRUCTURED errors, and `_phase_errors` joined them.

    `"; ".join(errors)` raised `sequence item 0: expected str instance, dict
    found`. The damage is out of proportion to the typo, because this function
    runs only while BUILDING A FAILURE MESSAGE: a diagnosable remote failure
    became an opaque TypeError naming neither the phase nor the cause. It cost
    one real diagnosis — a remote sizing run whose actual error was
    "EnergyPlus requires a weather file (WEATHER_S3_KEY)" surfaced as a
    TypeError about dicts.

    Offline: no transport, no network.
    """

    def _remote(self):
        from btap.simulation.backends import Remote

        return Remote(endpoint="https://example.invalid", api_key="unused")

    def test_a_dict_error_is_rendered_not_raised(self):
        status = {"phases": [{"errors": [{"message": "E+ failed", "code": 7}]}]}
        self.assertEqual("E+ failed", self._remote()._phase_errors(status))

    def test_a_dict_without_a_message_keeps_its_detail(self):
        """Falling back to the mapping beats dropping the only diagnosis."""
        status = {"phases": [{"errors": [{"code": 7, "where": "translate"}]}]}
        got = self._remote()._phase_errors(status)
        self.assertIn("code", got)
        self.assertIn("translate", got)

    def test_mixed_strings_dicts_nones_and_scalars(self):
        status = {"phases": [{"errors": ["a", {"detail": "b"}, None, 12]}]}
        self.assertEqual("a; b; 12", self._remote()._phase_errors(status))

    def test_strings_still_behave_exactly_as_before(self):
        status = {"phases": [{"errors": ["boom", "again"]}]}
        self.assertEqual("boom; again", self._remote()._phase_errors(status))

    def test_no_phases_is_empty_not_an_error(self):
        for status in ({"phases": []}, {}, None):
            with self.subTest(status=status):
                self.assertEqual("", self._remote()._phase_errors(status))
