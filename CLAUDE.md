# CLAUDE.md — canmet-btap repository guide

This repository contains one product implementation: the Python distribution
`canmet-btap` (import `btap`), licensed **LGPL-3.0-or-later**. It has five
subpackages: `btap.audit`, `btap.simulation`, `btap.modeling`, `btap.costing`,
and `btap.codes`. `btap.codes` is the code-compliance layer, with the NECB
family under `btap.codes.necb` (D-86 renamed and re-shaped that package at
Stage 1 of the multi-edition plan; the old namespace is gone, and
`python/tests/test_no_legacy_namespace.py` keeps it gone). The former
`btap-*` Ruby gems retired at R6 under D-84.

Ruby still has one deliberate role. `legacy_pin/` bundles the pinned
`openstudio-standards` revision, and the Ruby files in `verification/oracle/`
probe that external oracle. They are verification infrastructure, not product
code. Do not translate their Ruby mechanically or delete them as "leftover"
product Ruby.

[README.md](README.md) is for building engineers. Contributor setup and test
lanes live in [docs/DEVELOPERS.md](docs/DEVELOPERS.md). `PORT_STATUS.md` and the
audit/decision documents are historical records; keep their period wording
unless a moved link itself is wrong.

## Package contract

- **Pure OpenStudio SDK.** Product code does not depend on
  `openstudio-standards`, measures, or legacy BTAP.
- **One distribution, five subpackages.** Dependency direction is
  `btap.codes` → `btap.costing` → `btap.modeling` → `btap.audit`, with
  `btap.simulation` beside and depending only on audit. Import-linter enforces
  this D-77 contract.
- **Code families live under `btap.codes`; data lives by EDITION.**
  `btap.codes.necb` holds the five NECB rule domains and
  `btap/codes/necb/editions/necb2025/` for what exists in one edition only.
  Every edition is an independent, complete snapshot under
  `btap/codes/necb/data/<code id>/` (rule files, `tables/`,
  `coverage/articles_8_4.json`, and the `manifest.json` that drives
  discovery). Nothing at runtime reads another edition's files — no `extends`,
  no alias, no fallback. Loaders resolve through
  `btap.codes.necb._data_root()`; `_set_data_root(..., _testing=True)` is a
  test-only hook, never an environment variable. Code-family-neutral data —
  `decisions.json`, the Section 8.4 disposition and `ATTRIBUTION.md` — stays
  in `btap/codes/data/`.
- **One AuditLog schema:**
  `{step, target, action, inputs, value, article, ruling, evidence, building, level}`.
  Levels are `decision`, `info`, and `warning`; warnings are never silent.
- **Two citation axes.** `article` cites the code requirement; `ruling` cites
  the adjudicated D-XX interpretation. Keep `ruling` top-level, never nested in
  `inputs`.
- **Audit text is case-sensitive.** Violations are SHOUTED and passes are
  lowercase because the report checklist classifier relies on that distinction.
- **NECB 2020 and 2025 only.** Do not imply support for 2011–2017.
- **Python is authoritative.** Behaviour changes are Python-only and require a
  clean-tree frozen-scenario re-freeze in the same change when outputs move.

## Commands

```bash
cd python
python3 -m venv .venv
.venv/bin/pip install -e '.[tbd]' pytest pytest-xdist import-linter ruff build coverage
.venv/bin/pytest -n auto -q tests/
.venv/bin/lint-imports
.venv/bin/ruff check .

# Repository tools, from the repository root
python3 python/scripts/necb_orphan_keys.py
python3 python/scripts/generate_necb_coverage.py
python3 python/scripts/generate_necb_8_4_coverage.py
python3 python/scripts/generate_necb_edition_delta.py --check
python3 python/scripts/generate_decisions_toc.py --check
python3 python/scripts/legacy_whatsnew.py
```

The zero-install serial fallback is `cd python && python3 -m unittest discover
tests`. Full SDK, EnergyPlus, rasterizer, sample, and thermal-bridging coverage
runs in the `verify` CI job. Live oracle checks run only in `parity`.

## Decisions and coverage

`python/btap/codes/data/decisions.json` is canonical. The authored document is
`docs/necb_decisions.md`; its TOC is generated. Adding a `## D-XX` heading means
adding the registry entry, and vice versa. A `kind: runtime` entry must be cited
by product Python source.

```bash
python3 python/scripts/generate_decisions_toc.py --check
cd python && python3 -m unittest \
  tests.necb.test_decisions_registry_sync \
  tests.necb.test_decisions_registry
```

Coverage is declared at the depth the evidence supports. Match article ids by
prefix when a whole article can be split into sentence-level entries. Do not
split a uniformly implemented article merely to inflate coverage. Use
`gap_owner: "modeller"` only when no model change can satisfy the requirement.
Generated coverage documents live in `docs/`; regenerate both and review their
diffs rather than hand-editing them.

