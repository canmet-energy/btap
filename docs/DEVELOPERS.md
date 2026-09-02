# Developing canmet-btap

This guide is for contributors changing the product. To run a compliance check,
start with the [user README](../README.md).

R6 (D-84) retired the five product Ruby gems. The repository now ships one
Python distribution, `canmet-btap`, whose import package has five subpackages:
`btap.audit`, `btap.simulation`, `btap.modeling`, `btap.costing`, and
`btap.necb`. Ruby remains only for the pinned external oracle in `legacy_pin/`
and `verification/oracle/`.

## Contract

- Product code uses the OpenStudio SDK directly, not `openstudio-standards` or
  measures.
- Import direction is `necb` → `costing` → `modeling` → `audit`, with
  `simulation` beside and depending only on `audit`. Import-linter enforces it.
- `btap.audit` is SDK-free and owns the shared audit schema:
  `{step, target, action, inputs, value, article, ruling, evidence, building, level}`.
- `article` cites a code requirement; `ruling` cites a D-XX interpretation.
  Warnings are never silent. Violations are uppercase and passes lowercase
  because report classification is case-sensitive.
- Rules target NECB 2020 and 2025 only. Article-coverage manifests state every
  partial or missing sentence and emit the corresponding warning.
- Python is authoritative. Intentional output changes include a clean-tree
  frozen-scenario re-freeze and reviewed baseline diff in the same change.

## Requirements

- Python 3.11 or newer
- OpenStudio SDK 3.11.0
- EnergyPlus 25.2.0 for simulation tests
- A UTF-8 locale
- Ruby 3.2 and Bundler only when running the surviving legacy oracle

### Devcontainer

The devcontainer provides Ubuntu 24.04, OpenStudio 3.11.0, EnergyPlus 25.2.0,
Python, Ruby/Bundler for the oracle, and a UTF-8 locale. It installs staged host
certificates before network downloads, copies `.mcp.json.example` to the
gitignored `.mcp.json`, and leaves the multi-gigabyte oracle clone opt-in.

```bash
bash .devcontainer/setup.sh --no-claude
bash .devcontainer/setup.sh --serena
```

### Python environment

```bash
cd python
python3 -m venv .venv
.venv/bin/pip install -e '.[tbd]' pytest pytest-xdist import-linter ruff build
```

`[tbd]` installs the exact `canmet-tbd==3.5.2` thermal-bridging line. Do not
casually move it to upstream 3.6.x: the uprate physics differ materially and
require an adjudicated rebaseline.

### MCP servers

`.mcp.json.example` is tracked and `.mcp.json` is gitignored. The template holds
no secret; Claude Code expands `HBIX_API_KEY` from the environment. One key
covers codes, geocoding, weather, building-stock, modelling, and simulation.
`HBIX_MCP_BASE_URL` is the only URL override and repoints all six together.

```bash
cp .env.example .env
chmod 600 .env
$EDITOR .env
set -a && source .env && set +a
```

`set -a` is required in an existing shell because plain `source` does not
export values to child processes. The two Python maintainers' clients use the
same variables and also support a missing `.mcp.json`:

```bash
python3 python/scripts/fetch_necb_8_4_text.py
python3 python/scripts/building_stock.py --help
```

CI uses mocked protocol tests and never requires live HBIX.

## Testing

Fast local suite:

```bash
cd python
.venv/bin/pytest -n auto -q tests/
.venv/bin/lint-imports
.venv/bin/ruff check .
```

Serial zero-install fallback:

```bash
cd python && python3 -m unittest discover tests
```

Repository checks from the root:

```bash
python3 python/scripts/necb_orphan_keys.py
python3 python/scripts/necb_8_4_6_curve_probe.py
python3 python/scripts/generate_necb_gem_coverage.py
python3 python/scripts/generate_necb_8_4_coverage.py
python3 python/scripts/generate_decisions_toc.py --check
cd python && python3 scripts/wheel_smoke.py
```

The `verify` CI job is the authoritative full-runtime lane: SDK, EnergyPlus,
rasterizer, sample corpus, thermal bridging, all 97 HVAC systems, and sizing
frozen scenarios are required rather than skipped.

