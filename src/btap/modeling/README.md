# btap.modeling

Model AUTHORING — the generic, NECB-free half of the family (and the
intended MCP tool surface). SDK-only, shared AuditLog schema, never
simulates. Four engines: the footprint wizards and the bar engine (verbatim
ports from openstudio-standards), a 3D viewer (ported from
canmet-energy/campus) and a per-storey 2D floor-plan renderer — plus, since
the by-nature refactor (D-77), the **HVAC authoring machinery**: the
124-system topology catalog, `build_system` / `replace_system`, the system
builders, coil/curve/schedule components, `classify.characterize`,
teardown, and the envelope authoring pieces (constructions, the
exposed-surface census).

## Layout

```
btap/modeling/
  geometry/   wizards, bar engine, footprints, plans, 3D render
  hvac/       124-system catalog + builders (systems/, components/, data/)
  envelope/   constructions + surface census
```

No `lighting/` or `shw/`: their authoring is NECB-table application and
lives in `btap.codes` — see [CLAUDE.md](CLAUDE.md).

## HVAC performance profiles

`build_system(..., performance_profile={...})` separates topology selection
from equipment performance. The argument is a partial mapping merged over the
current 17-value builder profile; omitting it reproduces the previous builder
output exactly. It does not resolve a building vintage or load external data:
stock and retrofit callers supply concrete values.

```python
modeling.build_system(
    model,
    'Window AC with baseboard electric',
    zones,
    performance_profile={'window_ac_eer_btu_per_w_h': 7.5},
)
```

The profile covers the ten single- and multispeed DX curve names, VRF heating
and cooling COPs, window-AC EER, direct-evaporative-cooler effectiveness,
heating and cooling plant-heat-pump minimum part-load ratios, and the 640 Pa
PTAC fan pressure inherited from the NECB reference builder. Curve values name
entries in `hvac/data/curves.json`; invalid names, curve types, fractions,
ratings, and unknown keys fail before HVAC teardown or construction.

Defrost EIR curves and VRF heat-recovery startup dynamics remain equipment
behavior, not profile ratings. The unit-heater fan's 0.2 inH2O pressure is
also outside the profile: it is a generic prototype convention rather than a
code/reference target, and stock recipes can retarget fan pressure through
the code-neutral efficiency primitive after construction.

## Finding a system

The HVAC catalogue's 124 systems are organised the way a mechanical engineer
browses them: **category, then system type, then variants**. Variants within a
type differ by *facets*: what the air handler heats and cools with, the zone
terminals, the hot- and chilled-water plant, outdoor air, heat recovery, and
whether one unit serves one zone or several
([plan](../../../docs/plans/HVAC_TAXONOMY_PLAN.md)).

| Category | System types |
|---|---|
| Central ducted systems | packaged single-zone rooftop unit (PSZ-AC / PSZ-HP), packaged VAV and VAV with reheat, dual-duct VAV, CAV reheat, forced-air gas furnace, H&V unit, split AC, direct evaporative cooler |
| Zone terminals + outdoor-air unit | named terminal first: chilled beams, fan coils (two- or four-pipe) with a DOAS or a central air handler, packaged terminal and water-loop heat pumps, PTACs with a DOAS or a make-up air unit, VRF heat recovery |
| Zone equipment only | PTAC, PTHP, window AC, VRF heat recovery, water-loop heat pumps |
| Heating only / Ventilation only / Process | baseboards, unit heaters / DOAS, zone ERVs / computer-room air handler |

Every system has three names:

- an **id**, such as `psz-gas-hwbb-gasboiler`: short, file-safe, stable. It is
  what `build_system` writes into the model (`psz-gas-hwbb-gasboiler | Thermal
  Zone 1`) and what code should use;
- a **display name** people read: "Packaged single-zone rooftop unit (PSZ-AC):
  gas heat, DX cooling, hot water baseboards, serves several zones from one
  control zone - gas boiler". In the zone-terminal category the air-handler
  phrases carry their unit, as in "DOAS (electric heat; DX cooling)", so they
  cannot be read as the terminals' own;
