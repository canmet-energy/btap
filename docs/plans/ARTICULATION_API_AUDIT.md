# Articulation API audit — what a user can author, and what they cannot

**Status:** audit, 2026-10-25. No code changes. Measured against `main` at
`86ed3513`, the pinned oracle at `legacy_pin/REF`
(`f01da13a6b89e45761d1ede481fedb1c1aeb6ea0`), and the NECB 2020/2025 Section
8.4 caches.

`btap.modeling` is the code-agnostic authoring layer: it BUILDS a model.
`btap.codes.necb` APPLIES NECB values to one. The distinction matters
throughout, because several domains below are reachable only through the NECB
path — a user modelling a non-NECB scenario, or an ECM, cannot author them at
all.

## The blocking gap: no construction set can be seeded

`btap/modeling/README.md` states the authoring chain and its precondition:

> Bar and wizard output carries **no constructions** — downstream envelope
> work retargets existing ones, so **seed a basic construction set** (or start
> from an OSM that has one) before any envelope pass. With that, the full
> authoring chain is in-package.

There is no public API to seed one. The only implementation in the repository
is `seed_constructions`, a METHOD ON A TEST CLASS at
`python/tests/modeling/test_bar.py:20`. So the documented chain cannot be
started from the shipped wheel; it can only be started from an OSM someone
else authored.

`btap.modeling.envelope.constructions` does exist and is substantial — 24
public names, `opaque_at_conductance`, `fenestration_at_conductance`,
`find_and_set_insulation_layer`, film resistances, deep copy. Every one of them
RETARGETS an existing construction. None creates a set. And
`btap.modeling.envelope` itself exports nothing: the module is reachable only
by its full dotted path.

This is the one item on this list that blocks a documented workflow, and it is
the cheapest to close.

