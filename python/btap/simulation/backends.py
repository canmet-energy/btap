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
from urllib.parse import urlencode, urlsplit

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
        workspace, advisories = translate_capturing_advisories(model)
        _require_sizing_calculations(model, workspace, osm, advisories)
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
        # cwd MUST be the run's own output dir: `-x` (ExpandObjects) writes
        # its intermediates (expanded.idf, ...) into the CURRENT directory,
        # so concurrent runs sharing a cwd clobber each other — 36 of 97
        # systems failed in the parallel sweep before this, every one of
        # them passing when run alone. (`openstudio run` runs E+ in the run
        # directory for the same reason.)
        with open(run_dir / "cli.log", "w", encoding="utf-8") as log:
            ok = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                cwd=str(out_dir)).returncode == 0

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


def translate_capturing_advisories(model):
    """``(workspace, advisories)`` — ForwardTranslate, keeping the SDK's own
    sizing advice.

    OpenStudio emits e.g. "You have PlantLoop(s) and design days, it's possible
    you should enable SimulationControl::DoPlantSizingCalculation" at translate
    time, to the SDK log. That log is not `eplusout.err`, so nothing surfaced it
    and the partial-flag case ran silently (Fable, PR #70).
    """
    import openstudio

    sink = openstudio.StringStreamLogSink()
    sink.setLogLevel(openstudio.Warn)
    workspace = openstudio.energyplus.ForwardTranslator().translateModel(model)
    messages = [" ".join(str(m.logMessage()).split()) for m in sink.logMessages()]
    return workspace, [m for m in messages if "SizingCalculation" in m]


def autosized_fields(workspace):
    """The NUMERIC fields EnergyPlus would have to size, named.

    Asks the IDD for each field's declared type, because a whole-text search for
    the `Autosize` token cannot tell an autosizable numeric field from an alpha
    one: a `Building` merely NAMED "Autosize" renders `Autosize,  !- Name` and
    was counted, so the guard refused a model with nothing to size at all (Sol,
    `077` case 2). The IDD is authoritative about field types, and it is data the
    SDK already ships rather than a list this module would have to maintain.

    Interrogating the MODEL instead does not work: `getModelObjects()` yields
    base instances, so the SDK's typed `isXxxAutosized()` predicates are
    unreachable — they report 0 even for `01-baseboard-gas` — and enumerating
    concrete component types would be an open-ended surface to model.
    """
    found = []
    for obj in workspace.objects():
        idd = obj.iddObject()
        for index in range(obj.numFields()):
            value = obj.getString(index)
            if not value.is_initialized() or \
                    value.get().strip().lower() != "autosize":
                continue
            field = idd.getField(index)
            if not field.is_initialized():
                continue
            if not any(kind in str(field.get().properties().type)
                       for kind in ("Real", "Integer")):
                continue
            if not _method_selects(obj, idd, field.get().name()):
                continue
            found.append(f"{idd.name()} field {index} "
                         f"({field.get().name()})")
    return found


def _method_selects(obj, idd, field_name: str) -> bool:
    """Would EnergyPlus actually READ this autosized field?

    An autosized field is often governed by a sibling `*Method` field that
    selects which of several inputs applies. With
    `Heating Design Capacity Method = CapacityPerFloorArea`, EnergyPlus reads
    `Heating Design Capacity Per Floor Area` and never evaluates
    `Heating Design Capacity`, which OpenStudio leaves `Autosize` by default —
    so the field is autosized, inert, and needs no sizing run. The guard refused
    such a model while EnergyPlus completed it with rc=0 (Fable, PR #70).

    This reads ONE sibling field whose own value names the input it selects. It
    is not the component taxonomy this module refuses to model: no list of types,
    no per-component knowledge, just the method field the IDD already declares
    next to the value it governs.

    `FractionOfAutosizedHeatingCapacity` still NEEDS sizing — the fraction is
    taken OF the autosized result — so any method naming "autosiz" counts as
    selecting it.
    """
    wanted = field_name.replace(" ", "").lower()
    for index in range(obj.numFields()):
        field = idd.getField(index)
        if not field.is_initialized():
            continue
        name = field.get().name()
        if not name.endswith("Method"):
            continue
        base = name[: -len("Method")].strip().replace(" ", "").lower()
        if not wanted.startswith(base):
            continue                    # a method, but it governs another field
        value = obj.getString(index)
        if not value.is_initialized() or not value.get().strip():
            return True                 # unset: the field stands as given
        chosen = value.get().strip().replace(" ", "").lower()
        # `endswith`, not `==`: a method choice names its field, sometimes
        # WITHOUT the leading qualifier. `AirLoopHVAC:UnitarySystem`'s
        # `Cooling Supply Air Flow Rate Method = SupplyAirFlowRate` selects
        # `Cooling Supply Air Flow Rate` — so an equality test skipped a field
        # EnergyPlus must size, making the guard silently blind in the one
        # direction it exists to prevent (Fable, PR #70). Verified 7/7 across
        # both families: the `CapacityPerFloorArea` skip is preserved and the
        # `SupplyAirFlowRate` hole is closed.
        return wanted.endswith(chosen) or "autosiz" in chosen
    return True                         # no governing method field