- its **legacy name** from before the taxonomy, such as "PSZ RTU Gas and DX
  Coils and Hot Water Baseboard". It is still accepted wherever a system is
  named, so older scripts and models keep working.

```python
from btap import modeling

modeling.systems(system_type="psz", ahu_heating="gas")    # facet filters
modeling.systems(terminal="fc4", hw_plant="awhp")         # fan coils on a heat-pump plant
modeling.systems("rooftop shared")                        # words, any order
modeling.system_taxonomy()["facets"]                      # every facet and value
```

`modeling.catalog_html("catalog.html")` writes the browsable page: search,
facet filters with live counts, the tree, and each system's loop diagrams and
`build_system` line. `btap.codes.necb.hvac.catalog_annotations.catalog_html(
"catalog.html", code="necb2020")` adds which NECB reference System uses each
row; the modeling layer itself shows only a row's NECB *lineage*.

## Building a model's HVAC

The catalogue is browsed as central systems, zone terminals with an
outdoor-air unit, and zone equipment, but **each row is a whole system**:
`psz-gas-hwbb-gasboiler` is the rooftop unit, its hot-water baseboards and
the gas boiler, and `doas-fc4-elec-gasboiler-scrollchiller` is a DOAS, four-pipe
fan coils and both plants. So the normal pattern is one row per group of zones,
not a central row stacked on a zonal one.

1. **Prepare the model.** Every zone the system will serve needs a
   thermostat; `build_system` refuses a zone without one. If the model will go
   through an NECB compliance run, its spaces also need standards space types.
2. **Group the zones** that share a system: by use, schedule or floor, or
   one per zone. A group is a list of `ThermalZone` objects.
3. **Pick a row for each group**, on the catalogue page or from Python
   (see Finding a system above).
4. **Build each group:**

   ```python
   from btap import modeling

   zones = sorted(model.getThermalZones(), key=lambda z: z.nameString())
   offices, corridor = zones[:4], zones[4:]

   modeling.build_system(model, "vav-hw-hwbb-gasboiler-scrollchiller", offices)
   modeling.build_system(model, "bb-elecbb", corridor)
   ```

   - **Plants are shared.** A second group needing a gas hot-water plant
     joins the first one's loop. Plants of a different kind never share:
     heat pump or boiler, backup fuel, controls.
   - **Options go in `config=`:**
     - `{"hw_source": "awhp"}` for a heat-pump hot-water plant on any
       hydronic row;
     - `{"boiler_fuel": "Electricity"}`;
     - `{"hw_controls": {...}}` for the loop reset and the backup deadband;
     - `{"per_zone": True}` for one packaged unit per zone;
     - `{"all_outdoor_air": True}` on a rooftop unit or H&V unit to run it on
       100% outdoor air (the controller's outdoor-air fraction is fixed at 1,
       not merely sized for it).

     An unknown or contradictory option is refused before anything is
     built.
   - **A single-zone row given several zones builds one unit** that follows
     one control zone. Pass `control_zone=` to choose it, or leave it to step
     5. Without either, the build warns.
   - **`modeling.replace_system(...)` swaps a group's system.** It is
     `build_system(..., remove_existing=True)`: only those zones' HVAC is torn
     down, and a refused rebuild leaves the old system in place.
5. **Size, then settle the control zones:**

   ```python
   from btap import simulation

   simulation.run(model, run_dir="runs/size", weather=weather, sizing_only=True)
   modeling.elect_control_zones(model)   # each shared unit follows its largest heating load
   ```

6. **Check what you built.**
   - `modeling.characterize(model)` gives the facts per zone group: fuels,
     terminals, plants and heat pumps.
   - `modeling.model_hvac_diagrams(model)` draws the loops.
   - An annual run reports unmet hours. NECB 2020 Article 8.4.1.2.(3) allows
     100 h of unmet heating per thermal block.
   - The full NECB determination runs on the same model object, with no file
     to save first:

     ```python
     from btap import codes

     result = codes.performance_compliance(model, code="necb2020",
                                           weather=weather, run_dir="runs/necb")
     result.compliant                              # True / False; None if no determination
     result.report["compliance_determination"]     # "code", "conditional" (needs an AHJ's
                                                   # approval) or "no_determination"
     ```

     The command-line equivalent is `btap-compliance model.osm --code necb2020
     --epw ...`. It runs the same pipeline from a saved file and reports the
     outcome as an exit code: 0 compliant, 1 not compliant, 3 preflight refusal,
     4 simulation failure, 6 no determination.

