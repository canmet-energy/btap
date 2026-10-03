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


class ExplodingTransport:
    """Any use at all is a test failure.

    The guard tests used `mock.Mock()`, which answers every call with another
    Mock — so when a mutation removed the guard, `Remote.execute` sailed past the
    upload and sat in `_poll` forever against a Mock that never returns a
    terminal status. Three of five mutations HUNG instead of failing, including
    the two that matter most. A mutation that hangs is not a mutation that was
    caught, so the seam's four methods now refuse rather than improvise.
    """

    def _boom(self, name):
        raise AssertionError(
            f"transport.{name} was called: the guard must refuse before "
            "anything touches the wire")

    def post_json(self, *a, **k):
        self._boom("post_json")

    def put_bytes(self, *a, **k):
        self._boom("put_bytes")

    def get_json(self, *a, **k):
        self._boom("get_json")

    def get_bytes(self, *a, **k):
        self._boom("get_bytes")


class TestSizingCalculationsGuard(unittest.TestCase):
    """A backend reached without `run_energyplus` must say so, not hand
    EnergyPlus a model that fatals 0.3s in on the first autosized component.

    All three flags default to False on a model, and `run_energyplus` is the
    only thing that enables them, so every bypass hit the same cryptic error:
    an API upload, a local sweep and an `openstudio run` OSW, in one session.
    """

    @needs_sdk
    def _run_dir(self, *, sizing):
        import openstudio

        directory = Path(tempfile.mkdtemp())
        model = load_fixture()
        if sizing:
            sim = model.getSimulationControl()
            sim.setDoZoneSizingCalculation(True)
            sim.setDoSystemSizingCalculation(True)
            sim.setDoPlantSizingCalculation(True)
        model.save(openstudio.path(str(directory / "in.osm")), True)
        return directory

    @needs_sdk
    def test_local_refuses_a_model_with_sizing_disabled(self):
        directory = self._run_dir(sizing=False)
        # An explicit nonexistent binary, so that if the guard is ever removed
        # this test fails FAST instead of falling through to
        # engine.ensure_energyplus(), which provisions EnergyPlus. Without it,
        # the mutation "remove the Local call site" hung for 36 minutes instead
        # of failing -- a test whose failure mode was a hang, not a red.
        with self.assertRaises(RuntimeError) as caught:
            Local(energyplus="/nonexistent/energyplus").execute(directory)
        message = str(caught.exception)
        for expected in ("Do Zone Sizing Calculation",
                         "Do System Sizing Calculation",
                         "Do Plant Sizing Calculation",
                         "run_energyplus"):
            self.assertIn(expected, message,
                          "the message must name the missing flags and the fix")

    @needs_sdk
    def test_remote_refuses_before_uploading_anything(self):
        """The check must precede the upload: 20 queue-minutes is a worse place
        to learn this, and a rejected run still costs a transfer."""
        directory = self._run_dir(sizing=False)
        remote = Remote(endpoint="https://example.invalid", api_key="x",
                        transport=ExplodingTransport(), poll_seconds=0)
        with self.assertRaises(RuntimeError) as caught:
            remote.execute(directory)
        self.assertIn("Do Zone Sizing Calculation", str(caught.exception))

    @needs_sdk
    def test_remote_refuses_the_openstudio_workflow_too(self):
        """`workflow_type='openstudio'` uploads in.osm unchanged, so the
        workspace-level trick `_ensure_output_requests` uses cannot cover it."""
        directory = self._run_dir(sizing=False)
        remote = Remote(endpoint="https://example.invalid", api_key="x",
                        transport=ExplodingTransport(), poll_seconds=0,
                        workflow_type="openstudio")
        with self.assertRaises(RuntimeError) as caught:
            remote.execute(directory)
        self.assertIn("Do Zone Sizing Calculation", str(caught.exception),
                      "moving the guard after the workflow branch leaves this "
                      "path unguarded — the OSM is uploaded unchanged")

    @needs_sdk
    def test_a_prepared_model_passes_the_guard(self):
        """The guard must not fire on what `run_energyplus` produces —
        otherwise it would be unfalsifiable by construction."""
        from btap.simulation.backends import _require_sizing_calculations

        directory = self._run_dir(sizing=True)
        import openstudio

        from btap._compat import opt
        model = opt(openstudio.model.Model.load(
            openstudio.path(str(directory / "in.osm"))))
        _require_sizing_calculations(model, directory / "in.osm")   # must not raise

    @needs_sdk
    def test_each_flag_alone_is_enough_to_trip_it(self):
        """One disabled flag must fail, not only all three."""
        from btap.simulation.backends import _require_sizing_calculations

        setters = ("setDoZoneSizingCalculation", "setDoSystemSizingCalculation",
                   "setDoPlantSizingCalculation")
        for omitted in setters:
            with self.subTest(omitted=omitted):
                model = load_fixture()
                sim = model.getSimulationControl()
                for setter in setters:
                    getattr(sim, setter)(setter != omitted)
                with self.assertRaises(RuntimeError):
                    _require_sizing_calculations(model, Path("in.osm"))
