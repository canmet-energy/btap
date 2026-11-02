# Stock and retrofit model authoring: a performance profile and a build recipe

**Status:** planned, nothing implemented. Issues #183 (the profile parameter)
and #184 (the recipe). phylroy's use case, 2026-11-02: the 28 campus
archetypes under `models/` were authored by hand and should be generated
programmatically. They are pre-1960, 1960-1979, 1980-2004 and 2005-2014
buildings on which `btap-compliance` may never run.

**Decided already:** the library ships NO vintage data. `btap.stock` reads a
recipe of concrete values; resolving vintage x location x building type to
those values is the caller's business.

## The gap, measured

`btap.modeling` is vintage-neutral by its import contract and NOT by its
content.

    btap.modeling imports btap.codes      zero imports, enforced by
                                          import-linter (D-77)
    efficiency APPLIERS                   btap.codes.necb.hvac.efficiency only

So no NECB 2020/2025 applier runs on a model built through `modeling` alone.
That half works as designed. But the builders carry performance of their own —
37 calls across `btap/modeling/**`:

| count | what | where |
| --- | --- | --- |
| 10 | DX cooling/heating curves | `hvac/components/coils.py:78-82, 126-130` |
| 11 | heat-recovery limits and time constants | `hvac/components/ecm_air.py:256-266` |
| 6 | defrost EIR curves | `ecm_air.py:45,57,249`; `doas_pthp.py:46,86` |
| 2 | `setRatedHeatingCOP(4.0)`, `setGrossRatedCoolingCOP(4.0)` | `ecm_air.py:241-242` |
| 2 | `setPressureRise` 640 Pa / 0.2 inH2O | `mau_ptac.py:140`; `unit_heaters.py:22` |
| 2 | `setMinimumPartLoadRatio(0.2)` | `hp_plant_fancoils.py:149,191` |
| 1 | `WINDOW_AC_EER = 8.5` Btu/W-h | `zone_terminal.py:24,115` |
| 1 | `setCoolerDesignEffectiveness(0.9)` | `evap_cooler.py:41` |
| 1 | ERV bypass control type | `vav_reheat.py:180` — already config-driven |

The ten DX curves are the significant ones. `modeling/hvac/data/curves.json`
records its own provenance:

> NECB reference performance curves, extracted from openstudio-standards
> necb/**NECB2011**/hvac_systems.rb `add_onespeed_DX_coil` (cooling) and
> `add_onespeed_htg_DX_coil` (heating).

Their NECB 2011 origin is not a vintage escape hatch: all 21 of those
2011-derived curves were verified against the current editions' own text and
agree, so they are effectively current-edition curves. For a pre-1960 building
they are wrong in the same direction NECB 2020 would be.

`build_system`'s docstring already says **"Topology only: run your sizing and
code-efficiency passes afterwards"**. Those 37 values contradict it, so this
work brings the code into line with its own documented contract rather than
changing the contract.

## The envelope half is already right, and is the pattern to copy

|  | `modeling/envelope` | `modeling/hvac` |
| --- | --- | --- |
| embedded performance data | **none** — `data/` holds only `ATTRIBUTION.md` | 37 values |
| hard-coded conductance literals | **0** | several |
| how a target is supplied | a PARAMETER: `opaque_at_conductance(model, construction, conductance)` | baked in |
| defaults | `seed_constructions(model, *, opaque_r_si=2.0, window_u_si=2.5, ...)` | n/a |

`seed_constructions`' docstring is the precedent worth copying — its defaults
are *"deliberately POOR insulation... The seed exists to be improved on"*, so a
caller who forgets to retarget produces an obviously wrong model. The HVAC
defaults fail that property in the other direction: NECB reference DX curves on
a 1955 barracks are **plausible**, which is worse than conspicuous.

## The extension point already exists and is already used

This is not a new parameter. One performance value already flows catalogue ->
config -> builder:

    systems.json:749     "erv_bypass_control_type": "BypassWhenOAFlowGreater..."
    builder.py:122,132   config is "per-call overrides merged over the catalog
                         row"; resolved = {**catalog_row, **config}
    vav_reheat.py:69,181 validates the key, then
                         setHeatRecoveryBypassControlType(config['...'])
    reference.py:1517    the NECB reference path is a live caller passing config=