**For an existing model**, `btap.stock` reads its HVAC into a recipe and
ranks catalogue rows for each unidentified zone group. Each candidate lists the
facts that matched and those that did not. A candidate is only a guess:
building one is opt-in (`build_from_recipe(..., accept_candidates=True)`) and
is audited as a guess.

**Limits:**

- **Stacking two rows on the same zones is not validated.** It means calling
  `build_system` twice without `remove_existing`. The one case refused is a
  zone ERV on a system that already ventilates centrally. Prefer a row that
  already combines what you need; the composites (DOAS + fan coils, DOAS + VRF,
  DOAS + water-loop heat pumps) exist for that.
- **One build serves its zones uniformly**, so different equipment on
  different zones of one central system needs separate builds.

## Heat-pump hot water for any hydronic system

Any system with a hot-water plant (baseboards, VAV reheat, fan coils with a
central air handler, hot-water rooftop coils, unit heaters) can take an
air-to-water heat-pump plant instead of boilers, with one backup boiler in
series downstream of the heat pump.

Thirteen named catalogue entries use it (2026-11-27):

- hot water baseboards: `bb-hwbb-awhp-gasbu`, `bb-hwbb-awhp-elecbu`, and the
  retrofit `bb-hwbb-awhp-gasbu-lift` and `bb-hwbb-awhp-elecbu-lift`;
- VAV with reheat: `vav-hw-hwbb-awhp-gasbu-scrollchiller` and
  `vav-hw-hwbb-awhp-elecbu-scrollchiller`;
- packaged VAV: `pvav-hw-hwbb-awhp-gasbu` and `pvav-hw-hwbb-awhp-elecbu`;
- four-pipe fan coils with a make-up air unit (the NECB System 2 shape):
  `mau-fc4-gas-awhp-gasbu-scrollchiller`, and the all-electric
  `mau-fc4-elec-awhp-elecbu-scrollchiller`, whose make-up air unit heats
  electrically too;
- hot-water rooftop unit with hot water baseboards: `psz-hw-hwbb-awhp-gasbu`;
- hot water unit heaters: `uh-hw-awhp-gasbu` and `uh-hw-awhp-elecbu`.

`gasbu` and `elecbu` mark the boiler as a backup. Any other hydronic row takes
the same plant as an option:

```python
modeling.build_system(model, "bb-hwbb-gasboiler", zones,
                      config={"hw_source": "awhp"})                    # gas backup
modeling.build_system(model, "bb-hwbb-gasboiler", zones,
                      config={"hw_source": "awhp", "boiler_fuel": "Electricity"})
modeling.build_system(model, "vav-hw-hwbb-gasboiler-scrollchiller", zones,
                      config={"hw_source": "awhp", "hw_supply": "boiler_lift"})
```

`hw_supply` chooses how the load is met:

- **`low_temperature`** (the default, the new-design norm): the loop runs at
  60 C (outdoor reset down to 45 C at 0 C), terminals autosize for that water,
  and the boiler backs up to the same setpoint, firing only when the heat pump
  is at capacity or below its -15 C cutoff;
- **`boiler_lift`** (the retrofit arrangement): the loop keeps the
  conventional 82 C reset for terminals sized for it; the heat pump preheats to
  its 60 C limit and the boiler lifts the rest.

The heat pump is the ECM hs15 air-to-water equipment (COP 3, the CAWHP-HS15
curves), sized on the heating load. The backup boiler is setpoint-controlled
on its own outlet, 1 K below the heat pump: load-dispatched in series it was
handed almost nothing and the loop ran under setpoint, and at the SAME setpoint
it chased the fraction of a kelvin the heat pump runs short while defrosting.
Measured annually on the five-zone fixture (2026-11-27), hot water baseboards:

