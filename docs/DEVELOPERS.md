# Developing the NECB gem family

Everything a contributor needs. If you only want to **run** a compliance check,
start at the [README](../README.md) instead — this file assumes you are changing
the gems, not using them.

The family map and the per-gem API guides are in the
[README](../README.md#the-nine-gems).

## The family contract

Every gem in this repository obeys the same rules:

- **Pure OpenStudio SDK.** No `openstudio-standards`, no measures, no BTAP.
- **Never simulates.** Only the umbrella (`btap-necb`) runs EnergyPlus.
- **One AuditLog schema** —
  `{step, target, action, inputs, value, article, ruling, evidence, building, level}`,
  levels `:decision | :info | :warning`. **Warnings are never silent.** The class
  lives in `btap-audit`; every other gem's `audit_log.rb` is a three-line
  alias of it.
- **Two citation axes.** `article:` cites the code that mandates a value;
  `ruling:` cites the adjudicated decision that says how we read it. Every id
  must exist in
  [btap-necb/docs/necb_decisions.md](../btap-necb/docs/necb_decisions.md)
  and its machine-readable mirror; a drift test enforces both directions.
- **Audit text convention:** violations are SHOUTED, passes are lowercase — the
  report's checklist classifier is deliberately case-sensitive about this.
- **Article-coverage manifests.** Each vintage ruleset JSON declares what it
  implements; partial and not-implemented entries warn on every run.
- **Vintages 2020 and 2025 only.** 2011–2017 backfills are deferred.

## Requirements

- Ruby 3.2.2
- OpenStudio SDK 3.11.0 (`require 'openstudio'` must succeed; the SDK is
  deliberately not declared as a gem dependency)
- The `openstudio` CLI, for the tests that run EnergyPlus
- **A UTF-8 locale.** Without one, Ruby's default external encoding is US-ASCII
  and `File.read` of anything the gems emit — `plan_svg.rb` writes em dashes and
  `m²`, the decisions doc is full of them — raises
  `invalid byte sequence in US-ASCII`.

### Devcontainer

`.devcontainer/` provides all of the above: Ubuntu 24.04, Ruby 3.2.2,
OpenStudio 3.11.0, EnergyPlus 25.2.0, and `LANG=en_US.UTF-8`, on the
`canmet/os_sdk_container:3.11.0` image. Open the repo in VS Code and reopen in
the container. `postCreate` installs NRCan certificates when it detects that
network, installs **Claude Code**, installs `.mcp.json` from the template,
verifies the toolchain, and prints the common commands.

```bash
bash .devcontainer/setup.sh --no-claude   # skip the Claude Code install
bash .devcontainer/setup.sh --serena      # also add uv + the Serena MCP server
```

It deliberately does **not** clone the legacy oracle — that is gigabytes, so it
stays opt-in.

### MCP servers

`.mcp.json.example` is tracked; `.mcp.json` is **not** (the family rule is never
to stage it). Setup copies the template, which carries **no key** — Claude Code
expands `${VAR}` in `url` and `headers`, so the secret stays in your
environment.

The key lives in a gitignored `.env`, using the same variable name and the same
loading mechanism as [canmet-energy/bluesky](https://github.com/canmet-energy/bluesky),
so one `.env` works in both repositories:

```bash
cp .env.example .env
chmod 600 .env
$EDITOR .env        # set HBIX_API_KEY
```

`.devcontainer/setup.sh` appends an auto-load block to `~/.bashrc`, so a **new
terminal** has the key exported. To load it into the shell you are already in:

```bash
set -a && source .env && set +a
```

The `set -a` is load-bearing. A plain `source .env` sets shell variables without
**exporting** them, so Claude Code — a child process — expands `${HBIX_API_KEY}`
to nothing and all six servers send an empty `X-API-Key`. That surfaces as an
opaque 403, not as a missing-key message.

**One key, one name.** `HBIX_API_KEY` covers all six MCP servers (codes,
geocoding, weather, building-stock, modelling, simulation) and both Ruby scripts
that call them directly — those scripts expand the `${VAR}` placeholders in
`.mcp.json` themselves and abort with a clear message when the key is
unresolvable. There is deliberately no per-server key alias, because the servers
do not take different keys.

`HBIX_MCP_BASE_URL` is the only other knob: it repoints all six servers at
once — for the Ruby scripts and for `.mcp.json` alike — at a staging or local
stack. There are no per-server overrides for the URL either; the scripts append
their own `/<server>/mcp` path. That also keeps a missing `.mcp.json` a
supported configuration without hardcoding a host in the scripts.

## Testing

Each gem is self-contained:

```bash
cd btap-modeling && ruby test/test_catalog.rb
```

Cross-gem rule verification runs from the repository root:

```bash
rake necb:verify        # orphan-key lint + 8.4.6 curve probe + hostile-outcome tests
rake necb:coverage_doc  # regenerate the coverage documents
```

### Legacy-parity gates

The parity suites compare against a **pinned revision** of the NECB/BTAP
implementation in the `NatLabRockies/openstudio-standards` fork. See
[legacy_pin/README.md](../legacy_pin/README.md) for the pinning mechanism and the
bump workflow.

The tie to that fork is `legacy_pin/REF` — **one commit SHA, not a branch and
not a git remote**. Nothing in this repository points at the fork's history, so
"has upstream moved?" cannot be answered by `git log` here. Ask instead:

```bash
rake legacy:pin                                        # what we are pinned to
rake legacy:whatsnew                                   # what has landed since, on nrcan
LEGACY_FORK=/path/to/openstudio-standards rake legacy:whatsnew   # instant, offline
BRANCH=develop rake legacy:whatsnew                    # a different fork branch
```

`legacy:whatsnew` lists the commits between the pin and the fork branch and
groups every changed path by the gem that should care, so you can judge what is
worth absorbing. Absorbing means **bumping the pin and re-running the gates** —
never copying code across. With no local checkout it fetches a blobless mirror
under `tmp/` (first run only; GitHub honours the blob filter, a local `file://` path does not — prefer `LEGACY_FORK`).

Install the oracle once (it defaults to cloning the fork from GitHub — a
multi-gigabyte, one-time cost):

```bash
BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install
```

If you already have the fork checked out locally, point at it instead — bundler
git-clones from the path, which is far faster and works offline. Use the **same**
`LEGACY_PIN_REMOTE` for install and for every run: it is part of the resolved
lockfile, so changing it re-resolves and re-clones.

```bash
cd btap-necb
LEGACY_PIN_REQUIRED=1 \
LEGACY_PIN_REMOTE=/path/to/openstudio-standards \
BUNDLE_GEMFILE=../legacy_pin/Gemfile \
  bundle exec ruby test/test_apply_parity.rb
```

`LEGACY_PIN_REQUIRED=1` turns "oracle not bundled" from a skip into a failure —
CI and verification runs should always set it, because a skipped parity gate is a
green-but-vacuous gate. All eleven gates live in `btap-necb/test/`,
prefixed by their source domain: envelope (4), loads (3), lighting (3) and
shw (1).

## Three-way verification (D-78)

```
            Leg A (the eleven gates)
  oracle ◄──────────────────────────► Ruby gems
    │  Leg C: frozen goldens              │  Leg B: dual-CLI run diffs
    ▼  (test/goldens/oracle/,             ▼  (verification/compare_runs.py)
  goldens ◄──────────────────────────── the Python port
```

- **Leg C goldens**: exported from the PINNED oracle by
  `btap-necb/scripts/export_oracle_goldens.rb` via the same probe code the
  gates run (`test/support/oracle_probes.rb`). Regenerate whenever
  `legacy_pin/REF` bumps: dispatch `test.yml` with `export_goldens=true`,
  download the `oracle-goldens` artifact, commit.
  `test_oracle_goldens_current.rb` fails the parity job until you do.
- **Leg B differ**: `python3 verification/compare_runs.py RUN_A RUN_B`
  (rules in `verification/spec.json`); `bash verification/selftest.sh`
  runs the corpus twice through the Ruby CLI and proves zero-diff.


## The Python port (`python/`, D-79)

A second implementation lives in `python/` — one pip distribution, `btap`,
with five subpackages mirroring the gems. The port is COMPLETE (M0–M8,
2026-08-28), verified against the gates above; `PORT_STATUS.md` at the repo
root is the full record of what landed and what each milestone was gated
on. Standing rule: the two implementations move TOGETHER — a behaviour
change lands Ruby-first (Ruby is the Leg-B baseline), then its Python twin,
or not at all.

```bash
cd python
python3 -m venv .venv && .venv/bin/pip install 'openstudio~=3.11.0' pytest pytest-xdist import-linter
.venv/bin/pytest -n auto tests/     # the whole suite, parallel (~2.5 min)
.venv/bin/lint-imports              # the D-77 arrows + audit stays SDK-free
python3 -m unittest discover tests  # zero-install fallback, serial
```

Cross-cutting Ruby-vs-Python semantics are solved once in `btap/_compat.py`
(stdlib-only, so `btap.audit` keeps running on a runner with no OpenStudio)
and `btap/_sdk.py`. **Use those helpers rather than the raw Python
equivalents** — `ruby_round` (half away from zero, not banker's),
`ruby_div` (Ruby float division never raises), `opt`/`opt_or`,
`sorted_by_name`, `NullAudit`. Each exists because the naive translation
changes results silently; D-79 records why.

EnergyPlus comes from `btap.simulation.engine`, which provisions a pinned,
sha256-verified build (`BTAP_ENERGYPLUS` overrides it;
`BTAP_ENERGYPLUS_ARCHIVE` side-loads on a TLS-intercepting network). The
wheel carries the SDK and the ForwardTranslator but no engine; the umbrella
CLI ships as the `btap-compliance` console script (M6), and
`python -m btap.necb.cli` is the no-install spelling.

The Leg-B cross-language gate (M6): `CLI_B=python bash
verification/selftest.sh` runs the Ruby and Python CLIs over the same corpus
and diffs every pair's `audit.json`/`report.json` under the rules in
`verification/spec.json`; `TIER=sizing|annual` climbs into real EnergyPlus.
CI runs `none`+`sizing` in the `verify` job and `annual` in the
dispatch-only `parity` job.

Thermal bridging (M7, D-79 Option A) uses **py-tbd** — the native Python
port of rd2/tbd — pinned to its `tbd-3.5.2-compat` branch, the revision
verified against the SAME Ruby TBD 3.5.2 / OSut 0.8.2 baseline the parity
oracle is frozen on (py-tbd main ports 3.6.0, a physically different
uprate):

```bash
cd python && .venv/bin/pip install '.[tbd]'   # the SHA-pinned engine
BTAP_TBD_REQUIRED=1 .venv/bin/pytest tests/necb/test_envelope_thermal_bridging.py
```

The suite asserts the engine identity (`tbd.VERSION`/`UPSTREAM_SHA`), and
the Ruby-vs-Python TBD gates additionally need the pinned Ruby triplet
(`gem install $(ruby legacy_pin/tbd_triplet.rb)`). `BTAP_TBD_REQUIRED=1`
turns absence into failure — CI's `verify` job supplies both engines.


## History

These gems were developed inside a fork of
[openstudio-standards](https://github.com/NatLabRockies/openstudio-standards)
between July and August 2026 and extracted here with their full history intact.
The fork remains the source of the pinned parity oracle.