The other 36 are literals in builder bodies. The work is to do what
`vav_reheat` already does, for them.

## Phase 1 — the honest inventory, as a test

Pin the current 37 before moving anything: a test that walks
`btap/modeling/**` for performance-setting calls and asserts the set matches a
committed fixture, the same shape as `sdk_crash_family_methods.json`.

Without this, phase 2 is unverifiable. A value moved from a literal into a
catalogue column with a typo looks identical from outside.

## Phase 2 — the 17 code-derived values become catalogue columns

Only the ones a vintage profile must replace: the 10 DX curve NAMES, both COPs
of 4.0, the window-AC EER, the evaporative-cooler effectiveness, the two
minimum part-load ratios, the two fan pressure rises.

Each becomes a column with today's value as the default, read as
`resolved['...']`, validated where a bad value would otherwise fail late. **No
behaviour change** — every existing caller gets the same numbers, which the
phase-1 fixture proves.

Parameterise the curve NAME, not the coefficients: `curves.json` stays a
library of named curves and a profile names different ones.

## Phase 3 — leave the device physics alone, deliberately

The 6 defrost EIR curves and the 11 heat-recovery limits and time constants
describe how a machine behaves, not what a code requires. Recording the
decision matters more than the outcome: a later reader must be able to tell
"we judged this device physics" from "we never got to it".

## Phase 4 — disclose what was assumed

The values are applied today with NO audit entry, so a reader of the trail
cannot tell which performance came from the submitter and which from a builder
default. One `audit.info` per build naming the profile in force and the values
taken from it.

This is the same defect as AHJ-17 (#181, closed 2026-11-02): a value applied,
recorded nowhere, flagged to no one. The fix has the same shape — say what was
assumed. **A stock model carrying NECB reference DX curves is not a 1955
building, and nothing in the output currently says so.**

## Phase 5 — a decision, not work

Keep the NECB-derived values as the default and rely on phase 4's disclosure,
or make `performance` REQUIRED so the assumption cannot be inherited by
accident. The second breaks one caller (`reference.py:1517`) and is the safer
design. `seed_constructions` is the precedent for the first and the argument
for the second.

## Verification at each phase

- phase 1's fixture is the regression net for 2 and 3;
- `simulate_all_systems.py --check` must stay 108/108 with `severe: 0`;
- the frozen corpus must NOT move at all in phases 1-3: the same numbers
  through a different path. **If a baseline moves, a value changed** — that is
  the signal, not noise;
- phase 4 WILL move baselines, since it adds audit entries. Scoped re-freeze,
  all three lanes checked, `audit.json`/`audit.txt` only and never
  `report.json`.

## The recipe (#184), which phases 1-2 unblock

One file per building TYPE, a section per vintage, each naming a catalogue
system and listing that vintage's performance and envelope properties:

A complete, parsing sample is at
[`examples/stock_recipe_office.json`](examples/stock_recipe_office.json) — four
vintages for one building type, with the four `system` names verified against
`python/btap/modeling/hvac/data/systems.json`. Every NUMBER in it is a
placeholder: the library ships no vintage data, so the sample shows the shape
and nothing more.


`system` sits INSIDE the vintage block, because systems do change by vintage: a
1940 building may be hydronic radiators with no cooling, and the catalogue
already has `baseboards_only`, `baseboards` and `unit_heaters` among its 108.
Naming a catalogue entry rather than describing topology keeps the
`simulate_all_systems.py` gate meaningful — 108 of 108 size with `severe: 0`
today, and a recipe-built model inherits that. A system a recipe needs and the
catalogue lacks is a reason to add a catalogue entry.

Every value is concrete. No wildcards, no inheritance between vintage blocks,
nothing to resolve — so the AHJ-17 failure mode cannot recur here. `find_row`'s
"a missing key or 'Any' is a wildcard" is what produced that defect, and a
recipe has no lookup at all.

A key-parity check is worth having from the start: vintage blocks side by side
make the progression legible, and also invite copy-paste drift. A performance
key present in two vintages and missing from the third is invisible to a diff
review.

**Parity is PER SYSTEM, not per file** — a correction the sample forced. An
earlier draft of this plan proposed asserting that every vintage block carries
the same keys, and writing
[`examples/stock_recipe_office.json`](examples/stock_recipe_office.json) showed
that would REFUSE a correct recipe: its `pre-1960` block names
`Hot water unit heaters` and therefore has no `cooling_cop` and no DX curve
keys at all, because the building has no cooling. Padding it with
`cooling_cop: null` would be worse than omitting it — it implies a cooling
concept the system does not have.

So the check is: two vintage blocks naming the SAME catalogue system must carry
the same performance keys. Blocks naming different systems legitimately differ,
and the sample's four blocks fall into three groups (`Hot water unit heaters`,
the PSZ twice, `VAV chiller with gas boiler reheat`).