| Plant | Heat pump share | Heat-pump COP | Site gas | Occupied unmet heating |
| --- | ---: | ---: | ---: | ---: |
| Gas boilers only | 0% | - | 147 GJ | 56.5 h |
| Heat pump, low temperature, gas backup | 92% | 2.47 | 8.8 GJ | 59 h |
| Heat pump, boiler lift, gas backup | 39% | 2.39 | 89 GJ | 56.75 h |

VAV with reheat on a low-temperature heat-pump plant: 94% heat-pump share,
70.25 h. The same fixture, measured for the second set of entries:

| Entry | Heat pump share | Occupied unmet heating | Boiler twin |
| --- | ---: | ---: | ---: |
| Four-pipe fan coils + MAU, gas backup | 93.5% | 80.5 h | 150 h |
| Four-pipe fan coils + MAU, electric | 93.5% | 80.5 h | - |
| Hot-water rooftop unit + baseboards, gas backup | 94% | 687.75 h | 687 h |
| Baseboards, boiler lift, electric backup | 39% | 56.75 h | 56.5 h |

The rooftop unit's unmet hours are its shared topology (one control zone for
five), the same with boilers. On the default 60 to 45 C reset the fan coils had 239.25 h unmet: at 45 C
there was too little coil capacity to recover from night setback. Their two
rows therefore set `hw_controls: {"loop_reset_c": [60, 55]}` (phylroy,
2026-11-27). The measured trade-off, gas backup:

| Fan-coil loop reset | Occupied unmet heating | Heat-pump COP | Site electricity |
| --- | ---: | ---: | ---: |
| 60 to 45 C (the plant default) | 239.25 h | 2.77 | 478 GJ |
| 60 to 50 C | 111.25 h | 2.66 | 490 GJ |
| 60 to 55 C (these rows) | 80.5 h | 2.54 | 500 GJ |
| 60 C flat | 78.5 h | 2.45 | 507 GJ |

NECB 2020 Article 8.4.1.2.(3) allows 100 h of unmet heating per thermal block
in a compliance run; these are whole-building occupied hours on a test fixture
whose boiler twin has 150 h. The make-up air unit's coil recorded no heating in
either variant. None of these runs had a Severe error. A composite passes the options
to its hot-water parts; a row with no hot-water plant refuses them. A heat-pump plant is never shared with an
ordinary boiler system, and plants of different `hw_supply` or backup fuel are
never shared with each other. The setpoint schedules are authored defaults,
not code values; the NECB reference building is unaffected and keeps boilers.

`hw_controls` overrides those defaults. Every key is optional:

```python
modeling.build_system(model, "bb-hwbb-gasboiler", zones, config={
    "hw_source": "awhp",
    "hw_controls": {
        "loop_reset_c": [55, 40],       # loop supply at [cold, mild] outdoor
        "outdoor_reset_c": [-20, 5],    # the outdoor temperatures of that reset
        "heat_pump_max_c": 60,          # the heat pump's outlet ceiling
        "backup_deadband_k": 1.0,       # boiler setpoint below the loop's
    }})
```

Defaults: the loop resets over -16 to 0 C outdoor, from 60 to 45 C (low
temperature) or 82 to 60 C (boiler lift). The heat pump's outlet ceiling is
60 C, and the boiler deadband is 1 K.

- The boiler holds the deadband below the loop wherever the heat pump alone can
  meet the loop setpoint, and holds the loop setpoint itself wherever it cannot.
  On boiler lift the boiler follows the loop's own reset and carries on past the
  mild end until it is one deadband below the heat pump.
- The first boiler-lift version moved only the boiler's mild endpoint. Between
  the endpoints neither machine then met the loop: 0.96 K short at the default.
  The boiler-lift row above was 42% heat pump, 83 GJ, before that was fixed;
  some of that heat-pump share was really the loop running under setpoint.
