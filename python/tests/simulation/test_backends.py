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
    #: The fixture, parsed ONCE for the class. Each test gets an independent
    #: `clone()` rather than re-parsing the OSM, because `run_energyplus`
    #: MUTATES the model it is given (sizing flags, then the SQL file) and a
    #: shared instance would leak that between tests. Measured:
    #:
    #:     load_fixture()  4.78 s        model.clone().to_Model()  0.02 s
    #:
    #: so three loads were 14.4 s of this module; one load plus three clones is
    #: 4.8 s. Independence is asserted below rather than assumed.
    _base = None

    @classmethod
    def setUpClass(cls):
        cls._base = load_fixture()

    def fresh_model(self):
        """An independent copy of the fixture — safe to mutate."""
        return self._base.clone().to_Model()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_dir(self, name):
        return str(Path(self.tmp.name) / name)

    def test_a_clone_is_independent_of_the_shared_base(self):
        """The precondition for sharing the parse. If this fails, every other
        test in this class is suspect, so it is asserted, not assumed."""
        a, b = self.fresh_model(), self.fresh_model()
        a.getSimulationControl().setDoZoneSizingCalculation(True)
        self.assertTrue(a.getSimulationControl().doZoneSizingCalculation())
        self.assertFalse(b.getSimulationControl().doZoneSizingCalculation(),
                         "a sibling clone must not see the mutation")
        self.assertFalse(self._base.getSimulationControl()
                         .doZoneSizingCalculation(),
                         "the shared base must not see the mutation")
        self.assertEqual(len(self._base.objects()), len(a.objects()))

    def test_custom_backend_is_invoked_with_prepared_dir(self):
        model = self.fresh_model()
        target = self.run_dir("custom")
        fake = FakeBackend(self)

        result = runner.run_energyplus(model, target, sizing_only=True, backend=fake)

        self.assertEqual(target, fake.called_with, "backend.execute was not called with the run dir")
        self.assertTrue((Path(target) / "in.osm").is_file(), "runner did not write in.osm")
        self.assertTrue((Path(target) / "in.osw").is_file(), "runner did not write in.osw")
        self.assertEqual(str(Path(target) / "run"), result)
        self.assertTrue(runner.is_clean_run(result), "is_clean_run should read the canned err")

    def test_facade_uses_injected_backend(self):
        model = self.fresh_model()
        target = self.run_dir("facade")
        fake = FakeBackend(self)

        result = run(model, run_dir=target, sizing_only=True, backend=fake)

        self.assertEqual(target, fake.called_with)
        self.assertIsInstance(result, Result)
        self.assertTrue(result.is_clean())
        self.assertIsNone(result.energy, "sizing_only run has no energy results")
        self.assertIsNone(result.unmet_hours, "sizing_only run has no unmet hours")

    def test_local_is_the_default_backend(self):
        model = self.fresh_model()
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


class TestResultFilesShape(unittest.TestCase):
    """`res["files"]` is a LIST on the live service, and `_download` indexed it.

    The failed-job payload is, verbatim from the service:

        {"job_id": …, "status": "failed", "engine": "energyplus",
         "files": [], "summary": {}}

    so `files.get(name)` raised `'list' object has no attribute 'get'` from
    inside the DOWNLOAD step — burying the run's real error, which was an
    EnergyPlus severe about a missing zone sizing run.

    The populated shape is UNVERIFIED (no remote run of ours has succeeded
    yet), so this pins tolerance and a diagnostic rather than a guess.

    Offline: pure function, no transport.
    """

    def test_the_live_failure_shape_yields_no_files(self):
        from btap.simulation.backends import _result_files

        live = {"job_id": "x", "status": "failed", "engine": "energyplus",
                "files": [], "summary": {}}
        self.assertEqual(({}, []), _result_files(live))

    def test_a_mapping_is_used_as_is(self):
        """The shape the code originally assumed still works."""
        from btap.simulation.backends import _result_files

        self.assertEqual(({"eplusout.sql": "https://a"}, []),
                         _result_files({"files": {"eplusout.sql": "https://a"}}))

    def test_a_list_of_objects_is_read_through_name_and_url(self):
        from btap.simulation.backends import _result_files

        got, unreadable = _result_files({"files": [
            {"name": "eplusout.sql", "url": "https://a"},
            {"filename": "run/eplusout.err", "download_url": "https://b"},
        ]})
        self.assertEqual({"eplusout.sql": "https://a",
                          "eplusout.err": "https://b"}, got)
        self.assertEqual([], unreadable)

    def test_the_OBSERVED_successful_element_shape(self):
        """The real thing, from a completed job on 2026-10-04.

        17 files, element keys exactly
        `download_url, name, phase_id, s3_key, size_bytes`. Recorded because
        the previous version of this test used GUESSED aliases and called them
        live (Sol, PR #78).
        """
        from btap.simulation.backends import _result_files

        got, unreadable = _result_files({"files": [
            {"name": "eplusout.sql", "size_bytes": 778240,
             "phase_id": "fe0e240e", "s3_key": "jobs/…/eplusout.sql",
             "download_url": "https://…presigned"},
            {"name": "eplusout.err", "size_bytes": 10649,
             "phase_id": "fe0e240e", "s3_key": "jobs/…/eplusout.err",
             "download_url": "https://…presigned"},
        ]})
        self.assertEqual({"eplusout.sql": "https://…presigned",
                          "eplusout.err": "https://…presigned"}, got)
        self.assertEqual([], unreadable)

    def test_a_missing_or_null_files_key_is_empty(self):
        from btap.simulation.backends import _result_files

        for res in ({}, {"files": None}, None):
            with self.subTest(res=res):
                self.assertEqual(({}, []), _result_files(res))

    def test_an_unknown_shape_names_what_arrived(self):
        """A fourth wrong assumption should be a readable error, not a crash."""
        from btap.simulation.backends import _result_files

        with self.assertRaises(RuntimeError) as caught:
            _result_files({"files": "https://a"})
        self.assertIn("is a str", str(caught.exception))


