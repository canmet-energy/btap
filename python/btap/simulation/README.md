# btap.simulation

Run EnergyPlus on an OpenStudio model and get results back — **without** any
compliance layer. It depends on nothing else in the family but
`btap.audit`'s level of the stack; in practice, only the SDK wheel and a
provisioned EnergyPlus engine.

Use it when you just want to simulate a model and read the numbers — locally
now, or against a remote EnergyPlus service, through the same API.

## Quick start — the facade

```python
from btap import simulation

result = simulation.run(
    model,
    run_dir='/tmp/myrun',
    weather={'epw': 'weather.epw', 'ddy': 'weather.ddy'},  # optional; attaches design days
    run_period={'begin_month': 1, 'begin_day': 1, 'end_month': 1, 'end_day': 7},  # optional
)

result.clean        # True: E+ completed, no Fatal/Severe  (result.is_clean() also works)
result.run_dir      # '/tmp/myrun/run'
result.energy       # {'total_site_kwh': ..., 'end_uses_kwh': {...}, ...}
result.unmet_hours  # {'heating': ..., 'cooling': ...}
```

`sizing_only=True` runs a design-day sizing pass only; `energy` and
`unmet_hours` are then `None`.

## The engine — why no setup step

`pip install canmet-btap[tbd]` is meant to be sufficient, with no
environment variables and no manual EnergyPlus install. `engine.py` is what
makes that true. `ensure_energyplus()` resolves a verified binary of the
pinned version (`PINNED_VERSION`), in this order:

1. **Version gate** — the installed `openstudio` wheel must want the same
   EnergyPlus version this release pins.
2. **`BTAP_ENERGYPLUS`** — an explicit binary or install directory. Set but
   invalid **raises**; it never silently falls through.
3. **The `canmet-energyplus` companion wheel** — a hard, platform-marked,
   exact dependency on supported platforms. Fail-closed once imported.
4. **The local cache** (`cache_dir(version)`).
5. **`BTAP_ENERGYPLUS_ARCHIVE`** — install from a local release archive,
   for air-gapped or TLS-intercepted networks.
6. **Download** the official NREL release.

The result is memoized per process.

## Granular API — `btap.simulation.runner`

The backend-agnostic steps, if you want them individually:

- `attach_weather(model, epw=, ddy=)`
- `run_energyplus(model, dir, sizing_only=False, run_period=None, backend=None)`
- `is_clean_run(run_out_dir)`
- `energy_results(model)` — site energy + end-use breakdown (kWh)
- `unmet_occupied_hours(model)` — Facility setpoint-not-met hours
- `zone_unmet_occupied_hours(model)` — per-zone unmet occupied hours from
  the SQL (feeds the umbrella's capacity iteration)
- `request_run_period_variables(model, names)` — idempotent `'*'`-keyed
  `OutputVariable` requests at RunPeriod frequency
- `run_period_sums(model, variable_name)` — per-KeyValue run-period sums
  restricted to `EnvironmentType = 3`, so design days are excluded

`run_energyplus` prepares the run directory (sizing flags, run period,
`in.osm` + `in.osw`), delegates the actual EnergyPlus invocation to the
backend, then attaches `run/eplusout.sql` to the model.

## The local-vs-cloud seam — Backends

The one place execution happens is a `Backend`. Its contract: given a `dir`
that already contains `in.osm` + `in.osw`, run EnergyPlus so that
`dir/run/eplusout.sql` **and** `dir/run/eplusout.err` exist, and raise on
failure.

- **`Local`** (default) — translates the model in process with
  `ForwardTranslator`, writes `in.idf`, and runs the provisioned
  `energyplus` binary. (The Ruby gem shelled out to `openstudio run`
  instead; the artifacts and parse surface are identical — D-79, M2.)
- **`Remote`** — an AWS-Batch EnergyPlus service: upload the model,
  presigned S3 PUT, submit, poll, fetch results. Endpoint and key come from
  `HBIX_SIM_ENDPOINT` / `HBIX_API_KEY` or constructor arguments. The
  transport is an injectable `Http`, so the backend is fully exercised
  offline in tests. The key is never logged, echoed, or included in a raised
  message — errors name the host.

```python
from btap.simulation import Remote
simulation.run(model, run_dir=d, backend=Remote(endpoint='…', api_key='…'))
```

`set_default_backend(backend)` sets a process-wide default, which is how
`--backend remote` reaches the ~8 sites the compliance pipeline runs from
without threading a parameter through every phase. A per-call `backend=`
still wins.

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/simulation/
```

Engine-dependent tests skip without an engine; `BTAP_ENGINE_REQUIRED=1`
turns those skips into failures, which is what CI's `verify` job sets so a
missing dependency cannot pass vacuously.
