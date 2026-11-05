# CLAUDE.md — `btap.stock`

The sixth subpackage. It derives a **recipe** from an existing model and
builds a model from a recipe, for stock and retrofit work on buildings that
may never see a compliance run.

## It sits BESIDE `btap.codes`, not inside `btap.modeling`

Both consume `btap.modeling`; neither imports the other. Import-linter holds
it as a sibling layer, so **`stock` may import `modeling`, `modeling` may NOT
import `stock`, and `stock` may not import `codes`**.

The reason is not tidiness. `btap.modeling`'s value is having NO OPINION, and
`modeling/hvac` acquired 37 embedded NECB-derived values precisely because no
boundary told anyone not to — which is the defect #183 exists to fix. A recipe
layer living inside `modeling` would recreate those conditions. `btap.codes`
is the shape precedent: a neutral core plus a domain family.

## There is NO `data/` directory here, deliberately

The library ships no vintage data (phylroy, 2026-11-02: "none initially"). A
recipe is AUTHORED INPUT, not a shipped table, which keeps NECB's edition
snapshots the only authority in the distribution. The field inventory derived
from the external ECM projects is a REFERENCE artifact at
`docs/reference/ecm_field_inventory.json` — nothing in the package reads it —
and is refreshed by `scripts/fetch_ecm_field_inventory.py` through an
authenticated `gh` session, so runtime and CI stay offline.

An author adding `btap/stock/data/` should expect to be asked which authority
its numbers come from.

## Four rules the writer and reader share

These are what make the output trustworthy rather than merely plausible, and
each exists because its absence produced a measured error:

- **Generic, not exhaustive.** One value per assembly class, per space type,
  per plant. An exhaustive per-surface recipe is a second copy of the model
  and cannot be applied to different geometry. Collapsing HVAC by signature
  took `Office_pre-1960` from 47 zone groups to 10 descriptions.
- **Absent, never defaulted.** A value the writer cannot read is omitted and
  listed. This is why the readers do NOT reuse
  `envelope.constructions.fenestration_solar_transmittance`, which falls back
  to 0.60 — correct when APPLYING a construction, a fabrication when reading
  one. It is also what made a missing fenestration section visible rather
  than plausible.
- **Every aggregate carries its SPREAD.** The mean is preserved by a round
  trip and the DISTRIBUTION is destroyed: measured, `Floor:Ground` on the
  Office archetypes goes 4.22x -> 1.0x. An exact U match is therefore NOT
  evidence of a lossless round trip, only that the aggregation is idempotent.
- **Nothing invented, above all not a system name.** `catalog_name` is null
  for every zone group of every hand-built archetype, and that is
  `hvac/classify.py` being correct: it resolves the air loop's NAME against
  the catalogue, and structural identification cannot substitute because "the
  facts a classifier needs here are DESTROYED by the time the coil scan
  runs". `identify.py` supplies RANKED CANDIDATES with the facts that matched
  and the facts that did not; `suggest_systems=` and `accept_candidates=` are
  both OFF by default, and a system built from a candidate is audited as one.

## Order matters in the reader, and getting it wrong is silent

`hvac.builder.build_system` is TOPOLOGY ONLY and runs with
`remove_existing=True`, so it destroys the equipment serving those zones.
HVAC is therefore built BEFORE the equipment and controls sections, or their
values land on objects that are then torn down. The first version had it the
other way; every section was correct in isolation and only an end-to-end
simulation could show the sequence was not.

## The measured limit, and why the first number was MISATTRIBUTED

A generated building is representative for loads, envelope and equipment
performance, and only approximately for HVAC. On `Office_pre-1960`,
candidate-based generation lands about **21% below** the source on site
energy.

**Most of that gap is a DEFECT IN THE SOURCE MODEL, not a limit of
generating from a recipe.** This file previously said the 21% was
substitution rather than breakage, with no further account. The measurement
was right and the attribution was wrong, and the decomposition (2026-11-05)
is:

- the three `Office` archetypes carry TWO `SetpointManager:MixedAir` objects
  on the VAV loop that reference EACH OTHER — in `Office_pre-1960`,
  `Node 149` is set from `Node 155` and `Node 155` from `Node 149`. Each hop
  subtracts fan heat, so the target spirals: the simulated supply air
  averages **-48.5 C** and the reported setpoint falls below **-1000 C**. The
  DX coil chases it while terminal reheat fights back, burning **76.06 MWh**
  of cooling electricity where the rebuilt model uses **6.11**;