## Decisions and generated docs

The canonical registry is `python/btap/necb/data/decisions.json`; the authored
record is [necb_decisions.md](necb_decisions.md). The registry tests enforce
unique ordered ids, document/registry agreement, generated TOC agreement, and
runtime citations. Regenerate the TOC with
`python3 python/scripts/generate_decisions_toc.py`; use `--check` in gates.

The two generated coverage documents are
[NECB_GEM_COVERAGE.md](NECB_GEM_COVERAGE.md) and
[NECB_8_4_COVERAGE.html](NECB_8_4_COVERAGE.html). Their retained filenames are
part of the evidence history; their inputs and code pointers are Python-owned
after R6. Do not edit either output by hand.

Section 8.4 source caches ship under `python/btap/necb/data/coverage/` for
offline, versioned use. Refresh them only as a maintainer operation with
`python3 python/scripts/fetch_necb_8_4_text.py` and review the generated-doc
diff.

## Frozen scenarios

`verification/scenarios/` contains 35 scenarios in three lanes:

- `python`: engine-free, every Python-suite run
- `verify`: sizing, in the OpenStudio container
- `parity`: annual, in the dispatch-only parity job

When a deliberate behaviour change affects output, run
`verification/scenarios/freeze.py` from a clean tree and commit the resulting
baselines and provenance with the change. The 31 scenarios that once had live
Ruby seals are now `python-only:post-handoff` and retain their retired seal plus
the final attestation identity. Four scenarios were already Python-only.

## Pinned oracle

`legacy_pin/REF` pins one full `openstudio-standards` SHA. Python-prepared models
and the Ruby probes in `verification/oracle/` produce live Leg-C evidence; the
committed goldens are in `verification/oracle/goldens/`. The whole-building
SmallOffice gate also generates its source model through this bundle.

```bash
BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install

LEGACY_PIN_REQUIRED=1 \
BUNDLE_GEMFILE="$PWD/legacy_pin/Gemfile" \
PYTHONPATH="$PWD/python:/usr/local/openstudio-3.11.0/Python" \
BTAP_PYTHON="$PWD/python/.venv/bin/python" \
  bash verification/live_leg_c.sh /tmp/live-leg-c
```

For a local fork checkout, set `LEGACY_PIN_REMOTE=/path/to/openstudio-standards`
for both `bundle install` and every run. Bundler compares the remote with the
lock. `LEGACY_PIN_REQUIRED=1` turns an absent oracle into failure rather than a
vacuous skip.

On a pin bump, dispatch `.github/workflows/test.yml` with
`export_goldens=true`, download the `oracle-goldens` artifact into
`verification/oracle/goldens/`, and commit `REF`, `Gemfile.lock`, goldens, and
attribution together. Never hand-edit a golden. Full instructions are in
[legacy_pin/README.md](../legacy_pin/README.md).

## CI

The workflow has four jobs:

| Job | Role |
|---|---|
| `lint` | orphan keys, coverage pointers and generated docs, decisions registry |
| `python` | import contracts, Ruff, full Python suite, installed-wheel smoke |
| `verify` | required SDK/EnergyPlus suite, NECB checks, sizing scenarios |
| `parity` | live pinned oracle, SmallOffice gate, annual scenarios, optional golden export |

`parity` is `workflow_dispatch` only; no schedule is declared. Run it whenever
the oracle pin changes.

## D-84 attestation

The final coexistence evidence is commit
`85ab14352677093e24038d933cf1071e5b03431a`, GitHub Actions run
`33544573991`: 45 Ruby parity runs / 629 assertions; Ruby SmallOffice 3 runs /
62 assertions; Python successor 4 tests; live Leg C 23/23; frozen parity
scenarios; lint, Python, verify, and every then-existing gem matrix job green;
zero parity skips. It is immutable historical evidence, not a claim that
product Ruby can still be run after R6.

The completed port chronology remains in [PORT_STATUS.md](../PORT_STATUS.md).
Do not rewrite that or the audit/decision records into present tense; update
only moved links when necessary.
