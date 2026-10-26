# CLAUDE.md — btap.simulation

EnergyPlus execution with a pluggable backend, plus the engine-provisioning
ladder. **Only this subpackage ever simulates** — the domain subpackages are
SDK-only by contract, and import-linter enforces that `btap.simulation`
depends on nothing but `btap.audit`.

[README.md](README.md) is the API guide. This file is what a change *here*
costs.

## Architecture

- **`runner.py`** — `attach_weather(model, epw=, ddy=)` (EPW + DDY design
  days), `run_energyplus(...)` (writes `in.osm`/`in.osw`, drives the
  backend), `energy_results` (End Uses via TabularData GJ rows — SqlFile has
  NO fuel-agnostic end-use methods), `unmet_occupied_hours`,
  `zone_unmet_occupied_hours`, `is_clean_run`. District-energy accessors
  were renamed across SDK versions, so `_district` probes a list of method
  names rather than calling one. Also `request_run_period_variables`
  (idempotent `'*'`-keyed OutputVariable requests) and `run_period_sums`
  (per-KeyValue sums restricted to `EnvironmentType = 3` — design days
  EXCLUDED; a shared DDY carries dozens and an unfiltered sum silently mixes
  them in). Both exist for the NECB 8.4.4.13.(2)(g) aux-fuel election (D-52).
- **`backends.py`** — the `Backend` seam. `Local` runs the OpenStudio CLI.
  `Remote` drives the AWS-Batch service (upload → presigned S3 PUT → submit →
  poll → results) over an injectable `Http`, so the whole backend is
  exercised offline in tests.
- **`engine.py`** — has NO Ruby ancestor. It is the R5/D-83 engine
  resolution ladder that makes `pip install canmet-btap[tbd]` sufficient.
  Read the ladder before touching anything in it.

## The engine ladder (`ensure_energyplus`) — order is the contract

1. **Version gate.** The installed `openstudio` wheel's EnergyPlus version
   must equal `PINNED_VERSION`; mismatch raises rather than proceeding.
2. **`BTAP_ENERGYPLUS` override.** Set-but-bad **raises** — it never falls
   through. That is the premise of a frozen exit-4 scenario, so weakening it
   breaks a baseline, not just a test.
3. **The `canmet-energyplus` companion.** Outranks the cache deliberately:
   the cache rung returns UNVERIFIED, while the companion is pip-hash
   verified and is the shipped truth. **Fail-closed once imported** — only
   genuine absence (an optional platform) falls through; any defect after
   import raises.
4. **The unverified cache**, then 5. the `BTAP_ENERGYPLUS_ARCHIVE` rung,
   then 6. the NREL download.

Memoized process-wide in `_resolved`; `_reset_memo()` exists for tests.

**Testing this is where people get burned.** `tests/support.py` sets
`BTAP_ENERGYPLUS` process-wide when the container engine exists, so under
`pytest -n auto` rung 2 can answer for whichever rung is under test — two
companion tests passed serially and failed in parallel until
`EngineTestCase.setUp` started clearing the override. If you add a rung
test, clear the env in setup and install your fake explicitly; do not rely
on ambient state.

## Traps

- **`cwd` MUST be the run's own output directory.** `-x` (ExpandObjects)
  writes its intermediates (`expanded.idf`, …) into the CURRENT directory,
  so concurrent runs sharing a cwd clobber each other: **36 of 97 systems
  failed in the parallel sweep** before this, every one of them passing when
  run alone. (`openstudio run` runs E+ in the run directory for the same
  reason.) This is the single most expensive bug this module has had.
- **Never shell out with a string; use the argv form.** Paths with spaces
  are the Windows norm, and a shell string split the run-dir argument and
  sent the log to a stray file — exit 0, silent misdirection. A list argv
  has no shell, so it cannot recur. The Ruby gem paid for this twice; the
  comment in `Local.execute` says so on purpose.
- **There is no CLI probe any more.** Ruby's `Local` drove
  `openstudio run -w in.osw`; the Python one runs `ForwardTranslator` in
  process and then the provisioned `energyplus` binary directly, so
  `getOpenStudioCLI` / `OPENSTUDIO_CLI` have no Python successor. The
  artifacts and parse surface are identical (D-79, M2) — only the execution
  path changed. Do not reintroduce a CLI dependency to "match the docs".
- **`default_backend` is process-wide** and exists because the umbrella
  calls `run_energyplus` at ~8 sites — that is how `--backend remote`
  reaches them all without threading a parameter through every compliance
  phase. A per-call `backend=` still wins. Not thread-safe by design.
- **`engine_version` must match the model's version on the remote service.**
  Version translation is FORWARD-ONLY: a server defaulting to an older
  OpenStudio cannot open a newer OSM. Hard-won.
- **The API key is never logged, echoed, or put in a raised message** —
  errors name the host. `HBIX_API_KEY` covers every NRCan service; keep it
  that way.
- Remote submits can transiently 503 or time out during service deploys or
  after idle. Retry with backoff before concluding the service is down —
  submit is deployed separately from the read/upload endpoints.

## Two filters that are not optional on an hourly read

`_hourly_rows` carries both, and each was learned by measurement:

- **`EnvironmentType = 3`** — the D-56 trap `run_period_sums` already
  documents. Three sizing periods inflated an annual total by 1.8% on the
  reference fixture, and only the filtered figure reconciles to the tabular
  End Uses row.