- correcting ONLY that manager, with every other source object untouched,
  takes the source from **1,468.43** to **1,182.12 MWh/yr** and leaves the
  generated model just **3.28%** lower. Heating unmet hours barely move
  (1854 -> 1853.25 h), which is what shows the change is not a capacity
  thaw. That is **88.1%** of the gap;
- the other 21 shipped archetypes are clean. No test or scenario reads the
  three Office models, so nothing we validate against is affected.

What remains is attributable rather than mysterious: rebuilt CV supply fans
take **250 Pa** where the source has **500 Pa** (the recipe does NOT capture
fan pressure rise — a real gap), the recipe's AVERAGED fan efficiency moves
retained exhaust fans from 0.60 to 0.711111 by design, and two heating plants
become one pump.

A generated model also carries **five Severes of its own** that the source
does not: retained `Fan:ZoneExhaust` inlet nodes are orphaned by the HVAC
teardown (issue #201). Count Severes against the source before reading a
generated run as evidence.

Open: #200 the archetype setpoint cycle, #201 the orphaned exhaust-fan nodes,
#202 the uncaptured fan pressure.

So: do not present a generated model as a reproduction of a specific
building, and do NOT quote a headline gap against a hand-built archetype as a
property of this package until the archetype's own HVAC has been read. On
this model the generated building is arguably the better one.

## The identifier scores FACTS, and the fuel is not the coil medium

`identify.py` ranks catalogue rows against the facts `classify.characterize`
produces, and three of those facts are easy to misread. Each of these was a
real defect, found 2026-11-04 by two independent agent reads of
`gagetown_coldlake_Office_pre-1960.osm`:

- **`heating_energy_types` is the fuel resolved THROUGH the plant, not the
  coil medium.** All four of that model's central loops report
  `['NaturalGas']` while their coil is a `Coil:Heating:Water` on a gas boiler.
  Scoring the fuel alone let a direct-gas burner take a "gas coil matches gas
  heating" credit on a hydronic building. `supply_heating_media` is the fact
  that carries the medium, recorded from the SUPPLY path only — a terminal
  reheat coil is not the loop's coil.
- **`cooled` is a UNION of loop and zonal cooling.** That model's four-zone
  loop has NO cooling coil; its `cooling_energy_types: ['Electricity']` comes
  from two zonal PTACs. `loop_dx_cooling` is what says whether the LOOP cools,
  and a row that does not cool the air handler is CORRECT for such a group.
- **`ventilation_sized` does NOT mean "has outdoor air".** It is true only
  when the sizing basis is `VentilationRequirement` — "a DOAS whose coil
  tempers make-up air". OA PRESENCE is `system_outdoor_air_method`: a string
  when a controller exists, `None` when none does. Conflating them meant a
  no-OA row was marked down only against a DOAS, never against an ordinary
  mixed-air loop, and building one DELETES the ventilation and the economizer
  (`set_economizer_in_model` skips a loop with no controller, so the reader
  cannot restore it).

A row that OMITS a coil field is not silent when its BUILDER defaults it:
`furnace.py` is `config.get('heating_type', 'Gas')`. `_BUILDER_COIL_DEFAULTS`
mirrors five builders and a test re-reads their source so the mirror cannot
drift. Heat-pump rows carry `heat_source` instead of a coil type, and
`composite` rows delegate to `parts` — which is why the medium is a SET.

**One system per group is the standing limit.** `reader._build_hvac` builds
exactly one, with `remove_existing=True`, and nothing builds the group's
baseboards or PTACs afterwards. So a row carrying no baseboards DROPS them,
and a comment claiming they "come from their own row" was false. Until the
reader can build zonal equipment separately, a group with baseboards and
zonal cooling has no fully correct single answer.

Adding a catalogue row to satisfy any of this is FOUR gates, not one: the
sizing sweep, the ADJUDICATED D-58 golden (never regenerated from Python, per
D-79), the catalog-generation names, and `tests/stock/`.
