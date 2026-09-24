# Developing canmet-btap

This guide is for contributors changing the product. To run a compliance check,
start with the [user README](../README.md).

R6 (D-84) retired the five product Ruby gems. The repository now ships one
Python distribution, `canmet-btap`, whose import package has five subpackages:
`btap.audit`, `btap.simulation`, `btap.modeling`, `btap.costing`, and
`btap.codes`. Ruby remains only for the pinned external oracle in `legacy_pin/`
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
- An edition is selected by CODE ID: `code="necb2020"` on every public
  function, `--code necb2020` on the CLI (`btap.codes.code_ids()` is the
  list, `necb2020` the default). The per-edition data accessors take
  `edition="2020"`. `report.json` carries `edition`, `code` and
  `code_label`; audit entries that record the ruleset carry `code` and
  `edition` in `inputs` (D-87).
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
.venv/bin/pip install -e '.[tbd]' pytest pytest-xdist pytest-cov import-linter ruff build
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

Line coverage of `btap` (the frozen scenarios run in subprocesses, so they are
left out as they measure nothing):

```bash
cd python
.venv/bin/pytest -n auto -q --cov=btap --cov-report=term:skip-covered \
  --ignore=tests/necb/test_frozen_scenarios.py tests/
```

CI's `verify` job measures the same, publishes a per-module summary and an
HTML report, and fails below its floor (`--cov-fail-under` in
`.github/workflows/test.yml`). The baselines are recorded in
[necb_rule_verification.md](necb_rule_verification.md).

Repository checks from the root:

```bash
python3 python/scripts/necb_orphan_keys.py
python3 python/scripts/necb_8_4_6_curve_probe.py
python3 python/scripts/generate_necb_coverage.py
python3 python/scripts/generate_necb_8_4_coverage.py
python3 python/scripts/generate_decisions_toc.py --check
cd python && python3 scripts/wheel_smoke.py
```

The `verify` CI job is the authoritative full-runtime lane: SDK, EnergyPlus,
rasterizer, sample corpus, thermal bridging, all 97 HVAC systems, and sizing
frozen scenarios are required rather than skipped.

**Running today's tests against an OLDER product tree** — to show a new test
fails without its fix — needs more than `PYTHONPATH`. The venv installs `btap`
as an editable install whose finder resolves the package to this checkout
whatever `sys.path` says, so the tests silently exercise the current code and
pass. Export the old tree (`git archive <ref> python/btap | tar -x -C <dir>`),
then, before importing `btap`, drop the editable finder and put the export
first:

```python
sys.meta_path[:] = [f for f in sys.meta_path
                    if 'editable' not in (type(f).__module__ + repr(f)).lower()]
sys.path.insert(0, EXPORT)
import btap
assert btap.__file__.startswith(EXPORT)   # never skip this check
```

## Decisions and generated docs

The canonical registry is `python/btap/codes/data/decisions.json`; the authored
record is [necb_decisions.md](necb_decisions.md). The registry tests enforce
unique ordered ids, document/registry agreement, generated TOC agreement, and
runtime citations. Regenerate the TOC with
`python3 python/scripts/generate_decisions_toc.py`; use `--check` in gates.

The two generated coverage documents are
[NECB_COVERAGE.md](NECB_COVERAGE.md) and
[NECB_8_4_COVERAGE.html](NECB_8_4_COVERAGE.html). Their retained filenames are
part of the evidence history; their inputs and code pointers are Python-owned
after R6. Do not edit either output by hand.

Section 8.4 source caches ship inside each edition's own snapshot at
`python/btap/codes/necb/data/necb<edition>/coverage/articles_8_4.json` for
offline, versioned use; the Crown-copyright notice and the cross-edition
disposition stay code-family-neutral in `python/btap/codes/data/coverage/`.
Refresh them only as a maintainer operation with
`python3 python/scripts/fetch_necb_8_4_text.py` and review the generated-doc
diff.

## Frozen scenarios

`verification/scenarios/` contains 45 scenarios in three lanes:

- `python`: engine-free, every Python-suite run
- `verify`: sizing, in the OpenStudio container
- `parity`: annual, in the dispatch-only parity job

When a deliberate behaviour change affects output, run
`verification/scenarios/freeze.py` from a clean tree and commit the resulting
baselines and provenance with the change.

**Merge a freeze-carrying PR with GitHub's "Create a merge commit" (D-95).** A
PR that changes frozen baselines or the manifest provenance counts as
freeze-carrying — look for `manifest.json` or `baselines/` in the diff.
`freeze.py` records the commit it ran at — a branch commit — and
`test_manifest_integrity` requires that commit to be an ancestor of `HEAD`,
which is a separate claim from the content hashes the manifest already pins.

**Neither "Squash and merge" nor "Rebase and merge" will do.** Both give the
merged commit a new SHA, so the recorded branch commit is no longer an
ancestor and `main` goes red *after* the merge while every branch check was
green. Rebase merging is disabled on this repository, so that route is closed
mechanically — but it is the route that never bit: both measured breakages were
squashes, and the squash button is still there and still wrong for these PRs.
This is not theoretical: `main` failed that way for three days across two
merges, with a different stale pointer each time.

When it does happen the `main-red` job opens an issue naming the run and this
recovery path, assigned to `vars.MAIN_RED_ASSIGNEE` (or whoever pushed), and
closes it again when a push run on `main` is green. It tells someone; it does
not block anything.

If one is squash- or rebase-merged by mistake, re-freeze from the resulting `main` commit
and submit the minimal re-pin immediately; a pure repair moves only provenance
metadata and no baseline. And check the post-merge `main` run before calling
the work done — green PR-head CI is a different claim (D-94).

The 31 scenarios that once had live
Ruby seals are now `python-only:post-handoff` and retain their retired seal plus
the final attestation identity. The other fourteen are Python-only from their first
freeze: four that were already Python-only at the handoff, four NECB 2025
scenarios first frozen after R6, the two D-89 purchased-heating scenarios, and
the four DF-17 hydronic-VAV scenarios. A scenario authored after the handoff must
carry its own `python-only:` seal rather than inherit the default, or
`all_scenarios()` converts it to `post-handoff` and it claims a cross-language
attestation that was never run for it.

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

The workflow has six jobs:

| Job | Role |
|---|---|
| `lint` | orphan keys, coverage pointers and generated docs, decisions registry |
| `python` | import contracts, Ruff, full Python suite, installed-wheel smoke |
| `verify` | required SDK/EnergyPlus suite, NECB checks, sizing scenarios |
| `parity` | live pinned oracle, SmallOffice gate, optional golden export |
| `parity-scenarios` | annual frozen scenarios, in parallel with `parity` |
| `main-red` | on a failed push run on `main`, opens/updates an assigned issue (D-94) |

`parity` and `parity-scenarios` are `workflow_dispatch` only; no schedule is
declared. Run them whenever the oracle pin changes.

`verify`, `parity` and `parity-scenarios` run in the CI image
`ghcr.io/canmet-energy/btap-ci`, built from `infra/ci-image/Dockerfile` by the
`ci-image` workflow under a content-addressed tag; `test_ci_image_pin.py` keeps
`test.yml` on the current one. With the repository variable
`CI_RUNNER=necb-ci`, every job but `lint` runs on a 36-vCPU AWS CodeBuild runner
([infra/aws-ci/README.md](../infra/aws-ci/README.md)).

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
