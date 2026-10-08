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
        if path.endswith("/weather/upload-url"):
            # ENFORCES the documented contract (hbix, 2026-10-08), so this fake
            # cannot pass while the live call fails — the drift that cost us
            # three shape bugs the last time a fake restated the backend's own
            # assumptions.
            if "filename=" in query:
                raise RuntimeError(
                    "the weather route takes `filename` in the BODY; the "
                    "models route is the one that wants it in the query")
            if not body.get("filename"):
                raise RuntimeError("422 missing 'filename' in the body")
            digest = body.get("sha256_b64")
            if digest and len(digest) != 44:
                # base64 of a 32-byte binary digest is 44 chars; base64 of the
                # 64-char HEX string is 88 and is a well-formed wrong answer.
                raise RuntimeError(
                    "sha256_b64 must be base64 of the BINARY digest, not of "
                    "the hex string")
            self.weather_digest = digest
            reply = {"upload_url": "https://s3.test/weather",
                     "weather_s3_key": "weather-uploads/abc/original/x.epw",
                     "expires_in_seconds": 3600}
            if digest:
                reply["required_headers"] = {"x-amz-checksum-sha256": digest}
            return reply
        return {"job_id": "j-1", "status": "submitted"}

    def get_json(self, url):
        self.calls.append(("get", url))
        if url.endswith("/results"):
            return {"files": self.files if self.files is not None
                    else {"eplusout.sql": "https://s3.test/sql",
                          "eplusout.err": "https://s3.test/err"}}
        return {"status": self.status, "phases": [{"errors": ["boom"]}]}

    def put_bytes(self, url, payload, headers=None):
        self.calls.append(("put", url, len(payload), headers or {}))
        if url.endswith("/weather") and getattr(self, "weather_digest", None):
            # A checksum-bound PUT without the header is REFUSED by S3, so the
            # fake refuses it too.
            if (headers or {}).get("x-amz-checksum-sha256") != self.weather_digest:
                raise RuntimeError(
                    "400 the presigned PUT is bound to x-amz-checksum-sha256 "
                    "and the header is missing or wrong")

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
        # What `run_energyplus` sets before handing a dir to a backend. Without
        # these the backend's own guard refuses the dir, and this helper is named
        # for a PREPARED dir — so it must prepare one faithfully.
        sim = model.getSimulationControl()
        sim.setDoZoneSizingCalculation(True)
        sim.setDoSystemSizingCalculation(True)
        sim.setDoPlantSizingCalculation(True)
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
        t = FakeTransport(files={"eplusout.err": "https://s3.test/err"})
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


class TestCallerSuppliedWeather(unittest.TestCase):
    """hbix#107 / PR 108. Until that shipped, the service resolved weather from
    its own library by station id and a local EPW was not uploadable — and the
    library had DRIFTED from our committed fixture (measured 2026-10-08: the
    same `CWEC2020`/`716240` label served an EPW 62 bytes different, the STAT
    and DDY further apart, and no `sha256_b64` on any of the three).

    A remote run on a different weather file cannot be compared with a local
    baseline, which is what made remote verification of the annual lane
    useless. Our own bytes now travel, checksum-bound.
    """

    def _remote(self, **opts):
        from btap.simulation.backends import Remote

        transport = FakeTransport()
        return Remote(endpoint="https://svc.test/api", api_key="k",
                      transport=transport, **opts), transport

    def _epw(self, tmp):
        epw = Path(tmp) / "in.epw"
        epw.write_bytes(b"LOCATION,Toronto\n" + b"x" * 400)
        return epw

    def test_the_key_is_returned_and_the_PUT_carries_the_checksum(self):
        remote, transport = self._remote()
        with tempfile.TemporaryDirectory() as tmp:
            key = remote._upload_weather(self._epw(tmp))
        self.assertEqual("weather-uploads/abc/original/x.epw", key)
        puts = [c for c in transport.calls if c[0] == "put"]
        self.assertEqual(1, len(puts))
        self.assertIn("x-amz-checksum-sha256", puts[0][3],
                      "a checksum-bound PUT without the header is refused")

    def test_the_digest_is_the_BINARY_sha256_not_the_hex(self):
        """base64 of the hex string is a well-formed wrong answer, so the fake
        rejects it and this test proves we send the right one."""
        import base64
        import hashlib

        remote, transport = self._remote()
        with tempfile.TemporaryDirectory() as tmp:
            epw = self._epw(tmp)
            remote._upload_weather(epw)
            expected = base64.b64encode(
                hashlib.sha256(epw.read_bytes()).digest()).decode()
        self.assertEqual(expected, transport.weather_digest)

    def test_submit_sends_OUR_key_and_omits_the_station(self):
        remote, transport = self._remote()
        remote._weather_key = "weather-uploads/abc/original/x.epw"
        remote._submit("m-1")
        body = [c[2] for c in transport.calls
                if c[0] == "post" and c[1].endswith("/simulations")][0]
        self.assertEqual("weather-uploads/abc/original/x.epw",
                         body["weather_s3_key"])
        self.assertNotIn("weather_station_id", body,
                         "two weather sources in one submit is ambiguous")
        self.assertNotIn("weather_format", body)

    def test_without_a_key_the_station_id_is_still_used(self):
        """The fallback a model whose EPW is not on this machine needs."""
        remote, transport = self._remote(weather_station_id="716240")
        remote._submit("m-1")
        body = [c[2] for c in transport.calls
                if c[0] == "post" and c[1].endswith("/simulations")][0]
        self.assertEqual("716240", body["weather_station_id"])
        self.assertNotIn("weather_s3_key", body)

    def test_upload_weather_False_opts_out(self):
        remote, _transport = self._remote(upload_weather=False)
        with tempfile.TemporaryDirectory() as tmp:
            self._epw(tmp)
            self.assertIsNone(remote._resolve_weather(Path(tmp)))

    def test_a_missing_key_in_the_reply_RAISES_rather_than_falling_back(self):
        """Falling back to the station id would substitute DIFFERENT weather
        for the file the caller asked for and report the comparison as
        like-for-like."""
        from btap.simulation.backends import Remote

        class NoKey(FakeTransport):
            def post_json(self, url, body):
                if url.endswith("/weather/upload-url"):
                    return {"upload_url": "https://s3.test/weather"}
                return super().post_json(url, body)

        remote = Remote(endpoint="https://svc.test/api", api_key="k",
                        transport=NoKey())
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as caught:
                remote._upload_weather(self._epw(tmp))
        self.assertIn("weather_s3_key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
