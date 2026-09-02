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

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/simulation/
```

Engine-dependent tests skip without a CLI; `BTAP_ENGINE_REQUIRED=1` turns
those skips into failures, which is what the `verify` CI job sets so a
missing dependency cannot pass vacuously.