- These are refused:
  - a low-temperature reset hotter than the heat pump's ceiling, because that
    loop is boiler lift;
  - a boiler-lift reset the heat pump can reach, because the boiler would lift
    nothing;
  - a boiler-lift reset that falls below the heat pump's constant setpoint;
  - a deadband on a boiler-lift loop the heat pump never meets, because it
    would do nothing;
  - a loop whose design return would fall below 20 C (a 35 C low-temperature
    supply is accepted);
  - a boiler-lift reset so shallow that the boiler would need more than 5 C of
    outdoor temperature past the mild end to fall its deadband below the heat
    pump.
- Plants with different controls are never shared. A key that changes nothing
  built, such as the ceiling on a low-temperature loop, does not split them.

There is no sizing factor, deliberately. EnergyPlus scales the heat pump's
water flow with it, and the heat pump sits in series on the loop's only supply
branch, so a smaller heat pump starves the loop. Measured on the boiler-lift
baseboard plant:

| Sizing factor | Load-side flow | Occupied unmet heating |
| ---: | ---: | ---: |
| 1.0 | 0.8 L/s | 57 h |
| 0.4 | 0.3 L/s | 135 h |
| 0.25 | - | 260 h |

Is the autosized heat pump too big? The hourly part-load ratio measures
delivered heat against what the heat pump can deliver at that hour's outdoor
temperature, so it answers that. Its peak output in kW does not: the
capacity curve derates the rated capacity in cold weather. Measured
annually (2026-11-27):

| Outdoor | Low temperature: hours at >= 95% | Low temperature: max | Boiler lift: max |
| --- | ---: | ---: | ---: |
| -15 to -10 C | 9 | 1.00 | 0.03 |
| -10 to -5 C | 13 | 0.99 | 0.29 |
| -5 to 0 C | 0 | 0.91 | 0.67 |
| 0 to 5 C | 0 | 0.74 | 0.74 |

- **Low temperature: not oversized.** Just above its cutoff the heat pump runs
  at its full derated capacity and the boiler tops up. A smaller heat pump
  would hand that heat to the boiler.
- **Boiler lift: larger than it needs to be.** In cold weather the return
  water is already above the heat pump's 60 C, so it barely runs. It never
  exceeds 74% of its available capacity. That affects installed size, and so
  costing, but hardly any energy. Fixing it would need a two-pass sizing run,
  because a sizing factor starves the loop. It is left as it is (#244, closed
  by phylroy as costing-only).

## Modern HVAC systems

Five opt-in catalog rows add modern hydronic and air-system topology without
changing the existing rows:

- active and passive chilled beams use a dehumidifying/reheating 100% OA DOAS,
  electric baseboards, and 15/18 C tempered chilled water;
- rotary ERV VAV and sensible-only plate HRV PVAV variants use a central
  air-to-air exchanger, pretreat setpoint control, explicit frost/bypass
  inputs, current-SDK effectiveness curves, and gas-boiler hydronic perimeter
  trim; and
- true dual-duct VAV uses independent 35 C hot and 13 C cold decks with one
  `AirTerminalDualDuctVAV` per zone.

The chilled-beam rows reset chilled-water setpoints to the warmest served-zone
dew point plus a 2 K margin. Each zone dew point is evaluated once into an EMS
variable before comparison; inline `@TdpFnWPb` evaluation in an Erl `IF`
produced 2265 psychrometric failures per annual run in EnergyPlus 25.2. Plant
loops are reused only when their source and full temperature profile match.
Existing VRF and DOAS+VRF systems already enable heat recovery; that behavior
is tested rather than exposed as a duplicate row.

All five rows must complete the standard five-zone annual simulation cleanly,
consume both heating and cooling energy, and remain at or below 100 occupied
unmet hours in each mode. This common gate was introduced after completed runs
left both beam rows at 411-420 cooling unmet hours and both recovery rows at
468.5 heating unmet hours. The accepted annual results are:

| System | Heating h | Cooling h |
| --- | ---: | ---: |
| Active chilled beam | 49.00 | 76.25 |
| Passive chilled beam | 49.00 | 89.00 |
| Rotary ERV VAV | 70.00 | 0.75 |
| Plate HRV PVAV | 70.00 | 0.75 |
| Dual-duct VAV | 54.00 | 0.00 |

