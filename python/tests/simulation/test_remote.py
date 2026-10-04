"""Port of btap-simulation/test/test_remote.rb: the whole Remote backend,
exercised OFFLINE through an injected transport. Nothing here touches the
network."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from btap.simulation import Remote, engine
from tests.support import load_fixture, needs_sdk


class FakeTransport:
    """Records every call and replays canned responses. Deliberately not a
    mock library — the seam is four methods wide."""

    def __init__(self, status="completed", fail_times=0, files=None):
        self.calls = []
        self.status = status
        self.fail_times = fail_times
        self.files = files

    def post_json(self, url, body):
        self.calls.append(("post", url, body))
        path, _, query = url.partition("?")
        # Matched on the path's TAIL, not as a substring. `"/models" in path`
        # would fire for an endpoint that itself contains `/models` — e.g.
        # `https://svc.test/api/models` makes `{endpoint}/simulations` contain
        # `/models`, enter this branch, fail the endswith below, and raise a
        # spurious 404 on a route that works. Same substring class as the
        # `run_lines` parser in #64 (Fable, PR #75).
        if path.endswith(("/models", "/models/upload-url")):
            # The fake now ENFORCES the live service's contract instead of
            # restating whatever the backend happened to send. It previously
            # matched `endswith("/models")`, so it validated a route the service
            # answers with 404 — which is how the drift went unseen while every
            # offline test passed. Measured against the live API on 2026-10-03.
            if not path.endswith("/models/upload-url"):
                raise RuntimeError(f"404 Not Found: {path}")
            if "filename=" not in query:
                raise RuntimeError(
                    "422 missing query parameter 'filename' "
                    "(the service wants it in the query, not the body)")
            self.fail_times -= 1
            if self.fail_times >= 0:
                raise RuntimeError("503 Service Unavailable")
            return {"model_id": "m-1", "upload_url": "https://s3.test/put", "s3_key": "k"}
        return {"job_id": "j-1", "status": "submitted"}

    def get_json(self, url):
        self.calls.append(("get", url))
        if url.endswith("/results"):
            # THE OBSERVED SHAPE, from a COMPLETED job on 2026-10-04 — 17
            # files whose element keys are exactly
            # `download_url, name, phase_id, s3_key, size_bytes`. `files` is a
            # LIST, not a mapping; the fake used to return a mapping, which is
            # why `_download` calling `.get` on a list survived every offline
            # test and failed only on a real run. Same class of drift as the
            # `/models/upload-url` route above: a fake that restates the
            # backend's assumption cannot falsify it.
            #
            # These are the service's real key names rather than aliases the
            # backend happens to accept, so this fixture would catch the
            # service renaming one (Sol, PR #78).
            return {"job_id": "j-1", "status": self.status,
                    "engine": "energyplus",
                    "files": self.files if self.files is not None
                    else [{"name": "eplusout.sql", "size_bytes": 778240,
                           "phase_id": "p-1", "s3_key": "jobs/j-1/eplusout.sql",
                           "download_url": "https://s3.test/sql"},
                          {"name": "eplusout.err", "size_bytes": 10649,
                           "phase_id": "p-1", "s3_key": "jobs/j-1/eplusout.err",
                           "download_url": "https://s3.test/err"}],
                    "summary": {}}
        # Phase errors are STRUCTURED on the live service, verbatim:
        #   {"error_code": "ENERGYPLUS_SEVERE", "message": "** Severe **…",
        #    "recoverable": false, "suggestion": null}
        return {"status": self.status, "phases": [{"errors": [
            {"error_code": "ENERGYPLUS_SEVERE", "message": "boom",
             "recoverable": False, "suggestion": None}]}]}

    def put_bytes(self, url, payload):
        self.calls.append(("put", url, len(payload)))

    def get_bytes(self, url):
        self.calls.append(("getb", url))
        return b"SQLITE-BYTES" if url.endswith("sql") else b"EnergyPlus Completed Successfully"


@needs_sdk
class TestRemote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def prepared_dir(self):
        import openstudio
        run_dir = Path(self.tmp.name) / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        model = load_fixture()
        model.save(openstudio.path(str(run_dir / "in.osm")), True)
        return run_dir

    def remote(self, transport, **opts):
        opts.setdefault("poll_seconds", 0)
        return Remote(endpoint="https://svc.test", api_key="k", transport=transport, **opts)

    def uploaded_filename(self, transport):
        """The `filename` as the service receives it: a QUERY parameter.

        Reading it from the JSON body is what the old assertions did, and the
        service answers that shape with 422.
        """
        from urllib.parse import parse_qs, urlsplit

        call = self.find_call(transport, "post", "/models/upload-url")
        return parse_qs(urlsplit(call[1]).query).get("filename", [None])[0]

    def find_call(self, transport, kind, suffix):
        # endswith, not `in`: see FakeTransport.post_json on why a substring
        # match on a URL path is a trap.
        return next(c for c in transport.calls
                    if c[0] == kind and c[1].partition("?")[0].endswith(suffix))

    def test_happy_path_lands_both_artifacts_locally(self):
        run_dir = self.prepared_dir()
        t = FakeTransport()
        self.remote(t, weather_station_id="CAN_ON_Toronto").execute(run_dir)

        self.assertEqual(b"SQLITE-BYTES", (run_dir / "run" / "eplusout.sql").read_bytes())
        self.assertIn("Completed Successfully",
                      (run_dir / "run" / "eplusout.err").read_text())

    def test_default_workflow_uploads_a_translated_idf(self):
        # The default workflow translates in-process and uploads an IDF, so
        # the remote only has to match our EnergyPlus, not our OpenStudio.
        run_dir = self.prepared_dir()
        t = FakeTransport()
        self.remote(t).execute(run_dir)

        register = self.find_call(t, "post", "/models/upload-url")
        self.assertEqual("in.idf", self.uploaded_filename(t),
                         "the service wants filename in the query, not the body")
        self.assertEqual({}, register[2],
                         "and the body carries nothing — a body with filename "
                         "returns 422")
        self.assertTrue((run_dir / "in.idf").is_file(), "the IDF should be left beside in.osm")

        submit = self.find_call(t, "post", "/simulations")
        self.assertEqual("energyplus", submit[2]["workflow_type"])

    def test_openstudio_workflow_uploads_the_osm_instead(self):
        run_dir = self.prepared_dir()
        t = FakeTransport()
        self.remote(t, workflow_type="openstudio").execute(run_dir)
        self.assertEqual("in.osm", self.uploaded_filename(t))

    def test_engine_version_is_always_sent_and_defaults_to_the_local_energyplus(self):
        run_dir = self.prepared_dir()
        t = FakeTransport()
        self.remote(t).execute(run_dir)
        submitted = self.find_call(t, "post", "/simulations")[2]["engine_version"]
        self.assertIsNotNone(submitted)
        expected = ".".join(engine.wheel_energyplus_version().split(".")[:2])
        self.assertEqual(expected, submitted)

    def test_requesting_an_older_engine_is_refused_before_upload(self):
        # Translation is forward-only. Asking for an older engine must fail
        # in milliseconds, not 20 minutes into a queued run.
        run_dir = self.prepared_dir()
        t = FakeTransport()
        with self.assertRaises(RuntimeError) as ctx:
            self.remote(t, engine_version="9.1").execute(run_dir)
        self.assertIn("forward-only", str(ctx.exception))
        self.assertFalse(any(c[0] == "put" for c in t.calls),
                         "must refuse BEFORE uploading anything")

    def test_transient_503_on_submit_is_retried(self):
        run_dir = self.prepared_dir()
        t = FakeTransport(fail_times=2)
        with mock.patch("time.sleep"):
            self.remote(t).execute(run_dir)
        registers = [c for c in t.calls if c[0] == "post" and "/models/upload-url" in c[1]]
        self.assertGreaterEqual(len(registers), 3)

    def test_failed_status_raises_with_the_phase_errors(self):
        run_dir = self.prepared_dir()
        t = FakeTransport(status="failed")
        with self.assertRaises(RuntimeError) as ctx:
            self.remote(t).execute(run_dir)
        self.assertIn("remote run failed", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception), "the phase errors are the diagnostic")

    def test_missing_sql_in_the_result_bundle_raises(self):
        run_dir = self.prepared_dir()
        t = FakeTransport(files=[{"name": "eplusout.err", "size_bytes": 10649,
                                  "phase_id": "p-1",
                                  "s3_key": "jobs/j-1/eplusout.err",
                                  "download_url": "https://s3.test/err"}])
        with self.assertRaises(RuntimeError) as ctx:
            self.remote(t).execute(run_dir)
        self.assertIn("no eplusout.sql", str(ctx.exception))

    def test_timeout_is_bounded(self):
        run_dir = self.prepared_dir()
        t = FakeTransport(status="running")
        with self.assertRaises(RuntimeError) as ctx:
            self.remote(t, timeout_seconds=-1).execute(run_dir)
        self.assertIn("did not finish within", str(ctx.exception))

    def test_api_key_never_appears_in_an_error_message(self):
        # The credential must never reach a message a user can paste into a
        # ticket.
        run_dir = self.prepared_dir()
        secret = "super-secret-key-do-not-leak"
        t = FakeTransport(status="failed")
        with self.assertRaises(RuntimeError) as ctx:
            Remote(endpoint="https://svc.test", api_key=secret, transport=t,
                   poll_seconds=0).execute(run_dir)
        self.assertNotIn(secret, str(ctx.exception))

    def test_missing_in_osm_is_reported_as_a_contract_violation(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.remote(FakeTransport()).execute(self.tmp.name)
        self.assertIn("in.osm is missing", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
