# canmet-btap

> **Alpha software.** canmet-btap 0.4 is an alpha release: the command line,
> the Python API and the layout of `report.json` may change between releases,
> and each release's notes say what changed. Pin the version you build on.

> This file is the **distribution's** front page — it ships as
> `canmet-btap`'s `long_description` on PyPI, which is why it describes the
> package rather than the repository. The repository README is one level up.

`canmet-btap` is the sole product implementation after R6 (D-84). It is one
Python distribution with six subpackages:

- `btap.audit`: SDK-free audit and coverage evidence
- `btap.modeling`: generic OpenStudio model authoring
- `btap.costing`: costing and the licensed-data boundary
- `btap.simulation`: EnergyPlus execution and remote simulation
- `btap.codes`: NECB rules, reference building, determination, report, and CLI
- `btap.stock`: building-stock recipes — reading a model into one, and building
  a model from one

The enforced D-77 dependency direction is `codes` → `costing` → `modeling` →
`audit`, with `simulation` beside and depending only on `audit`; `stock`
consumes `modeling` and is a sibling of `codes`. The completed
M0–M8 port history remains in [PORT_STATUS.md](../PORT_STATUS.md); it is a
historical record, not a description of a second live implementation.

## Install

From PyPI — `--pre`, because this is an alpha and pip otherwise skips it and
installs the older 0.3.0:

```bash
pip install --pre canmet-btap
```

Straight from GitHub — the default branch, or any branch, tag or commit after
`@`:

```bash
pip install git+https://github.com/canmet-energy/btap
pip install git+https://github.com/canmet-energy/btap@main
```

Both install everything a compliance run needs, including the NECB 3.1.1.7
thermal-bridging engine, `canmet-tbd` — there is no extra to remember. The
Code makes the Table 3.2.2.x U-values *effective* transmittances, thermal
bridges included, and without the engine a reference building's envelope would
be under-insulated relative to the Code's intent.

The engine is pinned EXACTLY, because a later upstream release changes the
physics by roughly 43% on the same wall. If it is ever missing — a `--no-deps`
install, say — a compliance run still completes but warns loudly in its audit
trail and names the command that restores it.

For development, from the root of a clone (the standard src layout: the
package is under `src/btap/`, with `tests/` and `scripts/` beside it):

```bash
python3 -m venv .venv
.venv/bin/pip install -e . pytest pytest-xdist import-linter ruff build
```

The distribution requires Python 3.11 or newer and OpenStudio 3.11. The exact
EnergyPlus companion is installed automatically on supported Windows and Linux
x86-64 platforms; other platforms use the version-verified provisioner.

## CLI

```bash
btap-compliance model.osm --epw weather.epw
python3 -m btap.codes.cli model.osm --simulate none
btap-necb-coverage --help
```

Exit codes are 0 compliant, 1 not compliant, 2 usage, 3 pre-flight rejection,
4 simulation failure, 5 internal error, and 6 no determination. A `--quick`
week is never reported as a code determination.

## Public API

What you may import and depend on is declared, not implied. Each module's
`__all__` lists its public names; anything else — even when importable — is
internal and may change without notice.

| Module | Public |
|---|---|
| `btap` | `__version__` (import a subpackage directly; the root loads no SDK) |
| `btap.codes` | `performance_compliance`, `resolve`, `code_ids`, `editions`, `Ruleset`, `UnknownRuleset` |
| `btap.modeling` | `create`, `create_from_footprint`, `bar`, `apply_wwr`, `seed_constructions`, `SHAPES`, `render`, `floor_plans`, `systems`, `build_system`, `replace_system`, `remove_hvac_from_zones`, `plant_is_hvac_candidate`, `characterize`, `catalog_html`, `model_hvac_diagrams`, `hvac_icon_defs` |
| `btap.costing` | the domain modules `envelope`, `hvac`, `lighting`, `shw` |
| `btap.simulation` | `run`, `Result`, `Backend`, `Local`, `Remote`, `Http`, `engine`, `runner` |
| `btap.stock` | `build_from_recipe`, `write_recipe`, `identify_candidates`, `suggest`, `RecipeError`, and the `*_section` builders |
| `btap.audit` | `AuditLog`, `emit_coverage` |