def _require_sizing_calculations(model, workspace, osm, advisories=()) -> None:
    """Refuse a model that has fields to size but no sizing run to size them.

    The three flags default to FALSE on a model and `run_energyplus` is the only
    thing in the product that turns them on, so anything reaching a backend
    without going through it — a direct `Local().execute(...)`, an upload to the
    simulation API, a hand-built `openstudio run` OSW — dies 0.3s into
    EnergyPlus with `For autosizing of <component>, a zone sizing run must be
    done`, which names the first autosized component rather than the cause. That
    cost three separate detours in one session.

    NARROW, in two directions, because two wider versions each refused valid
    work (Sol, `075` and `077`):

    * a model with NOTHING to size does not need a sizing run — the bare fixture
      runs clean with all three flags false;
    * needing to size something does not require all THREE calculations. A zone
      baseboard sizes fine with `zone=True, system=False, plant=False`, and the
      earlier "any autosized field requires all three" rule refused exactly that;
    * an autosized field a sibling `*Method` field steers EnergyPlus away from is
      never evaluated at all — see `_method_selects`.

    So the refusal is limited to the one case that certainly fails: something must
    be sized and NO sizing calculation will run at all. That is deliberately
    weaker than a per-dependency check, because mapping each autosizable
    component to the calculation that sizes it would mean enumerating hundreds of
    component types — the unbounded surface this module already refuses to model.

    WHAT THE DEFERRED CASE COSTS, corrected. An earlier version of this docstring
    said EnergyPlus "reports that case itself". **It does not.** Fable ran an
    autosized boiler on a plant loop with zone sizing on and plant sizing off:
    EnergyPlus completed with rc=0, no Severe and no Fatal, and silently derived
    a nominal capacity. The only signal anywhere was an OpenStudio translate-time
    advisory, which goes to the SDK log rather than `eplusout.err`. So this gate
    surfaces that advisory through `warnings.warn` instead of claiming a report
    that never comes.

    It CHECKS rather than repairs, deliberately:

    * `Remote` with `workflow_type='openstudio'` uploads `in.osm` itself, so the
      workspace-level trick `_ensure_output_requests` uses cannot reach it; only
      the model could be mutated, and `in.osm` must stay byte-comparable with
      what the Ruby runner saves;
    * a backend that silently enabled sizing would hide the caller's omission,
      and `run_energyplus` deliberately varies the two `runSimulationfor*`
      flags — a backend is not the place to decide what the run is.
    """
    autosized = autosized_fields(workspace)
    if not autosized:
        return                      # nothing to size; the flags are irrelevant
    sim = model.getSimulationControl()
    enabled = {
        "Do Zone Sizing Calculation": sim.doZoneSizingCalculation(),
        "Do System Sizing Calculation": sim.doSystemSizingCalculation(),
        "Do Plant Sizing Calculation": sim.doPlantSizingCalculation(),
    }
    if any(enabled.values()):
        # A sizing run exists, but not necessarily the one this model needs, and
        # EnergyPlus will not say so. Surface the SDK's own advice rather than
        # letting a partial-flag run derive a capacity in silence.
        import warnings
        for advisory in advisories:
            warnings.warn(f"{osm}: {advisory}", stacklevel=2)
        return
    raise RuntimeError(
        f"{osm} has {len(autosized)} autosized field(s) but NO sizing "
        f"calculation enabled, so EnergyPlus cannot size any of them — it will "
        f"fail on the first. Example: {autosized[0]}. Prepare the run through "
        "btap.simulation.runner.run_energyplus, which enables all three, or "
        "enable the one(s) this model needs before calling a backend directly."
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


def _result_files(res):
    """`{name: url}` from the results payload, whatever shape it arrives in.

    `res["files"]` is a LIST on the live service, and the old code called
    `.get` on it, so `'list' object has no attribute 'get'` came out of the
    DOWNLOAD step.

    PRECISELY WHICH PATH: the SUCCESSFUL one. `execute()` polls before it
    downloads and `_poll` raises on `status == "failed"`, so a failed job
    never reaches here — an earlier version of this note cited the failed
    job's `{"files": []}` payload, which cannot trigger it (Sol, PR #78). A
    COMPLETED job returns 17 entries whose keys are `download_url`, `name`,
    `phase_id`, `s3_key`, `size_bytes`; that list is what broke the call.

    THE POPULATED SHAPE IS NOW OBSERVED, not guessed — see below for the 17
    entries a completed job returns. The tolerant handling predates that
    observation and is retained deliberately rather than narrowed to it: three
    assumptions about this API — three have already been wrong against the live
    service (`_upload`'s route, `_phase_errors`' entries, and this) — a mapping
    is used as-is, a list of objects is read through the obvious name/url
    aliases, and anything else raises a message naming what actually arrived.
    An empty list yields no files, which lets the caller's own "produced no
    eplusout.sql" error be the one that surfaces.
    """
    files = (res or {}).get("files")
    if files is None:
        return {}, []
    if isinstance(files, dict):
        return files, []
    if isinstance(files, list):
        out, unreadable = {}, []
        for item in files:
            if not isinstance(item, dict):
                unreadable.append(type(item).__name__)
                continue
            name = (item.get("name") or item.get("filename")
                    or item.get("file") or item.get("key"))
            url = (item.get("url") or item.get("download_url")
                   or item.get("presigned_url") or item.get("href"))
            if name and url:
                out[str(name).rsplit("/", 1)[-1]] = url
            else:
                # NEVER the values — a `download_url` is presigned and carries
                # an STS token. The KEY NAMES are what a maintainer needs to
                # see, and they are not secret.
                unreadable.append("{" + ", ".join(sorted(item)) + "}")
        return out, unreadable
    raise RuntimeError(
        f"remote results: 'files' is a {type(files).__name__}, which this "
        "backend does not understand — expected a mapping of name to URL, or "
        "a list of objects carrying a name and a URL")


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
        #: `weather_s3_key` for a caller-supplied EPW, set per execute() when
        #: the model names a local file. None means "use the service library".
        self._weather_key = None

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
        self._weather_key = self._resolve_weather(run_dir)
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
        import openstudio

        from btap._compat import opt

        # Loaded and checked BEFORE the workflow branch: the `openstudio`
        # workflow uploads this OSM unchanged, so it needs the same guard as the
        # translated path — and 20 queue-minutes is a worse place to learn this
        # than here.
        model = opt(openstudio.model.Model.load(openstudio.path(str(osm))))
        if model is None:
            raise RuntimeError(f"remote backend: cannot load {osm}")
        # Translated once, BEFORE the workflow branch, and reused below. The
        # `openstudio` workflow uploads `in.osm` unchanged and the remote does
        # its own translation, so this one is spent purely on the guard — a
        # second of local work against a transfer plus a queue wait (Sol, `075`:
        # keep the ordering).
        idf, advisories = translate_capturing_advisories(model)
        _require_sizing_calculations(model, idf, osm, advisories)

        if self._workflow_type() == "openstudio":
            return osm.read_bytes(), "in.osm"
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
        # `/models/upload-url`, with `filename` as a QUERY parameter.
        #
        # This backend was validated against the live service once and the API
        # has moved since. Measured against it on 2026-10-03:
        #
        #   POST {endpoint}/models                        -> 404 Not Found
        #   POST {endpoint}/models/upload-url  (JSON body) -> 422
        #        {"detail":[{"type":"missing","loc":["query","filename"], ...}]}
        #   POST {endpoint}/models/upload-url?filename=X   -> 200
        #        {"model_id", "s3_key", "upload_url"}
        #
        # So `Remote` could not upload anything, and no test caught it because
        # the transport is injected and every test runs offline against a fake —
        # correct for unit tests, and exactly why a contract change went unseen.
        # The other three routes (`/simulations`, `/simulations/{id}`,
        # `/simulations/{id}/results`) matched the service's OpenAPI spec when
        # read on 2026-10-03 — DATED deliberately, because a spec read once has
        # the same shelf life as the fake this replaced, and claiming they
        # "still match" would read as a standing guarantee (Fable, PR #75).
        #
        # The response keys this reads are unchanged, so nothing downstream moves.
        query = urlencode({"filename": filename})
        reg = self._with_retry("upload", lambda: self._transport.post_json(
            f"{self._endpoint}/models/upload-url?{query}", {}))
        url = reg.get("upload_url")
        if url is None:
            raise RuntimeError(f"remote upload registration returned no upload_url (host {self._host()})")
        self._with_retry("upload-put", lambda: self._transport.put_bytes(url, payload))
        return reg.get("model_id")

    def _resolve_weather(self, run_dir: Path):
        """OUR EPW's key, or None to fall back to the service's library.

        Opt out with `upload_weather=False`, which the station-id path still
        needs for a model whose EPW is not on this machine.
        """
        if not self._opts.get("upload_weather", True):
            return None
        epw = self._local_epw(run_dir)
        if epw is None:
            return None
        return self._upload_weather(epw)

    def _local_epw(self, run_dir: Path):
        """The model's weather file, when it is a readable local path.

        `in.epw` beside the model first: the runner copies it there, and that
        is the file the LOCAL run used, which is the one a comparison needs.
        """
        beside = run_dir / "in.epw"
        if beside.is_file():
            return beside
        named = self._opts.get("epw")
        if named and Path(named).is_file():
            return Path(named)
        return None

    def _upload_weather(self, epw: Path):
        """Presign, PUT and return a `weather_s3_key` for OUR OWN EPW.

        Until hbix#107 (PR 108) there was no way to do this: the service
        resolved weather from its library by station id, and the comment on
        `_station_id` recorded that as a documented limitation. It mattered
        because the library DRIFTED — measured 2026-10-08, the same
        `CWEC2020`/`716240` label served an EPW 62 bytes different from our
        committed fixture, with the STAT and DDY further apart still and no
        `sha256_b64` on any of the three. A remote run on that file cannot be
        compared with a local baseline.

        `sha256_b64` is sent so the service BINDS the PUT to our digest: the
        upload either carries our exact bytes or it fails, which is the
        property a comparison needs. DDY and STAT are not uploadable and do
        not need to be — `attach_weather` (D-25) filters the design days INTO
        the model, so they travel inside the IDF.
        """
        import base64
        import hashlib

        payload = epw.read_bytes()
        # `.digest()`, NOT `.hexdigest()`: the service wants the base64 of the
        # BINARY sha-256, and base64 of the hex string is a well-formed value
        # that fails the comparison (hbix called this out explicitly).
        digest = base64.b64encode(hashlib.sha256(payload).digest()).decode()
        # The documented shape is the JSON body alone (hbix, 2026-10-08). The
        # models endpoint takes `filename` as a QUERY parameter and this one
        # does not; sending it both ways worked but said the same thing twice.
        reg = self._with_retry("weather-upload", lambda: self._transport.post_json(
            f"{self._endpoint}/weather/upload-url",
            {"filename": epw.name, "sha256_b64": digest}))
        url = reg.get("upload_url")
        key = reg.get("weather_s3_key")
        if url is None or key is None:
            # NOT a silent fall back to the station id: that would substitute
            # different weather for the file the caller asked for and report a
            # comparison as if it were like-for-like.
            raise RuntimeError(
                "remote weather upload returned no upload_url/weather_s3_key "
                f"(host {self._host()}) — the service may predate the "
                "caller-supplied weather path")
        headers = reg.get("required_headers") or {}
        self._with_retry("weather-put", lambda: self._transport.put_bytes(
            url, payload, headers=headers))
        return key

    def _submit(self, model_id: str) -> str:
        # OUR bytes when we have them, the service's library otherwise.
        body = {"model_id": model_id,
                "weather_s3_key": self._weather_key,
                "weather_station_id": (None if self._weather_key
                                       else self._station_id()),
                "weather_format": (None if self._weather_key else
                                   self._opts.get("weather_format", "CWEC2020")),
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
        files, unreadable = _result_files(res)
        out_dir = run_dir / "run"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in ("eplusout.sql", "eplusout.err"):
            url = files.get(name)
            if url is None:
                continue
            (out_dir / name).write_bytes(self._transport.get_bytes(url))
        sql = out_dir / "eplusout.sql"
        if not (sql.is_file() and sql.stat().st_size > 0):
            # If entries arrived that this backend could not read, SAY SO and
            # name their shape. Reporting only "produced no eplusout.sql"
            # would replace one masked remote diagnosis with another: the
            # caller would chase a missing file when the real problem is an
            # element shape we do not handle (Sol, PR #78).
            if unreadable:
                raise RuntimeError(
                    f"remote run {job_id} produced no readable eplusout.sql, and "
                    f"{len(unreadable)} result entr"
                    f"{'y was' if len(unreadable) == 1 else 'ies were'} in a shape "
                    f"this backend does not understand: "
                    f"{', '.join(unreadable[:5])} — expected a name "
                    "(name/filename/file/key) and a URL "
                    "(url/download_url/presigned_url/href)")
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
        """The service's phase errors, as one line.

        An entry is NOT always a string. The live service returns structured
        errors — `{"message": …}` and friends — and a bare
        `"; ".join(errors)` then raises
        `sequence item 0: expected str instance, dict found`. The damage is out
        of proportion to the typo: this runs only while BUILDING A FAILURE
        MESSAGE, so a diagnosable remote failure became an opaque TypeError
        that named neither the phase nor the cause. Found on the first real
        sizing run through the remote backend.
        """
        phases = (status or {}).get("phases") or []
        out = []
        for phase in phases:
            for err in (phase.get("errors") or []):
                if err is None:
                    continue
                if isinstance(err, str):
                    out.append(err)
                    continue
                if isinstance(err, dict):
                    # Prefer a human message, then the usual aliases, and fall
                    # back to the whole mapping rather than dropping detail on
                    # the floor — this text is the only diagnosis the caller
                    # gets.
                    for key in ("message", "msg", "error", "detail", "reason"):
                        value = err.get(key)
                        if isinstance(value, str) and value.strip():
                            out.append(value.strip())
                            break
                    else:
                        out.append(json.dumps(err, sort_keys=True,
                                              default=str))
                    continue
                out.append(str(err))
        return "; ".join(out[:5])

    def _workflow_type(self) -> str:
        return self._opts.get("workflow_type", "energyplus")

    def _engine_version(self):
        explicit = self._opts.get("engine_version")
        if explicit:
            return explicit
        return ".".join(engine.wheel_energyplus_version().split(".")[:2])

    # The service's own library, by station id. Used only when we have no
    # local EPW to upload: since hbix#107 a caller-supplied file is the
    # preferred path, because the library has been measured to drift from our
    # committed fixture and a drifting input cannot be compared.
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

    def put_bytes(self, url, payload, headers=None):
        # `headers` carries the presigner's `required_headers`. A checksum-bound
        # weather PUT is REFUSED without `x-amz-checksum-sha256`, and the bound
        # upload is the point: the service verifies our bytes rather than
        # taking our word (hbix#107).
        return self._request("PUT", url, body=payload, auth=False, raw=True,
                             headers=headers)

    def _request(self, method, url, body=None, json_body=False, auth=True,
                 raw=False, headers=None):
        req = urllib.request.Request(url, data=body, method=method)
        if auth and self._api_key:
            req.add_header("X-API-Key", self._api_key)
        if json_body:
            req.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            req.add_header(name, value)
        with urllib.request.urlopen(req) as res:
            if not 200 <= res.status < 300:
                raise RuntimeError(f"HTTP {res.status}")
            data = res.read()
        return data if raw else data.decode("utf-8")
