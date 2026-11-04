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

## The measured limit

A generated building is representative for loads, envelope and equipment
performance, and NOT for HVAC. On `Office_pre-1960`, candidate-based
generation lands **~21% below** the source on site energy while meeting load
slightly BETTER (unmet hours 1854 -> 1717 h heating) with MORE cooling
equipment and matched COP and boiler efficiency. That is substitution, not
breakage: nine catalogue systems in place of ten hand-built ones. Do not
present a generated model as a reproduction of a specific building.