Also public: the two console scripts with their flags and exit codes (above),
and `btap.codes.compliance.PreflightError`, which is how a refused input model
is raised.

**`report.json`.** Its public fields are declared in
`btap/codes/data/report_contract.json`, which ships in the package. They
apply to a completed run — exit 0, 1 or 6; a failed run flushes whatever
partial report exists.

| Field | Present | Value |
|---|---|---|
| `code`, `code_label`, `edition` | always | strings, e.g. `necb2020`, `NECB 2020`, `2020` |
| `compliant` | always | `true` or `false` is a determination; `null` means none was made |
| `hdd` | always | number, the heating degree-days used |
| `simulate` | always | `annual`, `sizing` or `none` |
| `proposed`, `reference` | always | objects; on a simulated reference-path run each carries `total_site_kwh` (what the verdict compares), `eui_kwh_per_m2` and `floor_area_m2` |
| `warnings` | always | list of strings |
| `compliance_determination` | when applicable | `code` (unqualified), `conditional` (holds only if the authority approves the listed items) or `no_determination` |
| `compliance_determination_reason` | when conditional | object |
| `no_determination` | when no determination | object, with the reason and what would fix it |
| `percent_of_target` | when determined | number |
| `tier` | when determined | integer, or `null` |

Removing or renaming one of these, or narrowing its values, is an API change.
Adding a field is not, so a report may carry more than this; unlisted fields
are internal.

**The promise.** canmet-btap is an alpha, and pre-1.0: a MINOR release (0.4 →
0.5) may change the public API, and its release notes say what changed; a
PATCH release does not. `btap-compliance --version` says so on a pre-release. Internal names may change in any release.
`tests/test_public_api.py` pins every list above exactly, so a public name
cannot be removed, renamed or added without that test being updated in the
same change; `tests/test_report_contract.py` holds every frozen scenario's
`report.json` to the report contract.

## Test

```bash
.venv/bin/pytest -n auto -q tests/
.venv/bin/lint-imports
.venv/bin/ruff check src tests scripts
PYTHONPATH=src python3 -m unittest discover tests
python3 scripts/wheel_smoke.py
```

The first command is the normal parallel suite; `unittest` is the serial
zero-install fallback. SDK, engine, rasterizer, sample, and thermal-bridging
dependencies are made mandatory in the `verify` CI job.

Behaviour changes that alter outputs must re-freeze
`../verification/scenarios/` from a clean tree and commit the reviewed baseline
diff with the code. Ruby product backports and live dual-CLI comparisons ended
at R6. The only remaining Ruby is the pinned external-oracle bridge under
`../legacy_pin/` and `../verification/oracle/`.

## Compatibility helpers

`btap/_compat.py` centralizes contracts inherited from the verified port:
round-half-away-from-zero, SDK Optional unwrapping, deterministic sorting,
HTML escaping, and `NullAudit`. `btap/_sdk.py` centralizes SDK handling. Use
these helpers rather than reimplementing their semantics at call sites.

## Thermal bridging

NECB 3.1.1.7 uses native Python `canmet-tbd==3.5.2`, a default dependency (D-109).
Without it, the pipeline continues but emits the explicit audited warning that
thermal bridging was not accounted for. The 3.6.x line changes uprate physics
and requires a deliberate family-wide rebaseline.

## Verification history

D-84 records the final cross-language attestation at commit
`85ab14352677093e24038d933cf1071e5b03431a`, GitHub Actions run
`33544573991`: 45 Ruby parity runs / 629 assertions, Ruby SmallOffice 3 runs /
62 assertions, 4 Python successor tests, live Leg C 23/23, frozen parity
scenarios, and zero parity skips. Post-R6 verification consists of Python frozen
scenarios plus live/frozen comparisons to the pinned `openstudio-standards`
oracle; it does not imply a surviving Ruby product.