**CLOSED** by `3c39e7d9` (PR #144): `modeling.seed_constructions` is a public
audited facade, the test-local helper is gone, and `scripts/wheel_smoke.py`
runs the documented chain's first step from OUTSIDE the checkout against a
built wheel.

### What skipping the precondition actually does

Recorded here because that commit's own message and PR description say
something FALSE, and a commit message cannot be corrected: they state that the
full chain "DUMPS CORE on unseeded surfaces". **It does not.** Measured on the
documented chain with the seed omitted, `faulthandler` enabled:

    unseeded surfaces: 144 of 144
    loads... lighting... shw... build_system... prescriptive...
    SURVIVED the whole chain, exit 0
    AFTER: 144 of 144 still bare, 0 constructions in the model

and `apply_prescriptive` warns once per skipped surface:

    [warning] Surface 102    | surface has no layered construction — skipped
    [warning] Sub Surface 22 | subsurface has no layered construction — skipped

71 `prescriptive` audit entries, most of them those. That is the architecture
working as documented — warnings are never silent, and everything past the
preflight gate is disclosure.

The claim came from conflating two real but separate observations: the chain
completing at 0-of-54 surfaces in an early probe, and a genuine SIGSEGV in the
new test file's own unguarded `.to_StandardOpaqueMaterial().get()` under
mutation (issue #141's mechanism, diagnosed and fixed in the same PR). The
crash was real; it was in the tests, not in the chain.

So there is no refusal to add here. Whether the authoring API should REFUSE a
model it cannot retarget, rather than warn per surface, is a genuine design
question — but an ordinary one, and `performance_compliance` already gates its
own entry point in `codes/necb/path.py`.

## Domain-by-domain

| domain | author it? | apply NECB to it? | legacy reference |
|---|---|---|---|
| geometry | **yes** — `bar`, footprint wizards, `create_from_footprint`, plans, 3D render | n/a | ported |
| envelope retargeting | **yes** — `constructions.py`, 24 names | yes | ported |
| envelope SET seeding | **no** — test-only | n/a | — |
| foundations (Kiva) | **yes** — `envelope/foundations.py` | yes | n/a (new) |
| HVAC systems | **yes** — 102-system catalogue, `build_system`, `replace_system`, teardown | yes | ported |
| SHW | **no** create-side | yes — `codes/necb/shw/` | ported |
| loads (people, lights, equipment, infiltration) | **no** | yes — `codes/necb/loads/`, `codes/necb/lighting/` | `ECMS/loads.rb`, 94 lines |
| schedules | **no** general API — only HVAC availability/setpoint schedules in `hvac/components/schedules.py` | yes — `codes/necb/loads/schedules.py` | 54 gem files use `ScheduleRuleset` |
| renewables (PV) | **no** — we can only READ a collector (`shw/efficiency.py:404`) | no | **`ECMS/pv_ground.rb`, 107 lines, + `data/pv.json` + `btap/costing/pv_ground_costing.rb`** |
| natural ventilation | **no** | no | **`ECMS/nv.rb`, 192 lines** |
| electric storage (batteries) | **no** | no | none — greenfield |
| thermal storage (ice, chilled/hot water) | **no** | no | none — greenfield |
| solar wall (transpired collector) | **no** | no | one `Standards.PlantLoop.rb` reference only |
| ERV | **yes** (built by HVAC systems) | yes | `ECMS/erv.rb`, 30 lines |

## Renewables and storage are NOT a compliance-coverage gap

Checked against both editions' Section 8.4 caches. "Solar" appears 20 times
and is always absorptance or gains — `8.4.2.8`, `8.4.3.3`, `8.4.4.3`.
"Storage" appears 14 times and is always service-water tank capacity or
equipment characteristics — `8.4.3.5`, `8.4.4.6`, `8.4.4.20`. Neither edition
prescribes on-site generation or batteries anywhere in Section 8.4, and
"photovoltaic", "renewable", "battery" and "transpired" appear ZERO times.

So these are not missing compliance rules. They are missing MODELLING
capability — ECM and incentive-study territory — which is exactly why the
legacy carried PV under `standards/necb/ECMS/` rather than as a reference rule.
A proposal for them should be argued on modelling value, not on code coverage.

## Reference material that already exists

The pinned oracle is checked out at `vendor/bundle/.../openstudio-standards-f01da13a6b89`
and carries three directly usable references. CLAUDE.md's rule applies to all
of them: the gem is evidence of an approach, never an authority, and it has
already been caught shipping wrong data five times.

- **`standards/necb/ECMS/pv_ground.rb`** — `apply_pv_ground(model:,
  pv_ground_type:, pv_ground_total_area_pv_panels_m2:, pv_ground_tilt_angle:,
  pv_ground_azimuth_angle:)`. 107 lines, NECB lineage, with `data/pv.json` and
  a costing companion at `btap/costing/pv_ground_costing.rb`. This is the
  closest thing to a specified feature on the list.
- **`standards/necb/ECMS/nv.rb`** — 192 lines of natural ventilation.
- **`standards/necb/ECMS/loads.rb`** — 94 lines of load scaling.

Other NREL repositories are the natural reference for the greenfield items,
and I have NOT read them — they are not vendored here, so this names them as
candidates rather than citing them:

- `NREL/openstudio-model-articulation-gem` — the closest analogue to this
  layer's whole purpose; worth reading before designing a loads/schedules API;
- `NREL/openstudio-load-flexibility-measures-gem` — electric and ice thermal
  storage, which the pinned gem has nothing for;
- `NREL/openstudio-common-measures-gem` — schedule and load authoring
  patterns.

Reading them is a prerequisite for the storage and solar-wall items, not for
PV or natural ventilation, where the NECB-lineage code is already on disk.

## Proposed order

**P1 — seed a construction set. DONE, `3c39e7d9`.** Promote `seed_constructions` out of
`tests/modeling/test_bar.py` into `btap.modeling.envelope` and export it.
Closes the one documented-workflow blocker. Small, and it needs a test that
the DOCUMENTED chain runs end to end from the wheel, which is what nothing
currently proves.

**P2 — loads and schedules articulation.** Today these exist only as NECB
application. A user cannot author a custom occupancy schedule or a load
density without reaching past our API into raw OpenStudio. `ECMS/loads.rb` is
a reference for scaling; schedule authoring should be designed against
`openstudio-model-articulation-gem` rather than invented.

**P3 — ground-mounted PV.** The legacy has a specified implementation, data
file and costing path. Needs a decision on whether generation is reported
separately from consumption in the compliance report, which is an adjudication
and not a coding question.

**P4 — natural ventilation.** `nv.rb` is a 192-line reference.

**P5 — electric and thermal storage, solar wall.** Greenfield, no NECB
provision, no legacy reference. Each needs its own scoped proposal and a reason
beyond completeness.

## What this audit did not establish

Whether any of P2–P5 is WANTED. The audit measures absence, not demand. P1 is
different: the repository's own README documents a chain that cannot be run,
so that one is a defect regardless of roadmap.
