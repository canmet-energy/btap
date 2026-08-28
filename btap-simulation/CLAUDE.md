# CLAUDE.md — btap-simulation

The lowest-level gem of the family: EnergyPlus execution with a pluggable
backend. **Only this gem and the umbrella (via its `Runner` alias) ever
simulate** — the domain gems are SDK-only by contract.

## The Python twin (btap.simulation)

This gem is fully mirrored by `python/btap/simulation/` (the port is complete —
D-79; `PORT_STATUS.md` at the repo root is the record). **A behaviour change
here is a change to BOTH implementations**: land it Ruby-first, port it, and
keep the Leg-B gates green — audit `action`/`article`/`ruling` strings are
compared VERBATIM cross-language, so even wording is load-bearing. A defect
found on either side is fixed on both or flagged in D-79, never silently on
one.

## Architecture

- `runner.rb` — `attach_weather!(model, epw:, ddy:)` (EPW + DDY design days),
  `run_energyplus!` (writes in.osm/in.osw, drives the `openstudio` CLI),
  `energy_results` (End Uses via TabularData GJ rows — SqlFile has NO
  fuel-agnostic end-use methods), unmet hours, `clean_run?`. District-energy
  accessors were renamed across SDK versions — probe with `respond_to?`.
  Also `request_run_period_variables!` (idempotent '*'-keyed OutputVariable
  requests) and `run_period_sums` (per-KeyValue sums restricted to
  `EnvironmentType = 3` — design days EXCLUDED; a shared DDY carries dozens
  and an unfiltered sum silently mixes them in). Both exist for the NECB
  8.4.4.13.(2)(g) aux-fuel election (D-52).
- `backends.rb` — `Backend` seam. `Local` runs `openstudio run -w in.osw`.
  `Remote` is a documented stub whose docstring mirrors the real
  AWS-Batch service (upload_model → presigned S3 PUT → submit_simulation →
  poll → get_simulation_results). The READY-TO-EXECUTE wiring plan —
  triggers, transport design, version guard, fidelity gate — is
  `docs/remote_backend_plan.md` (phylroy-approved 2026-08-10); implement
  from it, don't re-derive.

## Key facts / traps

- **`Remote` is IMPLEMENTED now** (2026-08-19), not a stub. Endpoint/key come
  from `HBIX_SIM_ENDPOINT` / `HBIX_API_KEY` (or constructor args); the transport
  is injectable, so `test_remote.rb` exercises the whole backend offline. The
  key is never logged, echoed, or put in a raised message — errors name the host.
- **Never shell out with a string; use the argv form.** Both CLI probes used
  `system('openstudio ... > /dev/null 2>&1')`, which is unresolvable on Windows
  cmd, so `openstudio_cli?` answered FALSE there with the CLI right in front of
  it. The `run` call interpolated the run dir UNQUOTED, so any path with a space
  (the Windows norm) split the `-w` argument and sent the log to a stray file —
  exit 0, silent misdirection. `system(cli, 'run', '-w', path, out:, err:)` has
  no shell, so neither can recur. Pinned by a Linux test using a dir with a space.
- **`OpenStudio.getOpenStudioCLI` gives the absolute path of the binary that
  loaded the SDK** — immune to PATH, correct on every platform, and the reason
  `openstudio_cli_path` needs no registry probe. `ENV['OPENSTUDIO_CLI']` wins
  over it as an escape hatch; a blank value is ignored, not honoured.
- **`Runner.default_backend`** is process-wide and exists because the umbrella
  calls `run_energyplus!` at ~8 sites — that is how `--backend remote` reaches
  them all without threading a parameter through every compliance phase. A
  per-call `backend:` still wins. Not thread-safe by design; forked children set
  their own.
- **`engine_version:` must match the model's version on the remote service** —
  version translation is FORWARD-ONLY; a server defaulting to an older
  OpenStudio cannot open a newer OSM (hard-won).
- Remote submits can transiently 503/timeout during service deploys or after
  idle — retry with backoff before concluding the service is down; submit is
  deployed separately from the read/upload endpoints.
- The remote OSM path (2-phase openstudio workflow) and the IDF path are both
  verified working against the live service; results matched local to the
  decimal.

## Tests

`cd btap-simulation && ruby test/test_XX.rb` (skip without the CLI).