The Section 8.4 article caches live in each edition's snapshot at
`python/btap/codes/necb/data/necb<edition>/coverage/articles_8_4.json` and ship
in the wheel. Refresh them with `python3 python/scripts/fetch_necb_8_4_text.py`;
ordinary runtime remains offline.

## Verification

The post-R6 verification model has two independent parts:

- `verification/scenarios/` holds 35 frozen Python pipeline scenarios across
  `python`, `verify`, and `parity` lanes. Intentional output changes use
  `verification/scenarios/freeze.py` on a clean tree and commit the baseline
  changes with the code.
- `legacy_pin/` plus `verification/oracle/` compare Python against the live,
  pinned legacy oracle. Leg C uses Python-prepared models and Ruby probes;
  committed goldens remain under `verification/oracle/goldens/`.

`legacy_pin/REF` is the sole oracle revision. A pin bump requires a complete
golden re-export and attribution of every changed comparison. Never hand-edit a
golden. `LEGACY_PIN_REQUIRED=1` is mandatory for local parity work so a missing
bundle fails instead of skipping. See [legacy_pin/README.md](legacy_pin/README.md).

The final cross-language attestation is immutable: commit
`85ab14352677093e24038d933cf1071e5b03431a`, GitHub Actions run
`33544573991`. It recorded 45 Ruby parity runs / 629 assertions, the Ruby
SmallOffice gate at 3 runs / 62 assertions, 4 Python successor tests, live Leg C
23/23, frozen parity scenarios, all four current CI jobs and every then-existing
gem matrix job, with zero parity skips. D-84 is the authority for the retirement
boundary; post-R6 freezes do not recreate cross-language evidence.

## CI

`.github/workflows/test.yml` has four jobs:

- **`lint`**: stdlib-oriented Python checks, coverage pointers/doc drift, and
  the decisions registry.
- **`python`**: import contracts, Ruff, the Python suite, and installed-wheel
  smoke on a bare runner.
- **`verify`**: the full SDK/EnergyPlus Python suite, rule verification, and
  sizing-lane frozen scenarios in `nrel/openstudio:3.11.0`.
- **`parity`**: dispatch-only live-oracle checks, whole-building archetype gate,
  and annual frozen scenarios. It is also where oracle goldens are exported.

There is no scheduled parity trigger. Dispatch parity whenever `legacy_pin/REF`
moves. Documentation-only pushes are path-ignored by the workflow, so run local
doc checks before merging documentation changes.

## Traps

**`-n auto` is sized for CI, not this host.** The devcontainer sees every
host core (48 on the reference machine) and every xdist worker imports the
OpenStudio SDK, so one `-n auto` run is ~50 SDK-loaded processes. Three of
those plus two EnergyPlus runs exhausted the 32 GB WSL2 VM on 2026-09-08 and
took the VM down. The devcontainer sets `PYTEST_XDIST_AUTO_NUM_WORKERS=8`;
keep it, never run two full suites concurrently, and run simulations one at
a time.

**The locale is load-bearing.** Generated documents contain UTF-8. CI and the
devcontainer force a UTF-8 locale; preserve it and use explicit UTF-8 when a
tool reads generated text.

**The Bundler remote is part of the lock.** If `LEGACY_PIN_REMOTE` points to a
local checkout, run `bundle install` with that value and keep using it. A
different remote makes `bundle check` report the source as not checked out.

**Thermal bridging has two distinct pins.** Product Python uses
`canmet-tbd==3.5.2`. The oracle bundle retains its Ruby tbd/osut/topolys triplet.
Upstream 3.6.x changes the physics by roughly 43% on the same wall, so upgrading
either side is an adjudicated rebaseline, never routine dependency maintenance.

**One MCP key, exported.** `HBIX_API_KEY` covers all six NRCan MCP servers and
the two Python maintainers' scripts, `python/scripts/building_stock.py` and
`python/scripts/fetch_necb_8_4_text.py`. `HBIX_MCP_BASE_URL` repoints all six.
Use `set -a && source .env && set +a`; plain `source` does not export variables
for child processes such as Claude Code.

**Corporate CAs come from the host.** The devcontainer stages trusted host CAs
before network downloads. Do not replace that with a network bootstrap that
needs working TLS in order to establish working TLS.

## History

The code was extracted from the `NatLabRockies/openstudio-standards` fork on
2026-08-16 and ported to Python under D-79. D-82 made Python the only changing
implementation; D-84 retired the five product Ruby gems at R6 while retaining
the external-oracle bridge. `PORT_STATUS.md` is the completed port record, not
the current architecture guide.