## `btap.stock`, a sixth subpackage

The recipe reader goes beside `btap.codes` — both consume `btap.modeling`,
neither imports the other:

    btap/stock/__init__.py   build_from_recipe(path) / build(spec)
    btap/stock/recipe.py     the loader and its validation, vintage-agnostic
                             (no data/ directory)

Not a module inside `btap.modeling`, because that package's value is having no
opinion, and `modeling/hvac` acquired those 37 values precisely because no
boundary told anyone not to. `btap.codes` is the shape precedent: a neutral
core plus a domain family, with `codes/pipeline.py` forbidden from importing
`codes/necb`.

`btap.stock` joins the D-77 layers list in `pyproject.toml` so import-linter
holds "stock may import modeling; modeling may NOT import stock". Packaging
needs no change — `include = ["btap*"]` already. CLAUDE.md's "one distribution,
five subpackages" becomes six, including the comment at the contract block.

**No `docs/decisions/` entry.** phylroy, 2026-11-02: the registry is the NECB
code-interpretation record whose audience is the Codes Committee and AHJs, and
`CODE_DECISIONS_BY_PROVISION.md` is the view by code, edition and provision. A
stock-modelling entry cites no provision, is `not_applicable` for every
edition, and lands there as counted-and-omitted noise. The enforceable parts
live in import-linter and `btap/stock/CLAUDE.md`, where an author adding
`stock/data/` will actually meet them.

## A correction the recipes will expose

The 28 existing models do NOT vary by vintage. Measured across all 8
multi-vintage building types, system object counts are identical — a pre-1960
Office carries the same 16 cooling objects as the 1980-2004 one:

| vintage | Office | Hangar | MaintenanceShop-Small | Training Building |
| --- | --- | --- | --- | --- |
| pre-1960 | 16 / 41 | 2 / 47 | 2 / 16 | 1 / 26 |
| 1960-1979 | 16 / 41 | 2 / 47 | 2 / 16 | — |
| 1980-2004 | 16 / 41 | 2 / 47 | 2 / 16 | 1 / 26 |

(cooling objects / hydronic-and-unit-heat objects)

A 1940s office with full DX cooling is a modelling convenience, not a 1940s
office. Vintage-accurate recipes will therefore produce models materially
different from the hand-built ones, and removing cooling from a pre-1960 office
changes its energy use substantially. **That is a CORRECTION to the existing
stock models, not merely automation of them** — and anyone comparing old and
new stock results will otherwise read the difference as a regression. It
belongs in the output, not only in a commit message.

## What the campus models need beyond this

26 of the 28 archetypes are buildable from the 108-system catalogue today.
The two `LargeDataCenter*` models use three object types no builder creates,
one instance each: `AirTerminal:SingleDuct:VAV:NoReheat`,
`Humidifier:Steam:Electric` and `HeatExchanger:FluidToFluid`. `crah.py`
already has `_add_humidity_control`, which sets a maximum-supply-humidity-ratio
schedule rather than placing a steam humidifier, so the concept is present and
the object is not. Worth its own issue if the data centres are in scope.

## Open

- **Location.** Nothing in the recipe shape holds a climate zone, and
  performance varies by location. Candidates: another nesting level under each
  vintage; a separate per-location override file; or leave it out on the
  grounds that what genuinely varies by climate is envelope conductance —
  NECB's own pattern via `climate.table_c1` — expressed as a zone -> conductance
  map inside the envelope block.
- **Phase 5's default.** Above.