The chilled-beam sizing block retains an explicitly empirical 2.2 cooling
reserve: 2.0 produced 116.0 occupied cooling unmet hours for the passive row,
while 2.2 produced 89.0. This is fixture-tested catalog sizing, not a code
requirement or a general design rule. Likewise, the legacy non-recovery VAV
comparator records 468.75 heating unmet hours while the recovery rows include
new perimeter baseboards. The rows prove that their heat exchangers operate
and that their complete topologies condition this fixture; they are not an
isolated A/B proof that heat recovery caused the comfort result.

A hydronic-radiant candidate was retired rather than shipped under a misleading
name. On the same annual fixture, its PTAC DX coils delivered 18,680 kWh versus
3,955 kWh from the slab, and removing the PTACs left 2,315.5 occupied cooling
unmet hours. The slab injected about 313 MWh of heat while roughly 271 MWh left
through the preserved 3.401 W/(m2 K) uninsulated ground slab, producing
555.6 kWh/m2 heating intensity versus 91-156 kWh/m2 for the five accepted
rows. Inserting insulation would silently change the envelope rather than fix
the HVAC topology, so the catalog row, builder family, and its one-value trim
option were removed.

The unrelated pre-existing NECB System 2/5 water-coil sizing failure discovered
by the reference-generation gate is tracked in
[#113](https://github.com/canmet-energy/btap/issues/113); no code-driven sizing
workaround is part of this modeling feature.

UFAD is not a catalog option. OpenStudio 3.11 can author the required
EnergyPlus room-air objects in a translated workspace, but has no typed,
persistent OpenStudio Model (`.osm`) representation. Post-translation
injection would also be bypassed by ordinary external translation and the
remote OpenStudio-model workflow, so shipping a UFAD name would overstate
portable model behavior.

## Footprint wizards

`create_shape_*` ported whole (rectangle, aspect-ratio with rotation,
courtyard, H, L, T, U): perimeter/core zoning per storey, matched surfaces.
Rectangle supports below-grade storeys with Ground boundary conditions; the
other shapes do not (the aspect-ratio wrapper delegates to rectangle but
fixes below-grade storeys at 0).

```python
import btap.modeling as modeling

model = modeling.create(shape='rectangle', length=40.0, width=25.0,
                        storeys=3, below_grade_storeys=1,
                        perimeter_zone_depth=4.0, audit=audit)
modeling.create(shape='l', length=40.0, width=40.0, storeys=2)
```

`storeys` / `below_grade_storeys` are the canonical spellings across the
facade; the engines' own names (`above_ground_storys`, `under_ground_storys`,
`num_floors`, `num_stories_above_grade`, `num_stories_below_grade`) remain
accepted, but passing a canonical name and its engine name together raises.
Unknown parameters raise — typos never silently fall to defaults.

## Measured footprints

`create_from_footprint(geojson=…, height_m=…, …)` takes a real outline (a
GeoJSON ring from a building-stock service, survey or GIS export) plus a
measured height and returns zoned storeys. It is deliberately a PEER of
`create`, not a member of the shape table: `create` dispatches positional
scalars, and a coordinate ring is not that shape. It stays SDK-only and
offline — fetching records, choosing a storey height and class→space-type
mapping are the caller's job. See [CLAUDE.md](CLAUDE.md) for the zoning
thresholds, which were measured rather than chosen.

## The bar engine (Goldwasser lineage)

`create_bar` + `bar_hash_setup_run` and their five polygon/space helpers,
ported verbatim. The DOE/DEER building-type-ratio wrappers are deliberately
NOT ported (they depend on CreateTypical metadata); instead the family-native
entry assigns **NECB space types by ratio in one step**, so geometry arrives
already standards-tagged for the loads pass:

```python
model = modeling.bar(
    space_type_ratios={('Space Function', 'Office enclosed > 25 m2'): 0.7,
                       ('Space Function', 'Corridor/Transition area other-sch-A'): 0.3},
    length=50.0, width=20.0, storeys=3, wwr=0.4,
    party_wall_stories_north=2, below_grade_storeys=1)
```

