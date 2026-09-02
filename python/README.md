# canmet-btap

> This file is the **distribution's** front page — it ships as
> `canmet-btap`'s `long_description` on PyPI, which is why it describes the
> package rather than the repository. The repository README is one level up.

`canmet-btap` is the sole product implementation after R6 (D-84). It is one
Python distribution with five subpackages:

- `btap.audit`: SDK-free audit and coverage evidence
- `btap.modeling`: generic OpenStudio model authoring
- `btap.costing`: costing and the licensed-data boundary
- `btap.simulation`: EnergyPlus execution and remote simulation
- `btap.necb`: NECB rules, reference building, determination, report, and CLI

The enforced D-77 dependency direction is `necb` → `costing` → `modeling` →
`audit`, with `simulation` beside and depending only on `audit`. The completed
M0–M8 port history remains in [PORT_STATUS.md](../PORT_STATUS.md); it is a
historical record, not a description of a second live implementation.

## Install

From PyPI:

```bash
pip install 'canmet-btap[tbd]'
```

For development:

```bash
cd python
python3 -m venv .venv
.venv/bin/pip install -e '.[tbd]' pytest pytest-xdist import-linter ruff build
```

The distribution requires Python 3.11 or newer and OpenStudio 3.11. The exact
EnergyPlus companion is installed automatically on supported Windows and Linux
x86-64 platforms; other platforms use the version-verified provisioner.

## CLI

```bash
btap-compliance model.osm --epw weather.epw
python3 -m btap.necb.cli model.osm --simulate none
btap-necb-coverage --help
```

Exit codes are 0 compliant, 1 not compliant, 2 usage, 3 pre-flight rejection,
4 simulation failure, 5 internal error, and 6 no determination. A `--quick`
week is never reported as a code determination.

## Test

```bash
cd python
.venv/bin/pytest -n auto -q tests/
.venv/bin/lint-imports
.venv/bin/ruff check .
python3 -m unittest discover tests
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

NECB 3.1.1.7 uses native Python `canmet-tbd==3.5.2` through the `[tbd]` extra.
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
