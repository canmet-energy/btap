"""Execution backends (port of btap-simulation's backends.rb).

The runner writes ``dir/in.osm`` (+ ``dir/in.osw`` for artifact parity with
the Ruby run dirs) into a run directory, then hands that directory to a
Backend. A backend's job is narrow and precise: execute the simulation so
that, on return, BOTH

* ``dir/run/eplusout.sql``  (results — parsed by runner.energy_results)
* ``dir/run/eplusout.err``  (E+ log — parsed by runner.is_clean_run)

exist. On any failure the backend must raise.

DELIBERATE DIVERGENCE from the Ruby gem (D-79, M2): Ruby's Local backend
shells out to ``openstudio run -w in.osw`` — the CLI the wheel does not have.
This Local backend reproduces that pipeline in-process instead:
ForwardTranslator (the wheel carries it) -> the two output requests the
OpenStudio workflow's EnergyPlus preprocess adds (Output:SQLite
SimpleAndTabular; Output:Table:SummaryReports AllSummary) -> the provisioned
``energyplus`` binary from btap.simulation.engine. Same artifacts, same
parse surface, no CLI anywhere.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from btap.simulation import engine


class Backend:
    """The local-vs-cloud seam. Subclasses implement execute(dir)."""

    def execute(self, run_dir):
        raise NotImplementedError(
            f"{type(self).__name__}.execute(dir) must run EnergyPlus and "
            "produce dir/run/eplusout.sql + dir/run/eplusout.err"
        )


class Local(Backend):
    """In-process translate + the provisioned EnergyPlus binary (default)."""

    def __init__(self, energyplus=None):
        #: explicit binary override (tests, embedders); None -> the engine.
        self._energyplus = Path(energyplus) if energyplus else None

    def execute(self, run_dir):
        import openstudio

        from btap._compat import opt

        run_dir = Path(run_dir)
        osm = run_dir / "in.osm"
        if not osm.is_file():
            raise RuntimeError(f"local backend: {osm} is missing — the runner did not prepare this dir")
        model = opt(openstudio.model.Model.load(openstudio.path(str(osm))))
        if model is None:
            raise RuntimeError(f"local backend: cannot load {osm}")

        workspace = openstudio.energyplus.ForwardTranslator().translateModel(model)
        _ensure_output_requests(workspace)
        idf = run_dir / "in.idf"
        workspace.save(openstudio.path(str(idf)), True)

        binary = self._energyplus or engine.ensure_energyplus()
        out_dir = run_dir / "run"
        out_dir.mkdir(parents=True, exist_ok=True)
        # ARGV form (list), never a shell string: paths with spaces are the
        # Windows norm, and the Ruby gem already paid for that lesson twice.
        cmd = [str(binary), "-x", "-d", str(out_dir)]
        epw = _weather_file_path(model)
        if epw is not None:
            cmd += ["-w", epw]
        cmd.append(str(idf))
        with open(run_dir / "cli.log", "w", encoding="utf-8") as log:
            ok = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode == 0

        err_path = out_dir / "eplusout.err"
        if not err_path.is_file():
            raise RuntimeError(
                f"EnergyPlus run failed in {run_dir} and wrote no eplusout.err — see {run_dir}/cli.log"
            )
        if ok:
            return None
        raise RuntimeError(
            f"EnergyPlus run failed in {run_dir}:\n{_failure_detail(err_path)}\n(full log: {err_path})"
        )


def _ensure_output_requests(workspace) -> None:
    """The two IDF-level additions `openstudio run` makes before EnergyPlus,
    without which eplusout.sql (and the tabular summaries every parser reads)
    never exist. Added at the WORKSPACE, never the model — in.osm must stay
    byte-comparable with what the Ruby runner saves."""
    import openstudio

    def has(type_name):
        return len(workspace.getObjectsByType(openstudio.IddObjectType(type_name))) > 0

    def add(idf_text):
        obj = openstudio.IdfObject.load(idf_text)
        if obj.is_initialized():
            workspace.addObject(obj.get())

    if not has("Output_SQLite"):
        add("Output:SQLite, SimpleAndTabular;")
    if not has("Output_Table_SummaryReports"):
        add("Output:Table:SummaryReports, AllSummary;")


def _weather_file_path(model):
    from btap._compat import opt

    weather = opt(model.weatherFile())
    if weather is None:
        return None
    path = opt(weather.path())
    return str(path) if path is not None else None


def _failure_detail(err_path: Path) -> str:
    """The Fatal line is usually the useless 'final processing' one — the
    SEVERE lines above it carry the cause. Surface both."""
    import re

    err = err_path.read_text(encoding="utf-8", errors="replace")
    severes = re.findall(r"^\s*\*\* Severe {2}\*\*.*(?:\n\s*\*\* {3}~~~ {3}\*\*.*)*", err, re.M)
    fatal = re.search(r"^.*Fatal.*$", err, re.M)
    detail = "\n".join(severes[:5] + ([fatal.group(0)] if fatal else [])).strip()
    return detail if detail else err[-800:]


class Remote(Backend):
    """Remote/cloud execution against an AWS-Batch EnergyPlus service (the
    hbix simulation API shape): upload_model -> presigned S3 PUT -> submit ->
    poll -> download results. Port of the Ruby Remote backend, transport
    injected so every test runs offline.

    HARD-WON (from validating the live service): the ENGINE VERSION MUST
    MATCH THE MODEL — neither OpenStudio nor EnergyPlus translates backward;
    the default 1-phase `energyplus` workflow uploads a ForwardTranslated IDF
    so the remote only has to match our EnergyPlus, not our OpenStudio; the
    service is async on AWS Batch, so poll on an interval, never tight-loop.
    The API key is NEVER logged, echoed, or put in a raised message."""

    def __init__(self, endpoint=None, api_key=None, transport=None, **opts):
        import os

        self._endpoint = (endpoint or os.environ.get("HBIX_SIM_ENDPOINT")
                          or os.environ.get("OS_SIM_REMOTE_ENDPOINT") or None)
        if self._endpoint:
            self._endpoint = self._endpoint.rstrip("/")
        self._api_key = (api_key or os.environ.get("HBIX_API_KEY")
                         or os.environ.get("OS_SIM_REMOTE_API_KEY") or None)
        self._opts = opts
        self._transport = transport or Http(self._api_key)

    def is_configured(self) -> bool:
        return bool(self._endpoint) and bool(self._api_key)

    def execute(self, run_dir):
        if not self.is_configured():
            raise RuntimeError(
                "remote backend is not configured: set HBIX_SIM_ENDPOINT and HBIX_API_KEY "
                "(or pass endpoint=/api_key=)"
            )
        run_dir = Path(run_dir)
        payload, filename = self._prepare_payload(run_dir)
        self._guard_engine_version()
        model_id = self._upload(payload, filename)
        job_id = self._submit(model_id)
        self._poll(job_id)
        self._download(job_id, run_dir)
        return None

    # The 1-phase `energyplus` workflow is the default: translate in-process
    # and upload an IDF — sidestepping the OSM-version wall entirely.
    # workflow_type='openstudio' uploads the OSM and leans on the remote's
    # 2-phase workflow instead.
    def _prepare_payload(self, run_dir: Path):
        osm = run_dir / "in.osm"
        if not osm.is_file():
            raise RuntimeError(f"remote backend: {osm} is missing — the runner did not prepare this dir")
        if self._workflow_type() == "openstudio":
            return osm.read_bytes(), "in.osm"

        import openstudio

        from btap._compat import opt

        model = opt(openstudio.model.Model.load(openstudio.path(str(osm))))
        if model is None:
            raise RuntimeError(f"remote backend: cannot load {osm}")
        idf = openstudio.energyplus.ForwardTranslator().translateModel(model)
        path = run_dir / "in.idf"
        idf.save(openstudio.path(str(path)), True)
        return path.read_bytes(), "in.idf"

    # Neither OpenStudio nor EnergyPlus translates BACKWARD. Catch the skew
    # here, in milliseconds, instead of 20 queue-minutes later.
    def _guard_engine_version(self):
        requested = self._engine_version()
        local = engine.wheel_energyplus_version()
        if not requested or not local:
            return
        want = [int(x) for x in requested.split(".")[:2]]
        have = [int(x) for x in local.split(".")[:2]]
        if want < have:
            raise RuntimeError(
                f"remote engine_version {requested} is OLDER than the EnergyPlus that wrote "
                f"this model ({local}). Translation is forward-only — the run would fail on "
                "the runner. Request an engine that matches, or generate the model with the "
                "older SDK."
            )

    def _upload(self, payload: bytes, filename: str) -> str:
        reg = self._with_retry("upload", lambda: self._transport.post_json(
            f"{self._endpoint}/models", {"filename": filename}))
        url = reg.get("upload_url")
        if url is None:
            raise RuntimeError(f"remote upload registration returned no upload_url (host {self._host()})")
        self._with_retry("upload-put", lambda: self._transport.put_bytes(url, payload))
        return reg.get("model_id")

    def _submit(self, model_id: str) -> str:
        body = {"model_id": model_id,
                "weather_station_id": self._station_id(),
                "weather_format": self._opts.get("weather_format", "CWEC2020"),
                "workflow_type": self._workflow_type(),
                "engine_version": self._engine_version(),
                "queue": self._opts.get("queue", "auto")}
        body = {k: v for k, v in body.items() if v is not None}
        job = self._with_retry("submit", lambda: self._transport.post_json(
            f"{self._endpoint}/simulations", body))
        job_id = job.get("job_id")
        if job_id is None:
            raise RuntimeError(f"remote submit returned no job_id (host {self._host()})")
        return job_id

    # Async on AWS Batch: a cold start before the phase leaves `submitted` is
    # normal. Poll on a fixed interval with a hard deadline, and tolerate a
    # transient read error rather than abandoning a running job.
    def _poll(self, job_id: str):
        timeout = self._opts.get("timeout_seconds", 3600)
        interval = self._opts.get("poll_seconds", 15)
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(f"remote job {job_id} did not finish within {timeout}s")
            try:
                status = self._transport.get_json(f"{self._endpoint}/simulations/{job_id}")
            except Exception:
                status = None  # transient — the job is still out there; try again next tick
            state = str((status or {}).get("status", ""))
            if state == "failed":
                raise RuntimeError(f"remote run failed: {self._phase_errors(status)}")
            if state == "completed":
                return
            time.sleep(interval)

    # Presigned result URLs carry a ~15-minute TTL — fetch both artifacts
    # immediately rather than stashing the URLs.
    def _download(self, job_id: str, run_dir: Path):
        res = self._with_retry("results", lambda: self._transport.get_json(
            f"{self._endpoint}/simulations/{job_id}/results"))
        files = res.get("files") or {}
        out_dir = run_dir / "run"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in ("eplusout.sql", "eplusout.err"):
            url = files.get(name)
            if url is None:
                continue
            (out_dir / name).write_bytes(self._transport.get_bytes(url))
        sql = out_dir / "eplusout.sql"
        if not (sql.is_file() and sql.stat().st_size > 0):
            raise RuntimeError(
                f"remote run {job_id} produced no eplusout.sql — the contract needs it for results parsing"
            )

    # Submits transiently 503 after a service deploy or an idle period; that
    # is not "the service is down". Exponential backoff, then give up loudly.
    def _with_retry(self, what: str, thunk, attempts: int = 5):
        delay = 1
        while True:
            try:
                return thunk()
            except Exception as e:
                attempts -= 1
                if attempts <= 0:
                    raise RuntimeError(f"remote {what} failed against {self._host()}: {e}") from e
                time.sleep(delay)
                delay *= 2

    def _phase_errors(self, status) -> str:
        phases = (status or {}).get("phases") or []
        errors = [err for p in phases for err in (p.get("errors") or []) if err is not None]
        return "; ".join(errors[:5])

    def _workflow_type(self) -> str:
        return self._opts.get("workflow_type", "energyplus")

    def _engine_version(self):
        explicit = self._opts.get("engine_version")
        if explicit:
            return explicit
        return ".".join(engine.wheel_energyplus_version().split(".")[:2])

    # The service resolves weather from its own library by station id;
    # arbitrary local EPWs are not uploadable on this path (documented).
    def _station_id(self):
        return self._opts.get("weather_station_id") or (
            self._opts.get("station_map") or {}).get("default")

    # Never put the api key in a message — errors name the host only.
    def _host(self) -> str:
        try:
            return urlsplit(str(self._endpoint)).hostname or str(self._endpoint)
        except Exception:
            return "the configured endpoint"


class Http:
    """The default transport (urllib). Isolated so tests never touch the
    network; the seam is four methods wide, deliberately not a mock library."""

    def __init__(self, api_key):
        self._api_key = api_key

    def post_json(self, url, body):
        return json.loads(self._request("POST", url, body=json.dumps(body).encode(),
                                        json_body=True))

    def get_json(self, url):
        return json.loads(self._request("GET", url))

    def get_bytes(self, url):
        return self._request("GET", url, auth=False, raw=True)

    def put_bytes(self, url, payload):
        return self._request("PUT", url, body=payload, auth=False, raw=True)

    def _request(self, method, url, body=None, json_body=False, auth=True, raw=False):
        req = urllib.request.Request(url, data=body, method=method)
        if auth and self._api_key:
            req.add_header("X-API-Key", self._api_key)
        if json_body:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req) as res:
            if not 200 <= res.status < 300:
                raise RuntimeError(f"HTTP {res.status}")
            data = res.read()
        return data if raw else data.decode("utf-8")