- **`ReportingFrequency = 'Hourly'`** — subtler and worse. The same variable
  NAME can be reported at two frequencies in one run, because
  `request_run_period_variables` exists for the NECB 8.4.4.13.(2)(g) election.
  Without this clause the query also matched the RunPeriod rows, whose
  Month/Day/Hour are NULL, and in SQLite `NULL || 'x'` is NULL — so the read
  did not return junk, it returned **nothing**. A boiler series present as
  8832 hourly rows read back as zero hours. Every column is `COALESCE`d for
  the same reason.

Both are mutation-tested in `tests/simulation/test_hourly_layer.py`: removing
either fails named tests against a green control.

## `Heating:EnergyTransfer` is a ZONE-SIDE NET term — and it does NOT exclude baseboards

An earlier version of this section said it excluded hydronic baseboards. That
was FALSE and the false reason was in five places (Fable, `323` 3). It is the
facility sum of `Zone Air System Sensible Heating Energy`; on a baseboard-only
system the meter, `Baseboard:EnergyTransfer` and the summed variable are all
33.40 MWh.

The gap that justifies reading the plant is REHEAT AND VENTILATION-AIR
HEATING — plant heat that offsets cooling or conditions outdoor air and never
arrives as net zone sensible heating. A VAV with NO baseboards shows it at
2.17x. The ratio runs 0.98 to 2.17 across catalogue systems, so an assertion
of the form `plant > zone * 1.5` is a property of a FIXTURE, not of the
physics; the general statement is directional.

`hourly_hot_water_plant_heat` is the hot-water plant's delivery, NOT the
building's heat load: electric baseboards carried 35.83 MWh past the boilers
on one catalogue sibling. A model with electric or heat-pump heating reads a
fraction of its heating from it.

## Three silent-empty paths, and what replaced the guesses

An unrequested name, a misspelt name, a request skipped by a stale
idempotency check, a variable with no matching object (five district-hot-water
systems have no boiler; three have ELECTRIC boilers so the gas fuel variable
is empty) and a model with no SQL all returned `{'index': [], 'values': []}`
identically. So:

- idempotency keys on `(name, frequency)` in all three request helpers. Keyed
  on name alone, a pre-existing MONTHLY meter made `request_hourly_meters`
  report success while the hourly read came back as zero hours;
- `request_hourly_plant_variables` exists so the documented recipe requests
  what it reads;
- `hourly_series` REFUSES a multi-key name rather than summing, and refuses a
  name containing a quote rather than escaping it. The escaping was correct
  SQLite and untestable: a malformed literal and a correct query for an absent
  name both return empty, so dropping it passed every test TWICE — once
  against a test written specifically for it, whose quote was in a zone key
  and therefore in the result rather than the query;
- a name the model NEVER REQUESTED hourly raises `KeyError` naming
  `hourly_names(model)`. A name it DID request and that had nothing to report
  returns empty, because that is a real answer — `ExteriorLights:Electricity`
  is in tier 1 and EnergyPlus creates no meter for an end use a building does
  not have. The first version raised on every absence and made iterating
  tier 1 impossible; the boundary test found it.

## `OutputMeter` defaults to `meterFileOnly` — and that broke CI, not local

`request_hourly_meters` sets `setMeterFileOnly(False)` on every meter it
touches, and it must. `OutputMeter` defaults to `meterFileOnly = True`, which
the forward translator emits as `Output:Meter:MeterFileOnly` — the `.mtr`
file. Whether that data ALSO reaches the SQL `ReportData` the hourly readers
use is BUILD-DEPENDENT: it did on the devcontainer and did not on the
`verify` CI image, so the first version of this layer passed the local suite
SIX TIMES and failed `verify` with `8760 != 0`. `Output:Meter` always reaches
the SQL.

It also keeps ONE METER PER NAME, raising a coarser existing request to hourly
instead of adding a sibling. Two `OutputMeter` objects with the same name at
different frequencies are legal and translate to two IDF lines, but which is
honoured is NOT deterministic — `verify` ran the engine class on two xdist
workers (each re-runs `setUpClass`, so each simulated) and one honoured the
hourly request while `gw28` honoured a monthly sibling.

**Testing this needed `TestRequestHelpers`, a fresh `Model()` and ONE call.**
The engine class calls `request_hourly_meters` twice to assert idempotency,
and the second call takes the UPGRADE branch — which REPAIRED what a mutated
CREATE branch had left broken, so the mutation passed all 25 engine tests. An
idempotency fixture and a correctness fixture cannot be the same fixture: the
second call is a repair opportunity. Asserting only `Electricity:Facility`
failed for a different reason — it is the one with a monthly sibling, so it
takes the upgrade branch and leaves the other twelve unobserved.

## The fixture carries four deliberate oddities

Each exists because without it a mutation passes. Do not tidy them:

- a zone named `Thermal Zone 1|X` — a pipe used to truncate the key and read
  8760 plausible zeros;
- a zone named `Bob's Zone` — a quoted KEY must round-trip through the result;
- a MONTHLY `Electricity:Facility` request — a name-only idempotency check
  skipped the hourly one and reported success;
- a MONTHLY-ONLY `Cooling:EnergyTransfer` request — without a name reported at
  a non-hourly frequency ONLY, `hourly_names` filtered and unfiltered return
  the same set, and dropping its frequency filter passes every test.

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/simulation/
```

Engine-dependent tests skip without a CLI; `BTAP_ENGINE_REQUIRED=1` turns
those skips into failures, which is what the `verify` CI job sets so a
missing dependency cannot pass vacuously.
