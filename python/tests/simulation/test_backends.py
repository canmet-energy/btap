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

    def _plant_run_dir(self):
        """A run dir whose model PROVOKES a real SDK plant-sizing advisory.

        Zone sizing on, plant sizing off, and an autosized boiler on a pumped
        hot-water loop with a scheduled setpoint — the partial-flag case Sol
        validated end to end. The point is that the translator emits a NONEMPTY
        advisory list, which `_run_dir(sizing=True)` does not.
        """
        import openstudio

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        model = load_fixture()
        loop = openstudio.model.PlantLoop(model)
        boiler = openstudio.model.BoilerHotWater(model)
        boiler.autosizeNominalCapacity()
        loop.addSupplyBranchForComponent(boiler)
        openstudio.model.PumpVariableSpeed(model).addToNode(loop.supplyInletNode())
        schedule = openstudio.model.ScheduleConstant(model)
        schedule.setValue(82.0)
        openstudio.model.SetpointManagerScheduled(model, schedule).addToNode(
            loop.supplyOutletNode())
        coil = openstudio.model.CoilHeatingWaterBaseboard(model)
        baseboard = openstudio.model.ZoneHVACBaseboardConvectiveWater(
            model, model.alwaysOnDiscreteSchedule(), coil)
        baseboard.addToThermalZone(model.getThermalZones()[0])
        loop.addDemandBranchForComponent(coil)
        control = model.getSimulationControl()
        control.setDoZoneSizingCalculation(True)       # partial: plant is OFF
        control.setDoSystemSizingCalculation(False)
        control.setDoPlantSizingCalculation(False)
        model.save(openstudio.path(str(directory / "in.osm")), True)
        (directory / "in.osw").write_text("{}", encoding="utf-8")
        return directory

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
    def test_a_field_a_sibling_METHOD_steers_away_from_is_not_to_be_sized(self):
        """Fable's L1, pinned. The guard refused a run EnergyPlus completes.

        With `Heating Design Capacity Method = CapacityPerFloorArea`, EnergyPlus
        reads `Heating Design Capacity Per Floor Area` and never evaluates
        `Heating Design Capacity`, which OpenStudio leaves `Autosize`. The field
        is autosized, inert, and needs no sizing run. Reachable through seven
        documented SDK classes, and `isHeatingDesignCapacityAutosized()` returns
        True — so the SDK's own predicate would have made the same mistake.
        """
        import openstudio

        from btap.simulation.backends import autosized_fields

        model = load_fixture()
        baseboard = openstudio.model.ZoneHVACBaseboardRadiantConvectiveElectric(model)
        baseboard.setHeatingDesignCapacityMethod("CapacityPerFloorArea")
        baseboard.setHeatingDesignCapacityPerFloorArea(50.0)
        baseboard.addToThermalZone(model.getThermalZones()[0])
        self.assertTrue(baseboard.isHeatingDesignCapacityAutosized(),
                        "precondition: the SDK still calls the field autosized")
        workspace = openstudio.energyplus.ForwardTranslator().translateModel(model)
        self.assertEqual([], autosized_fields(workspace),
                         "a field the method steers away from is not to be sized")

    @needs_sdk
    def test_the_METHOD_cases_that_DO_need_sizing_still_count(self):
        """The inverse, so the skip cannot become a blanket exemption.

        `HeatingDesignCapacity` selects the autosized field, and
        `FractionOfAutosizedHeatingCapacity` takes a fraction OF the autosized
        result — both need a sizing run.
        """
        import openstudio

        from btap.simulation.backends import autosized_fields

        for method in ("HeatingDesignCapacity",
                       "FractionOfAutosizedHeatingCapacity"):
            with self.subTest(method=method):
                model = load_fixture()
                baseboard = openstudio.model.ZoneHVACBaseboardRadiantConvectiveElectric(
                    model)
                baseboard.setHeatingDesignCapacityMethod(method)
                baseboard.addToThermalZone(model.getThermalZones()[0])
                workspace = openstudio.energyplus.ForwardTranslator().translateModel(
                    model)
                self.assertTrue(autosized_fields(workspace),
                                f"{method} needs a sizing run")

    @needs_sdk
    def test_BOTH_backends_SURFACE_a_real_advisory_as_a_warning(self):
        """The wiring carrying real content, through each backend entry path.

        Two earlier versions of this were vacuous. The first called
        `_require_sizing_calculations` directly, proving the helper and not the
        wiring. The second went through the backends but used a fixture with
        zone sizing ENABLED, so the translator produced ZERO advisories and the
        assertion — argument 4 is a list — accepted `[]`. Sol falsified it by
        discarding the advisory list only when called from `Local.execute` or
        `Remote._prepare_payload`: both tests still passed while the real boiler
        case would have gone silent (`079`).

        So this asserts a NONEMPTY `DoPlantSizingCalculation` advisory reaches a
        Python warning through each real backend path. The engine and transport
        fail AFTER the warning, which is why the failure is allowed — but only
        after the warning has been captured, never as proof of it.
        """
        import warnings

        from btap.simulation.backends import translate_capturing_advisories

        directory = self._plant_run_dir()

        # precondition: the fixture must actually provoke the advisory, or this
        # test is the vacuous one again
        import openstudio

        from btap._compat import opt
        model = opt(openstudio.model.Model.load(
            openstudio.path(str(directory / "in.osm"))))
        _, advisories = translate_capturing_advisories(model)
        self.assertTrue(any("DoPlantSizingCalculation" in a for a in advisories),
                        f"fixture must provoke a plant advisory, got {advisories}")

        for name, invoke in (
                ("Local", lambda: Local(energyplus="/nonexistent").execute(directory)),
                ("Remote", lambda: Remote(endpoint="https://example.invalid",
                                          api_key="x",
                                          transport=ExplodingTransport(),
                                          poll_seconds=0).execute(directory))):
            with self.subTest(backend=name):
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    try:
                        invoke()
                    except Exception:
                        pass        # the engine/transport fails AFTER the warning
                    surfaced = [str(w.message) for w in caught
                                if "DoPlantSizingCalculation" in str(w.message)]
                self.assertTrue(
                    surfaced,
                    f"{name} must surface the SDK's plant-sizing advisory as a "
                    f"warning; captured {[str(w.message) for w in caught]}")

    @needs_sdk
    def test_a_method_naming_its_field_WITHOUT_the_qualifier_still_counts(self):
        """Fable's `#70` fourth hole, in the opposite direction to the first three.

        A method choice names its field, sometimes without the leading
        qualifier: `Cooling Supply Air Flow Rate Method = SupplyAirFlowRate`
        selects `Cooling Supply Air Flow Rate`. An equality test skipped it, so
        the guard went silently blind on a field EnergyPlus must size — the
        failure it exists to prevent. Checked at the predicate, because no btap
        builder produces `AirLoopHVAC:UnitarySystem` today.
        """
        from btap.simulation.backends import _method_selects

        class FakeField:
            def __init__(self, name):
                self._name = name

            def name(self):
                return self._name

        class FakeOpt:
            def __init__(self, v):
                self._v = v

            def is_initialized(self):
                return self._v is not None

            def get(self):
                return self._v

        class FakeIdd:
            def __init__(self, pairs):
                self._pairs = pairs

            def numFields(self):
                return len(self._pairs)

            def getField(self, i):
                return FakeOpt(FakeField(self._pairs[i][0]))

        class FakeObj:
            def __init__(self, pairs):
                self._pairs = pairs

            def numFields(self):
                return len(self._pairs)

            def getString(self, i):
                return FakeOpt(self._pairs[i][1])

        CASES = (
            # (field, method value, must the field be counted?)
            ("Heating Design Capacity", "CapacityPerFloorArea", False),
            ("Heating Design Capacity", "HeatingDesignCapacity", True),
            ("Heating Design Capacity", "FractionOfAutosizedHeatingCapacity", True),
            ("Cooling Supply Air Flow Rate", "SupplyAirFlowRate", True),
            ("Cooling Supply Air Flow Rate", "FlowPerFloorArea", False),
            ("Cooling Supply Air Flow Rate", "FlowPerCoolingCapacity", False),
            ("No Load Supply Air Flow Rate", "SupplyAirFlowRate", True),
            # THIS ROW PINS THE PREDICATE'S CONTRACT, NOT A REACHABLE DEFECT,
            # and the distinction cost a wrong claim in PR #70's body.
            #
            # I added it because a mutation widening `endswith` to a substring
            # test (`chosen in wanted`) passed the other seven rows, and
            # described that as closing a hole. It is not one. Fable derived
            # the ground truth from the shipped IDD — all 67 real
            # (autosizable field x governing method choice) tuples — and the
            # substring form differs from `endswith` on ZERO of them, so on
            # this IDD it is an observationally equivalent implementation.
            # `Heating Design Capacity Per Floor Area` is itself
            # `autosizable=False`, so `autosized_fields` never calls
            # `_method_selects` for it: OpenStudio will not emit `autosize`
            # there.
            #
            # It still earns its place — a predicate's contract is
            # legitimately broader than its current call sites, and this row
            # says which predicate was intended where several agree on today's
            # inputs. But it is intent-pinning, and calling it a defect fix
            # would be the shape this repository keeps catching: a check whose
            # reported difference cannot occur.
            #
            # IT IS NOT PERMANENTLY INERT, WHICH IS THE POINT OF RECORDING IT
            # NOW. The IDD is a pinned artifact, not a law — the CI image pins
            # OpenStudio 3.11.0 — and both facts that make this row moot are
            # properties of THAT IDD: this field being `autosizable=False`,
            # and no object spelling a method token strictly inside a field
            # name. On an SDK bump either can change, and the row becomes
            # load-bearing the first time it does. Recorded now rather than at
            # the bump, when nobody will want to re-derive which predicate was
            # meant under time pressure (Fable, PR #82).
            #
            # For the record of what each candidate actually differs on
            # (Fable's enumeration over the 67 tuples):
            #
            #   ==, startswith, reversed endswith   6 real tuples
            #   no autosiz clause                  18
            #   always True                        33
            #   substring (`chosen in wanted`)      0
            ("Heating Design Capacity Per Floor Area",
             "HeatingDesignCapacity", False),
        )
        for field, method, expected in CASES:
            with self.subTest(field=field, method=method):
                pairs = [(f"{field} Method", method), (field, "Autosize")]
                got = _method_selects(FakeObj(pairs), FakeIdd(pairs), field)
                self.assertEqual(expected, got,
                                 f"{method!r} selecting {field!r}")

    @needs_sdk
    def test_a_partial_flag_run_surfaces_the_SDK_advisory(self):
        """Fable's L2, pinned.

        An autosized boiler with plant sizing OFF completes in EnergyPlus with
        rc=0, no Severe and no Fatal, silently deriving a capacity. The docstring
        used to claim EnergyPlus reports this; it does not. The only signal is an
        OpenStudio translate-time advisory, so the guard surfaces it.
        """
        import warnings

        import openstudio

        from btap.simulation.backends import (
            _require_sizing_calculations,
            translate_capturing_advisories,
        )

        model = load_fixture()
        loop = openstudio.model.PlantLoop(model)
        boiler = openstudio.model.BoilerHotWater(model)
        boiler.autosizeNominalCapacity()
        loop.addSupplyBranchForComponent(boiler)
        sim = model.getSimulationControl()
        sim.setDoZoneSizingCalculation(True)        # partial: plant is OFF
        sim.setDoSystemSizingCalculation(False)
        sim.setDoPlantSizingCalculation(False)

        workspace, advisories = translate_capturing_advisories(model)
        self.assertTrue(any("DoPlantSizingCalculation" in a for a in advisories),
                        f"the SDK must advise about plant sizing: {advisories}")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _require_sizing_calculations(model, workspace, Path("in.osm"),
                                         advisories)
        self.assertTrue(any("DoPlantSizingCalculation" in str(w.message)
                            for w in caught),
                        "the deferred case must not be silent")

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