class TestUnreadableEntriesAreNamed(unittest.TestCase):
    """A NONEMPTY unsupported entry must name its shape, not vanish.

    `_result_files` used to `continue` past an element it could not read, so
    `_download` reported only "produced no eplusout.sql" — replacing one
    masked remote diagnosis with another. The caller would chase a missing
    file when the real problem is an element shape we do not handle.

    Reaches `_download` through the transport seam, because a helper-level
    test cannot show the message the caller actually receives (Sol, PR #78).
    """

    class Transport:
        def __init__(self, files):
            self._files = files

        def get_json(self, url):
            if url.endswith("/results"):
                return {"job_id": "j-1", "status": "completed",
                        "engine": "energyplus", "files": self._files,
                        "summary": {}}
            return {"status": "completed", "phases": []}

        def get_bytes(self, url):
            return b""

    def _download(self, files):
        import tempfile
        from pathlib import Path

        from btap.simulation.backends import Remote

        remote = Remote(endpoint="https://svc.test", api_key="k",
                        transport=self.Transport(files))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as caught:
                remote._download("j-1", Path(tmp))
        return str(caught.exception)

    def test_an_unsupported_entry_shape_is_named(self):
        message = self._download([{"path": "eplusout.sql",
                                   "downloadUrl": "https://example.invalid/s"}])
        self.assertIn("does not understand", message)
        self.assertIn("downloadUrl", message, "the KEY NAMES must appear")
        self.assertIn("path", message)

    def test_the_presigned_url_is_NEVER_in_the_message(self):
        """Key names are not secret; a presigned URL carries an STS token."""
        secret = "https://example.invalid/SECRET-TOKEN-abc123"
        message = self._download([{"path": "eplusout.sql",
                                   "downloadUrl": secret}])
        self.assertNotIn(secret, message)
        self.assertNotIn("SECRET-TOKEN", message)

    def test_a_non_dict_entry_is_named_by_its_type(self):
        message = self._download(["https://example.invalid/sql"])
        self.assertIn("str", message)

    def test_an_EMPTY_list_keeps_the_original_message(self):
        """No unreadable entries means the plain contract error, unchanged."""
        message = self._download([])
        self.assertIn("produced no eplusout.sql", message)
        self.assertNotIn("does not understand", message)


