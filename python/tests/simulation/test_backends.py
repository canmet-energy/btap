"""Port of btap-simulation/test/test_backends.rb: the execution abstraction /
local-vs-cloud seam WITHOUT EnergyPlus — the runner prepares the dir, then
delegates to an injected backend. (The Ruby CLI-path tests have no Python
analogue: the Local backend runs the provisioned engine, not the CLI; their
replacement lives in test_engine.py.)"""

import shutil
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


class TestRunnerOwnsTheSizingContract(unittest.TestCase):
    """`run_energyplus` must set the flags itself, starting from the defaults.

    Sol's `075`: pre-setting them in a test fixture MASKS a future failure of
    exactly that runner preparation, so the fixture keeps its false defaults and
    the runner is required to prove its own contract on the SAVED `in.osm`.
    """

    @needs_sdk
    def test_run_energyplus_enables_sizing_on_the_saved_in_osm(self):
        import openstudio

        from btap._compat import opt

        model = load_fixture()
        sim = model.getSimulationControl()
        self.assertFalse(sim.doZoneSizingCalculation(), "precondition: defaults")
        self.assertFalse(sim.doSystemSizingCalculation())
        self.assertFalse(sim.doPlantSizingCalculation())

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        runner.run_energyplus(model, directory, backend=FakeBackend(self))

        saved = opt(openstudio.model.Model.load(
            openstudio.path(str(directory / "in.osm"))))
        self.assertIsNotNone(saved, "the runner must save in.osm")
        control = saved.getSimulationControl()
        self.assertTrue(control.doZoneSizingCalculation(),
                        "the runner must enable zone sizing on the saved model")
        self.assertTrue(control.doSystemSizingCalculation())
        self.assertTrue(control.doPlantSizingCalculation())


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

    def _run_dir(self, *, sizing, autosized=True):
        """A run dir as the runner would leave one.

        `autosized` adds a baseboard with an autosized capacity. Without it the
        bare fixture has NOTHING to size, and a model with nothing to size does
        not need a sizing run — the case Sol's `075` showed the first version of
        this guard wrongly refused.
        """
        import openstudio

        directory = Path(tempfile.mkdtemp())
        model = load_fixture()
        if autosized:
            baseboard = openstudio.model.ZoneHVACBaseboardConvectiveElectric(model)
            baseboard.autosizeNominalCapacity()
            zones = model.getThermalZones()
            self.assertTrue(zones, "the fixture must have a zone to attach to")
            baseboard.addToThermalZone(zones[0])
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
        for expected in ("NO sizing calculation enabled", "run_energyplus"):
            self.assertIn(expected, message,
                          "the message must say what is wrong and name the fix")
        self.assertIn("Heating Design Capacity", message,
                      "and name an actual field, so the reader can see WHY")

    @needs_sdk
    def test_remote_refuses_before_uploading_anything(self):
        """The check must precede the upload: 20 queue-minutes is a worse place
        to learn this, and a rejected run still costs a transfer."""
        directory = self._run_dir(sizing=False)
        remote = Remote(endpoint="https://example.invalid", api_key="x",
                        transport=ExplodingTransport(), poll_seconds=0)
        with self.assertRaises(RuntimeError) as caught:
            remote.execute(directory)
        self.assertIn("NO sizing calculation enabled", str(caught.exception))

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
        self.assertIn("NO sizing calculation enabled", str(caught.exception),
                      "moving the guard after the workflow branch leaves this "
                      "path unguarded — the OSM is uploaded unchanged")

    @needs_sdk
    def test_a_model_with_nothing_to_size_is_NOT_refused(self):
        """Sol's `075` finding, pinned.

        A bare model with no autosized field runs fine in EnergyPlus with all
        three flags false. The first version of this guard refused it, so its
        error text predicted a failure that does not occur and it removed a
        valid direct-backend use. The guard must stay silent here.
        """
        import openstudio

        from btap._compat import opt
        from btap.simulation.backends import _require_sizing_calculations, autosized_fields
        directory = self._run_dir(sizing=False, autosized=False)
        model = opt(openstudio.model.Model.load(
            openstudio.path(str(directory / "in.osm"))))
        workspace = openstudio.energyplus.ForwardTranslator().translateModel(model)
        self.assertEqual([], autosized_fields(workspace),
                         "the bare fixture must have nothing to size")
        _require_sizing_calculations(model, workspace, directory / "in.osm")

    @needs_sdk
    def test_an_autosized_model_has_fields_to_size(self):
        """The other half: the probe must actually detect autosizing, or the
        conditional guard is unfalsifiable by construction."""
        import openstudio

        from btap._compat import opt
        from btap.simulation.backends import autosized_fields
        directory = self._run_dir(sizing=False, autosized=True)
        model = opt(openstudio.model.Model.load(
            openstudio.path(str(directory / "in.osm"))))
        workspace = openstudio.energyplus.ForwardTranslator().translateModel(model)
        fields = autosized_fields(workspace)
        self.assertTrue(fields, "the probe must detect a real autosized field")
        self.assertTrue(any("Heating Design Capacity" in f for f in fields),
                        f"and name it: {fields}")

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
        workspace = openstudio.energyplus.ForwardTranslator().translateModel(model)
        _require_sizing_calculations(model, workspace, directory / "in.osm")

    @needs_sdk
    def test_one_enabled_flag_is_enough_for_a_zone_only_model(self):
        """Sol's `077` case 1, pinned — and the test this REPLACES asserted the
        opposite using exactly this model.

        A zone baseboard sizes fine with zone=True, system=False, plant=False;
        he verified it by running it. The old rule required all three, so it
        refused a working run, and `test_each_flag_alone_is_enough_to_trip_it`
        encoded that false requirement as if it were a contract.
        """
        import openstudio

        from btap._compat import opt
        from btap.simulation.backends import _require_sizing_calculations, autosized_fields

        directory = self._run_dir(sizing=False, autosized=True)
        model = opt(openstudio.model.Model.load(
            openstudio.path(str(directory / "in.osm"))))
        sim = model.getSimulationControl()
        sim.setDoZoneSizingCalculation(True)        # the only one this needs
        sim.setDoSystemSizingCalculation(False)
        sim.setDoPlantSizingCalculation(False)
        workspace = openstudio.energyplus.ForwardTranslator().translateModel(model)
        self.assertTrue(autosized_fields(workspace),
                        "precondition: there IS something to size")
        _require_sizing_calculations(model, workspace, directory / "in.osm")

    @needs_sdk
    def test_an_object_merely_NAMED_autosize_is_not_a_field_to_size(self):
        """Sol's `077` case 2, pinned.

        A `Building` named "Autosize" renders `Autosize,  !- Name`, which the
        whole-text token count read as a field to size — so the guard refused a
        model with nothing to size. The IDD knows that field is alpha.
        """
        import openstudio

        from btap._compat import opt
        from btap.simulation.backends import _require_sizing_calculations, autosized_fields

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        model = load_fixture()
        model.getBuilding().setName("Autosize")
        model.save(openstudio.path(str(directory / "in.osm")), True)
        saved = opt(openstudio.model.Model.load(
            openstudio.path(str(directory / "in.osm"))))
        workspace = openstudio.energyplus.ForwardTranslator().translateModel(saved)
        self.assertIn("Autosize", str(workspace),
                      "precondition: the TOKEN is present in the IDF text")
        self.assertEqual([], autosized_fields(workspace),
                         "but no NUMERIC field needs sizing")
        _require_sizing_calculations(saved, workspace, directory / "in.osm")