Slicing is ratio-true (verified to 1%), WWR is honoured per facade,
party-wall storeys go adiabatic, below-grade surfaces go Ground.

## The 3D viewer (campus port)

`render(model_or_path, path=…, height=…)` — the SDK `GltfForwardTranslator`
produces glTF, embedded as a base64 data URI in a Google `<model-viewer>`
page. Every export runs in a child process (`render_worker.py`) because the
C++ translator can SEGFAULT on un-triangulatable surfaces; the fallback
ladder then retries — full model → sub-surfaces removed (massing shell) →
binary-search removal of crashing base surfaces. Unrenderable models return
`''`, audited, never raising.

Trade-off carried from campus: the `<model-viewer>` SCRIPT loads from a CDN
at view time; the geometry itself is fully embedded. A CSP that blocks
external hosts will not run this viewer.

## Floor plans (per-storey 2D)

`floor_plans(model_or_path, path=…, png_dir=…, audit=…)` — the 2D
counterpart, for the everyday question *"what are the spaces and zones in
this model called?"*. One inline-SVG plan per storey: space footprints in
**world coordinates** (`space.transformation * surface.vertices`, so rotated
buildings draw rotated), filled by thermal zone from a deterministic palette,
labelled with space and zone name at the centroid, every polygon carrying a
`space | zone | space type | area` hover tooltip — plus a shared zone legend
and a metric scale bar.

```python
bundle = modeling.floor_plans(model, path='floor_plans.html')
[s['name'] for s in bundle['storeys']]   # ['Story 0', 'Story 1', 'Story 2']
bundle['storeys'][0]['svg']              # inline <svg>, embeddable anywhere
bundle['legend_svg']                     # the shared thermal-zone legend
```

The returned bundle — `{storeys: [{name, svg}], legend_svg, empty,
inferred_storeys, error}` — is the same never-raises shape the catalog
report's `model_diagrams` returns, so a host report (the NECB AHJ compliance
report) can embed the plans and degrade to a one-line note on an empty or
unreadable model.

The standalone page is **fully self-contained** — inline CSS and SVG, native
`<details>`, no scripts and no external references (one `break-inside: avoid`
section per storey, so printing gives a plan per page). Unlike the 3D viewer,
it renders under a strict CSP.

`png_dir` additionally rasterizes one PNG per storey if a system converter is
installed (`rsvg-convert` → `cairosvg` → `magick`); when none is, the audit
gets a loud warning and no PNG is written — PNGs are never a required output.

Storeys come from `BuildingStory` objects ordered by minimum world z. A model
without them falls back to binning floor elevations at ±0.01 m into
synthesized levels, flagged `inferred_storeys` plus an audit warning. Spaces
with no floor surface are warned and skipped; a space with floors at several
elevations is cut at the lowest one.

## Composing with the family

Bar and wizard output carries **no constructions** — downstream envelope work
retargets existing ones, so seed a basic construction set (or start from an
OSM that has one) before any envelope pass. With that, the full authoring
chain is in-package:

geometry → `btap.codes.necb.loads` → `btap.codes.necb.lighting` → `btap.codes.necb.shw` →
`modeling.build_system` → `btap.codes.necb.envelope` prescriptive →
`btap.codes.performance_compliance` (proposed + reference + costing, one
audit) — pinned by the full-family composition test in `tests/modeling/`.

## From nothing to a simulation

A complete building from library calls alone — geometry, constructions, NECB
loads, lighting and hot water, HVAC — then a one-week simulation. This block is
EXECUTED by `tests/modeling/test_from_nothing_example.py`, so it is kept
working, not just kept.