class TestWeatherIdentity(unittest.TestCase):
    """The station the service needs, derived from the model's own EPW.

    `cli.py` builds a bare `Remote()`, so nothing supplied `weather_station_id`
    and `_submit` dropped it — the service then rejected the job as
    "EnergyPlus requires a weather file (WEATHER_S3_KEY)". No harness scenario
    could run remotely at all (Sol, PR #79).

    Deriving it from the EPW the model already carries binds the station to THE
    SAME committed weather the scenario pins. Note it binds the LABEL, not the
    bytes — see hbix#105.
    """

    def test_the_committed_naming_conventions(self):
        from btap.simulation.backends import weather_identity

        CASES = (
            ("CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw",
             ("716240", "CWEC2020")),
            ("CAN_NB_Fredericton.717000_CWEC2020.epw",
             ("717000", "CWEC2020")),
            ("/abs/path/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw",
             ("716240", "CWEC2020")),
            ("CAN_ON_Toronto.Intl.AP.716240_TMYx.2009-2023.epw",
             ("716240", "TMYx.2009-2023")),
            ("no-station-here.epw", None),
            ("", None),
            (None, None),
        )
        for path, expected in CASES:
            with self.subTest(path=path):
                self.assertEqual(expected, weather_identity(path))

    def test_an_explicit_option_still_wins(self):
        from btap.simulation.backends import Remote

        remote = Remote(endpoint="https://svc.test", api_key="k",
                        weather_station_id="999999", weather_format="TMYx")
        remote._derived = ("716240", "CWEC2020")
        self.assertEqual("999999", remote._station_id())
        self.assertEqual("TMYx", remote._weather_format())

    def test_the_derived_identity_is_used_when_no_option_is_given(self):
        from btap.simulation.backends import Remote

        remote = Remote(endpoint="https://svc.test", api_key="k")
        remote._derived = ("716240", "CWEC2020")
        self.assertEqual("716240", remote._station_id())
        self.assertEqual("CWEC2020", remote._weather_format())

    def test_submit_REFUSES_when_no_station_can_be_found(self):
        """Better than the service's own cryptic rejection."""
        from btap.simulation.backends import Remote

        class Transport:
            def post_json(self, url, body):
                raise AssertionError("must refuse BEFORE submitting")

        remote = Remote(endpoint="https://svc.test", api_key="k",
                        transport=Transport())
        with self.assertRaises(RuntimeError) as caught:
            remote._submit("m-1")
        message = str(caught.exception)
        self.assertIn("needs a weather station", message)
        self.assertIn("WEATHER_S3_KEY", message,
                      "name the service's own error so it is searchable")

    def test_the_osm_text_scan_finds_the_weather_path(self):
        import tempfile
        from pathlib import Path

        from btap.simulation.backends import _osm_weather_path

        body = ("OS:WeatherFile,\n  {h}, !- Handle\n  Toronto Intl AP,\n"
                "  /x/y/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw, !- Url\n;\n")
        with tempfile.TemporaryDirectory() as tmp:
            osm = Path(tmp) / "in.osm"
            osm.write_text(body, encoding="utf-8")
            self.assertEqual(
                "/x/y/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw",
                _osm_weather_path(osm))
            missing = Path(tmp) / "absent.osm"
            self.assertIsNone(_osm_weather_path(missing))


class TestDerivationHappensAtTheCallSite(unittest.TestCase):
    """`_prepare_payload` must actually DERIVE, not just be able to.

    THIRD time this gap has bitten in this PR family: tests that set
    `remote._derived` by hand pass even when the derivation is deleted, just
    as `_result_files` tests passed when `_download` was reverted (#78) and
    `_select_backend` tests passed when `build_env` did not pass the variable
    (#79). Mutation evidence is what exposed it: removing the two derivation
    lines from `_prepare_payload` left 63 tests green.

    So this reaches `_prepare_payload` with a real OSM on disk, and asserts the
    station it will SUBMIT.
    """

    def _prepared(self, osm_body, **opts):
        import tempfile
        from pathlib import Path

        from btap.simulation.backends import Remote

        remote = Remote(endpoint="https://svc.test", api_key="k", **opts)
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "in.osm").write_text(osm_body, encoding="utf-8")
            # the 2-phase branch returns before any SDK work, which is enough
            # to exercise the derivation
            remote._opts["workflow_type"] = "openstudio"
            remote._prepare_payload(run_dir)
        return remote

    OSM = ("OS:WeatherFile,\n  {h}, !- Handle\n  Toronto Intl AP,\n"
           "  /w/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw, !- Url\n;\n")

    def test_preparing_the_payload_derives_the_station(self):
        remote = self._prepared(self.OSM)
        self.assertEqual(("716240", "CWEC2020"), remote._derived)
        self.assertEqual("716240", remote._station_id())

    def test_the_FORMAT_comes_from_the_epw_not_a_constant(self):
        """A non-CWEC2020 EPW must not be submitted as CWEC2020."""
        osm = self.OSM.replace("716240_CWEC2020.epw",
                               "716240_TMYx.2009-2023.epw")
        remote = self._prepared(osm)
        self.assertEqual("TMYx.2009-2023", remote._weather_format(),
                         "a constant fallback would mis-describe the weather")

    def test_an_osm_without_a_derivable_epw_leaves_it_unset(self):
        remote = self._prepared("OS:Version,\n  {h}, !- Handle\n  3.11.0;\n")
        self.assertIsNone(remote._station_id())

    def test_a_number_that_is_not_a_six_digit_station_is_not_one(self):
        """`_(\\d{6})_` is deliberate: a bare number is not a WMO station."""
        from btap.simulation.backends import weather_identity

        for name in ("CAN_ON_somewhere.12_CWEC2020.epw",
                     "CAN_ON_somewhere.1234567_CWEC2020.epw",
                     "CAN_ON_run.2024_CWEC2020.epw"):
            with self.subTest(name=name):
                got = weather_identity(name)
                self.assertIsNone(
                    got, f"{name!r} has no six-digit station, got {got!r}")


