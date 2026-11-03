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

## The articulation surface, measured against an existing implementation

phylroy pointed at `canmet-energy/osruby`'s `measures/dnd_analysis` (private
repo; read through `gh`). Its measure class is literally
`ColdLakeVintageMaker`, and it is the thing that produced the `models/`
archetypes. Its architecture is the one this plan proposes, which is
reassuring:

    resources/*.osm        geometry per building type — barracks, office, hangar,
                           fire_hall, food_service, recreation_center,
                           storage_building, training_building, vehicle_garage,
                           maintenance_shop{,_small}
    cl_modelling_assumptions.{xlsx,csv}
                           one row per variant, keyed by `measure_id`, with
                           `building_type` and `vintage_name` columns
    apply_ecms(model, row) reflection: calls every `ecm_*` method it finds
    model naming           "<building_type>~<vintage_name>~baseline"

`measure.rb` itself is 73 lines of wrapper. The articulation lives in 20
`ecm_*` methods, each declaring a `measure_values` array of column names —
**113 declared columns in all**. The first sketch of the recipe in this plan
covered about four of the eighteen performance categories.

Mapped against what `btap.modeling` can do today, by probing for the SDK
classes and setters each category needs:

| category | cols | state |
| --- | --- | --- |
| `ecm_envelope` | 43 | **modeling** — `opaque_at_conductance`, `fenestration_at_conductance`, `seed_set` and `find_and_set_insulation_layer` are all present |
| `ecm_hotwater_boilers` | 10 | modeling builds `BoilerHotWater`; the efficiency setter is codes-side |
| `ecm_economizers` | 6 | modeling |
| `ecm_temp_setback` | 6 | modeling |
| `ecm_sat_reset` | 5 | modeling — and **no `codes` counterpart at all** |
| **`ecm_infiltration`** | **4** | **CODES ONLY** |
| `ecm_sizing` | 4 | modeling |
| **`ecm_lighting`** | **4** | **CODES ONLY** |
| **`ecm_plugs`** | **4** | **CODES ONLY** |
| `ecm_fans` / `ecm_pumps` / `ecm_dhw` / `ecm_erv` / `ecm_heating_cooling_setpoints` / `ecm_cold_deck_reset_control` | 3 each | modeling (`cold_deck_reset_control` also has no `codes` counterpart) |
| `ecm_cooling_cop` | 1 | modeling |
| **`ecm_dcv`** | **1** | **CODES ONLY** |
| `ecm_exhaust_fans` | 1 | modeling |
| `ecm_capital_costs` | 3 | out of scope — `btap.costing` |
| `ecm_id` | 3 | out of scope — bookkeeping |

**14 of the 18 performance categories already have their primitives in
`btap.modeling`**, which makes phase 2 parameterisation rather than
construction. `ecm_envelope`'s 43 columns — RSI and cost per m3 for every
surface class, with `solar_trans` and `vis_trans` on the glazed ones — are
already covered by four existing functions, so the envelope half stays the
easy half, just far wider than this plan's sample shows.

## Phase 0 — lift the four codes-only load primitives

`ecm_infiltration`, `ecm_lighting`, `ecm_plugs` and `ecm_dcv` exist ONLY in
`btap.codes.necb`:

    SpaceInfiltrationDesignFlowRate   codes/necb/loads/apply.py,
                                      codes/necb/envelope/reference.py
    LightsDefinition                  codes/necb/lighting/apply_lights.py,
                                      codes/necb/lighting/exterior.py
    ElectricEquipmentDefinition       codes/necb/loads/apply.py
    setDemandControlled               codes/necb/hvac/reference.py

So a stock model built through `modeling` alone **cannot set them at all**, and
for a 1940s building infiltration is arguably the dominant difference from a
2005 one. That makes this a prerequisite for the recipe, not a later
refinement: a recipe that cannot express infiltration is incomplete for the use
case that motivated it.

The lift is bounded, because the PRIMITIVE is separable from the NECB lookup.
`loads/apply.py:296` is

    def create():
        infiltration = openstudio.model.SpaceInfiltrationDesignFlowRate(
            space_type.model())
        infiltration.setName(f"{space_type.nameString()} Infiltration")
        infiltration.setSpaceType(space_type)
        return infiltration

— object construction and attachment, with the NECB part being only where the
VALUE comes from. `loads/apply.py` is 468 lines with 27 NECB-coupled
references and `lighting/apply_lights.py` is 443 with 40, so the primitives are
a minority of each file.

Phase 0 extracts "apply an infiltration rate / lighting fractions / a plug-load
density to a space type" into `btap.modeling`, leaving the NECB value lookup in
`codes`, which then calls down into the primitive. That direction is what D-77
already allows: `codes` imports `modeling`, never the reverse.

**Verification:** the NECB appliers must produce byte-identical output — this
is a move, not a change — so the frozen corpus must not move at all, in any of
the three lanes. The 108-system sizing sweep must stay 108/108 with
`severe: 0`.

## Phase 0b — the three ECM clusters a retrofit set needs

Numbered 0b rather than renumbering 1-5, because "phase 0" is referenced by
merged commits (#187, #191) and by the verification section below.

phylroy pointed at `canmet-energy/campus`'s 22 measures
(`src/resources/buildings/measures`) and asked whether phase 0 covers their
articulation. It does not, and the gap is NOT phase 0's — it is this plan's.
Phases 1-5 do not reach it either: phase 1 is an inventory test, phase 2 turns
code-derived values into catalogue columns, phase 3 deliberately leaves device
physics alone, phase 4 is disclosure and phase 5 a decision.

Those measures are PYTHON OpenStudio measures, so they are not a parallel
lineage to translate — they are callers these primitives could serve directly.

### What `btap.modeling` articulates today: 9 of 22

| measure | where |
|---|---|
| `change_ext_wall_r_value` | `envelope/constructions.py` `opaque_at_conductance` |
| `window_retrofit` | `envelope/constructions.py` `fenestration_at_conductance` |
| `add_ashp_with_backup` | `hvac/systems/ashp_baseboard.py` |
| `add_doas_erv` | `hvac/systems/doas.py`, `zone_ervs.py` |
| `reduce_lighting_load_by_percentage` | `loads` `scale_lighting` |
| `reduce_infiltration_by_percentage` | `loads` `scale_infiltration` |
| `demand_controlled_ventilation` | `hvac/ventilation.py` |
| `led_lighting` | `loads` `set_lighting` (the LED VALUE is a data question) |
| `shift_hours_of_operation` | `hvac/components/schedules.py`, PARTIAL — it creates rulesets; shifting an existing one is a different act |

### The three clusters that are absent

**Equipment efficiency (3 measures).** `improve_motor_efficiency`,
`improve_fan_and_pump_total_efficiency`,
`fan_and_pump_motor_efficiency_upgrade`. Zero hits for
`setMotorEfficiency` or `setFanTotalEfficiency` anywhere in `btap.modeling`.

This is NOT what phase 3 excludes. Phase 3 leaves the 6 defrost EIR curves and
11 heat-recovery limits alone because they describe how a machine behaves;
a motor efficiency is a NAMEPLATE RATING that a retrofit changes and a vintage
determines, and a 1955 fan motor against a 2015 premium-efficiency one is
exactly the kind of difference this plan exists to express.

**Controls (6 measures).** `add_daylight_sensors`,
`daylight_and_occupancy_controls`, `adjust_thermostat_deadband`,
`unoccupied_temp_setback`, `economizer_control`,
`windowed_setpoint_and_load_override`. No setpoint setter exists in
`btap.modeling` at all — zero hits for
`setHeatingSetpointTemperatureSchedule` or its cooling counterpart.

**Service water (2 measures).** `install_low_flow_fixtures`,
`upgrade_dhw_plant`. `hvac/classify.py:299` reads `to_WaterHeaterMixed()` for
FUEL CLASSIFICATION only; nothing constructs or upgrades one.

`add_reporting_outputs` is a fourth, smaller gap: one system
(`hp_plant_fancoils.py:238`) creates an `OutputVariable` for its own
debugging, and there is no general facility. `shared_resources` is a helper
library, not a capability.

### Three greps that had to be discarded, and why that matters

Counting matches would have inflated the supported column, and each of these
looked like a hit:

- **thermostat deadband** matched `hvac/catalog_report.py:290`, which
  constructs a BARE `ThermostatSetpointDualSetpoint` for the catalogue's
  sizing probe. No setpoints and no deadband.
- **economizer** matched `hvac/systems/doas.py:60` —
  `setEconomizerControlType('NoEconomizer')`, hardcoded OFF. The opposite of
  the capability.
- **DHW plant** matched a classifier read, as above.

A name appearing in the package is not the capability; the file had to be
opened in each case. That is the same discipline the coverage manifest
enforces — a code pointer means implemented, and a pointer into a report does
not.

### Why this matters for the recipe

A stock generator missing these can build a 1940s building's ENVELOPE and not
its OPERATION. Equipment efficiency and controls are most of a retrofit
measure set's vocabulary, and for pre-1980 vintages the operating assumptions
— no setback, no economizer, no daylight control, a standard-efficiency motor
— are as characteristic as the wall assembly. A recipe that cannot say "this
vintage had no night setback" cannot describe the building.

### Verification for this phase

Each lift is a MOVE where it has an existing caller and an ADDITION where it
does not, and the two have different evidence:

- a lift with an NECB caller must leave the frozen corpus byte-identical in
  all three lanes, as phase 0's did;
- an addition has no caller to hold identical, so it carries unit tests that
  FAIL against its absence, and the plan should not claim corpus evidence for
  it. Phase 0 learned this twice: `lighting_per_person` and
  `additional_lighting_per_area` are 0 in all 308 rows of both editions, so
  the corpus cannot witness either branch, and the `sorted()` ->
  `sorted_by_name` determinism fix moved no baseline because no corpus model
  carries two load instances on one space type.

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

- phase 0 is a MOVE, not a change: the NECB appliers must produce
  byte-identical output, so the frozen corpus must not move in any lane;
- phase 1's fixture is the regression net for 2 and 3;
- `simulate_all_systems.py --check` must stay 108/108 with `severe: 0`;
- the frozen corpus must NOT move at all in phases 1-3: the same numbers
  through a different path. **If a baseline moves, a value changed** — that is
  the signal, not noise;
- phase 4 WILL move baselines, since it adds audit entries. Scoped re-freeze,
  all three lanes checked, `audit.json`/`audit.txt` only and never
  `report.json`.

## The recipe (#184), which phases 0-2 unblock

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