```python
from btap import modeling, simulation
from btap.audit import AuditLog
from btap.codes.necb import lighting, loads, shw

epw = "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw"   # your weather file
ddy = "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy"   # and its design days
audit = AuditLog()                                    # one trail for every step

# 1. A two-storey 40 m x 20 m office bar, NECB space types assigned by ratio.
model = modeling.bar(
    space_type_ratios={("Space Function", "Office enclosed > 25 m2"): 0.75,
                       ("Space Function", "Corridor/Transition area other-sch-A"): 0.25},
    length=40.0, width=20.0, storeys=2, wwr=0.35, audit=audit)

# 2. Constructions: bar output has none. This seed is deliberately poor and
#    NOT a real assembly — replace it before trusting the energy numbers.
modeling.seed_constructions(model, audit=audit)

# 3. NECB loads (people, equipment, infiltration, thermostats), lighting and
#    service hot water, from the tagged space types.
loads.apply_loads(model, code="necb2020", audit=audit)
lighting.apply_lights(model, code="necb2020", audit=audit)
shw.apply_shw(model, code="necb2020", fuel="NaturalGas", audit=audit)

# 4. HVAC: a multi-zone VAV system serves every zone from one air handler.
modeling.build_system(
    model, "MZ BU RTU Electric Heating Coil Scroll Chiller and Hot Water Baseboard",
    list(model.getThermalZones()), audit=audit)

# 5. Simulate one January week.
result = simulation.run(
    model, run_dir="my_first_run", weather={"epw": epw, "ddy": ddy},
    run_period={"begin_month": 1, "begin_day": 8, "end_month": 1, "end_day": 14})

print(result.clean)                          # True: no Severe or Fatal errors
print(result.energy["total_site_kwh"])       # about 10,200 kWh for the week
print(result.unmet_hours)                    # {'heating': ..., 'cooling': ...}
```

Two things worth knowing before choosing a different system:

- **A packaged single-zone unit follows ONE zone.** Most "PSZ RTU ..."
  rows build ONE unit over every zone they are given, as a house's furnace
  serves every floor from one thermostat. The zone it follows decides which
  zones go unmet, so choose it, or let a sizing run choose it:

  ```python
  modeling.build_system(model, name, zones, control_zone=main_floor)  # yours

  modeling.build_system(model, name, zones)        # zones[0], provisionally
  simulation.run(model, run_dir="runs/size", weather=weather, sizing_only=True)
  modeling.elect_control_zones(model)  # -> the largest design heating load
  ```

  `control_zone="cooling"` asks for the largest design cooling load instead.
  No choice of zone, fixed or switched by season, makes one thermostat serve
  zones whose loads differ: the zone holding it is met and the others are
  not. Where they differ, build one unit per zone.

  For one unit per zone instead, pass `config={'per_zone': True}` or call
  `build_system` once per zone. `build_system` warns about a shared unit on a
  provisional zone (#236). Electing is yours to do: a compliance run never
  changes a proposed's control zone, and `--hvac-system` builds a shared-by-
  default row one unit per thermal block (D-101). Following the zone
  with the most heating leaves the others over-heated rather than starved,
  but with one thermostat the cooling-dominated zones can then go unmet.
- **A baseboard plus a single-zone air loop in the same zone can report
  `CheckWarmupConvergence` Severe errors** on larger buildings: a
  day-to-day heating-load wobble of tenths of a watt, against EnergyPlus's
  absolute 0.04 W tolerance, as the two share the zone's heating. Results are
  still produced and the NECB reference is unaffected; the system above, and
  per-zone systems without a baseboard, run clean (#236).

## Citation conventions

`article=` in audit entries is the NECB clause that mandates a value;
`ruling='D-nn'` is the adjudicated reading of it. The registry is
[docs/necb_decisions.md](../../../docs/necb_decisions.md) plus its
drift-tested `btap/codes/data/decisions.json` mirror; `L-nn` cites the legacy
findings register. The family glossary lives in
[docs/README.md](../../../docs/README.md).

**No `article=` citation belongs in this subpackage** — it is code-agnostic
authoring by contract.

## Tests

```bash
.venv/bin/python -m pytest -q tests/modeling/
```

## Documented future

A seed-construction-set helper (candidate for the envelope domain) ·
FloorspaceJS import · the DOE/DEER building-type-ratio wrappers (host scope).