class TestStationComesFromThisRunsModel(unittest.TestCase):
    """Sol's #78 findings: the station could come from the wrong model.

    Both were reproduced before fixing, and both silently change the station
    sent to the service — so annual results move while the baseline claims the
    committed EPW. That is why #78 is compliance tier and not verification
    tier, which I had it wrong.

    Offline: no transport, no network, no SDK load (the 2-phase payload path
    returns the OSM bytes directly).
    """

    def _remote(self, **opts):
        from btap.simulation.backends import Remote

        opts.setdefault("workflow_type", "openstudio")
        return Remote(endpoint="https://svc.test", api_key="k", **opts)

    def _run_dir(self, station):
        import tempfile
        from pathlib import Path

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, directory,
                        ignore_errors=True)
        (directory / "in.osm").write_text(
            "OS:WeatherFile,\n  {h}, !- Handle\n  Somewhere,\n"
            f"  /w/CAN_XX_Somewhere.{station}_CWEC2020.epw, !- Url\n;\n",
            encoding="utf-8")
        return directory

    def test_a_REUSED_backend_recomputes_for_each_model(self):
        """`Remote` is reused — `set_default_backend` installs one
        process-wide — and `if self._derived is None` cached the FIRST
        model's station. A second run naming 717000 still submitted 716240,
        so every model after the first in a sweep went to the wrong station.
        """
        remote = self._remote()
        seen = []
        for station in ("716240", "717000", "718770"):
            remote._prepare_payload(self._run_dir(station))
            seen.append(remote._station_id())
        self.assertEqual(["716240", "717000", "718770"], seen,
                         "each preparation must derive from ITS OWN model")

    def test_an_unrelated_epw_before_the_weather_object_is_ignored(self):
        """`_osm_weather_path` took the first `.epw` token ANYWHERE, including
        a comment, despite its docstring naming the `OS:WeatherFile` URL."""
        import shutil
        import tempfile
        from pathlib import Path

        from btap.simulation.backends import _osm_weather_path

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        osm = directory / "in.osm"
        osm.write_text(
            "! stale note about /old/CAN_XX.716240_CWEC2020.epw\n"
            "OS:Version,\n  {v}, !- Handle\n  3.11.0;\n"
            "OS:WeatherFile,\n  {h}, !- Handle\n  Somewhere,\n"
            "  /w/CAN_XX.717000_CWEC2020.epw, !- Url\n;\n",
            encoding="utf-8")
        self.assertEqual("/w/CAN_XX.717000_CWEC2020.epw",
                         _osm_weather_path(osm),
                         "a comment must not decide the service weather")

    def test_the_station_reaches_the_SUBMITTED_request(self):
        """The helper is not the deliverable — the request body is."""
        captured = {}

        class Transport:
            def post_json(self, url, body):
                captured.setdefault("bodies", []).append(body)
                if url.endswith("/models/upload-url"):
                    return {"model_id": "m-1",
                            "upload_url": "https://s3.test/put", "s3_key": "k"}
                return {"job_id": "j-1"}

            def put_bytes(self, url, payload):
                return None

        remote = self._remote(transport=Transport())
        remote._prepare_payload(self._run_dir("717000"))
        remote._submit("m-1")
        submitted = [b for b in captured["bodies"] if "weather_station_id" in b]
        self.assertEqual(1, len(submitted))
        self.assertEqual("717000", submitted[0]["weather_station_id"])
        self.assertEqual("CWEC2020", submitted[0]["weather_format"])

    def test_an_explicit_option_still_wins_over_the_model(self):
        remote = self._remote(weather_station_id="999999")
        remote._prepare_payload(self._run_dir("716240"))
        self.assertEqual("999999", remote._station_id())

    def test_a_model_with_no_station_is_refused_BEFORE_any_upload(self):
        """The check lived in `_submit`, so the model was transferred first."""
        import shutil
        import tempfile
        from pathlib import Path

        class Transport:
            def __init__(self):
                self.calls = []

            def post_json(self, url, body):
                self.calls.append(url)
                raise AssertionError(f"network touched: {url}")

            def put_bytes(self, url, payload):
                self.calls.append(url)
                raise AssertionError(f"network touched: {url}")

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        (directory / "in.osm").write_text("OS:Version,\n  {h},\n  3.11.0;\n",
                                          encoding="utf-8")
        transport = Transport()
        remote = self._remote(transport=transport)
        with self.assertRaises(RuntimeError) as caught:
            remote.execute(directory)
        self.assertIn("needs a weather station", str(caught.exception))
        self.assertEqual([], transport.calls,
                         "nothing may be uploaded before the refusal")
