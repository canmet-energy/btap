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

## Hourly output — OFF by default, tiered, and read as plain Python

Hourly output is opt-in. Issue #147 measured the cost on an annual run of the
reference fixture, and the tiers follow the measurement:

| request | SQL | vs baseline |
|---|---:|---:|
| baseline (no hourly) | 0.72–0.88 MiB | 1.00x |
| `Electricity:Facility` only | 1.36 MiB | ~1.9x |
| `HOURLY_METERS` — all 13 | 3.39 MiB | ~4.7x |
| + the zone air heat BALANCE set (5 zones) | 45.43 MiB | ~63x |

**~0.35 MiB per hourly series per weather year** is the portable figure,
measured flat at 11, 12 and 59 series and independent of zone count (each
series is 8832 `ReportData` rows plus two indexes). The RATIOS are
fixture-specific — a complex system writes bigger tabular reports at baseline,
and the 63x line is a 5-zone figure. Tier 2 is `5 × zones` series, so a
50-zone building pays roughly 90 MiB for tier 2 alone.

```python
from btap.simulation import runner

runner.request_hourly_meters(model)          # tier 1, idempotent
runner.request_hourly_zone_variables(model)  # tier 2, per zone
# ... run ...
runner.request_hourly_plant_variables(model)  # the boiler heat + fuel
# ... run ...
elec = runner.hourly_series(model, "Electricity:Facility")      # J per hour
heat = runner.hourly_hot_water_plant_heat(model)                # district energy

demand = runner.demand_from_energy(elec["values"])              # J/h -> W
curve = runner.load_duration_curve(demand)                      # (hours, W)
curve_pct = runner.load_duration_curve(demand, percent=True)    # (% of time, W)
store = runner.energy_above(demand, 0.8 * curve[0][1])          # Wh to shave
```

The load duration curve is **duration against demand, sloping downward from
peak to minimum** — x in hours or percentage of time, y in demand. A raw meter
is joules PER HOUR, not watts, so `demand_from_energy` is what makes the y
axis a demand; the two differ by 3600. `interval_hours=` handles a non-hourly
series.

`hourly_series` REFUSES a name reported under more than one key, because no
single reduction suits them all — summing five `Zone Mean Air Temperature`
series gives a plottable lie. Use `hourly_series_by_key` and reduce
deliberately; `sum_by_key` adds them where that is right, and refuses a
ragged set rather than clipping.

It also refuses a name THIS MODEL never requested hourly, with a `KeyError`
naming the catalogue — `hourly_names(model)` is that catalogue. A misspelling
used to return an empty series, and `energy_above([], t)` is a cheerful `0.0`,
so the mistake propagated as a number. But a name the model DID request and
which simply had nothing to report comes back empty, because that is a real
answer: `ExteriorLights:Electricity` is in tier 1 and a building with no
exterior lights never reports it at all — EnergyPlus does not create a meter
with no contributing objects.

`hourly_series` returns `{'index': [(month, day, hour)], 'values': [...]}` —
PLAIN PYTHON, because this distribution depends on `openstudio` and the
EnergyPlus companion and nothing else. A caller that wants a frame writes
`pd.DataFrame(s['values'], index=s['index'])`.

**For DISTRICT ENERGY use `hourly_hot_water_plant_heat`, not a meter.**
`Heating:EnergyTransfer` is the facility sum of `Zone Air System Sensible
Heating Energy` — the zone air balance's NET sensible heating. It does NOT
exclude hydronic baseboards; on a baseboard-only system the meter, the
baseboard meter and the summed variable are all 33.40 MWh.

The gap is real and its cause is simultaneous cooling-then-reheat and the
heating of ventilation air to supply temperature — plant heat that offsets
cooling or outdoor air and never arrives as net zone sensible heating. A VAV
with NO baseboards shows 2.17x (35.07 zone-side, 76.13 at the plant). The
ratio is system-dependent, measured from 0.98 to 2.17, so what is general is
the direction: a zone-side net term cannot see a hydronic plant's obligation.

That function is the HOT-WATER PLANT's delivery, not "the building's heat
load": on a system with electric baseboards the boilers carried 41.63 MWh
while the baseboards delivered another 35.83 that no boiler sees. It sums
every boiler, because a lead/lag pair reports the idle one as zero. For a
source-neutral read use `hourly_series_by_key` on `Plant Supply Side Heating
Demand Rate` and pick the loop — but that is a RATE in W.

Modelling a district-energy connection AS A BOILER then answers both cases
from one run: `BOILER_HEAT_VARIABLE` is the district system's delivery
obligation and `BOILER_FUEL_VARIABLE` is the same building read as an on-site
boiler. No second model, so no chance of an unintended difference between
variants.

## The local-vs-cloud seam — Backends

The one place execution happens is a `Backend`. Its contract: given a `dir`
that already contains `in.osm` + `in.osw`, run EnergyPlus so that
`dir/run/eplusout.sql` **and** `dir/run/eplusout.err` exist, and raise on
failure.

One narrow precondition: **if the translated model has an autosized numeric
field and NO sizing calculation is enabled at all, a backend refuses the dir**
rather than letting EnergyPlus fail 0.3s in with a message naming the first
autosized component instead of the cause. `run_energyplus` enables all three, so
a dir it prepared always satisfies this.

Deliberately narrow, because two wider rules each refused runs that work (Sol
`075`, `077`):

- a model with nothing to size needs no sizing run — the bare fixture runs clean
  with all three flags off;
- needing to size something does **not** require all three calculations: a zone
  baseboard sizes fine with `zone=True, system=False, plant=False`;
- an autosized field a sibling `*Method` field steers EnergyPlus away from is
  never evaluated. With `Heating Design Capacity Method = CapacityPerFloorArea`
  it reads the per-area field and ignores the autosized one, which OpenStudio
  leaves `Autosize` by default.

So this gate UNDER-refuses by design: it will not catch a model whose autosized
boiler needs plant sizing while only zone sizing is on. **EnergyPlus does not
report that case.** It completes with `rc=0`, no Severe and no Fatal, and
silently derives a capacity. The only signal is an OpenStudio translate-time
advisory, which goes to the SDK log rather than `eplusout.err` — so the backend
captures it and re-emits it as a Python warning. An earlier version of this
section claimed EnergyPlus reported it; that was false (Fable, PR #70).

Autosized fields are identified by asking the IDD for each field's type, because
a text search for the `Autosize` token also matches an object merely NAMED
"Autosize". One residual: the check inspects the pre-ExpandObjects workspace
while EnergyPlus sizes the post-expansion IDF, so a template-bearing model whose
expansion supplies a default autosize would not be seen.

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
