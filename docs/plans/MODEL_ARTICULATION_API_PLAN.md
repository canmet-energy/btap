# Model articulation API and the reference-building review workflow

**Status:** planned, 2026-10-17. Direction set by phylroy: APIs for the five
authoring domains, and a workflow that creates and runs an NECB 2020/2025
reference building with an audit trail a local authority can review.

## Scope correction, 2026-10-17

The first draft of this plan proposed one `articulate()` call with
`seed constructions → thermostats → loads` as its order, treating thermostats
as a bolt-on step guarded by `require_thermostats`.

**That was wrong, and phylroy corrected it.** Setpoints are not a separate
authoring concern: space types carry schedule sets, and the thermostat falls
out of the space-type record. The code already works this way —
`btap/codes/necb/loads/apply.py#_apply_to_space_type` runs, per space type:

```
apply_people
apply_equipment
_apply_ventilation
_apply_infiltration        space-type modelling infiltration
_apply_schedule_set        occupancy/lighting/plug/setpoint schedules
_apply_thermostat          FROM the space-type record
```

then `_assign_zone_thermostats(model, audit)` hooks zones still lacking one.
A plan that added a thermostat step would have duplicated this.

The correct framing is **five domain APIs**: geometry, envelope
(constructions + infiltration), load schedules / space types (occupancy,
lighting, plugs), setpoints, and HVAC.

## What each domain actually has

Measured, not assumed:

| Domain | State |
|---|---|
| **Geometry** | Implemented. `create_shape_rectangle/_l/_t/_u/_h/_courtyard/_aspect_ratio`, `create_bar`, `create_from_footprint`, `build_massing`, `create_core_and_perimeter_polygons`. **Not exported.** |
| **Space types / schedules / loads** | Implemented. `assign_space_types`, `apply_loads` → people, equipment, ventilation, infiltration, schedule sets. **Not exported.** |
| **Setpoints** | Implemented, derived from the space-type record. No separate API needed or wanted. |
| **Envelope — infiltration** | TWO distinct things, both implemented (see below). |
| **Envelope — constructions** | **The one real product gap.** The seed exists only as a test helper. |
| **HVAC** | Implemented. `build_system` over the 102-system catalog. **Not exported.** |

### The two infiltrations

These are not the same requirement and the code is explicit about it:

1. **Space-type modelling infiltration** — `loads/apply.py:274`, from the
   space-type record (`infiltration_per_exterior_area`,
   `infiltration_per_exterior_wall_area`, `infiltration_air_changes`,
   `infiltration_schedule`). Its own docstring says it is "NOT the envelope
   domain's 8.4.3.3 air-leakage rule".
2. **The reference air-leakage default** — `envelope/reference.py:302`,
   `apply_air_leakage_default`, with `AIR_LEAKAGE_I75 = 1.50 L/(s·m²) @ 75 Pa`
   per 8.4.3.3.(3), applied as `I_AGW = (5/75)^0.6 × 1.50 × S/A_AGW` under
   8.4.4.3.(6) via 8.4.2.9.(2).

So grouping infiltration under envelope is right for (2) and under space types
for (1). The API should name both and not pretend they are one knob.

**A candidate gap worth deciding:** there is no input for a PROPOSED building's
tested air leakage. The CLI takes `--space-type`, `--space-type-map`,
`--shw-fuel`, `--hvac-system` and no air-leakage value, so a proposed model
carries whatever its spaces were built with. An AHJ reviewing a proposed
building against a reference that uses a prescribed 1.50 default would
reasonably expect the proposed value to be declarable. Confirm against the Code
before adding it.

### The one real gap

**`seed_constructions` is a test helper, not product code.** It lives at
`tests/modeling/test_bar.py:20` and nowhere in the package:

```
btap.modeling.envelope has seed: NONE
btap.modeling          has seed: NONE
```

Wizard and bar output carry no constructions, and the envelope pass only
RETARGETS existing ones. So the full-family composition pinned by
`test_full_family_composition_from_bar` **cannot be completed from an installed
wheel.** `btap/modeling/CLAUDE.md` already records it: "An opaque SEED is still
the real missing piece." That is also why no sample model ships — nothing in
the package can make one.

### The surface problem

| Package | Exported names |
|---|---|
| `btap.modeling` | **0** |
| `btap.codes` | **0** |
| `btap.audit` | 2 |
| `btap.simulation` | 8 |

Everything above is reachable only by internal module path.

## Phase 1 — close the construction gap

`btap.modeling.envelope.seed_constructions(model, ...)` as product code: a
`DefaultConstructionSet` with layered opaque constructions for every boundary
the exposed-surface census reads.

Code-agnostic by contract — it seeds a buildable baseline and applies no NECB
values, so `apply_prescriptive` remains what retargets to code conductances,
the D-77 direction holds, and no `article=` enters `btap.modeling`.

## Phase 2 — export the five domains

Give each domain a named, documented entry point and a real `__all__`.
Exporting is a support commitment, so export what has tests and nothing else:

```python
btap.modeling.geometry     create_shape_*, create_bar, create_from_footprint,
                           build_massing, apply_wwr, apply_boundary_conditions
btap.modeling.envelope     seed_constructions
btap.modeling.hvac         build_system, catalog listing
btap.codes.necb.loads      assign_space_types, apply_loads
btap.codes.necb.envelope   apply_prescriptive
```

Setpoints get no entry point of their own — `apply_loads` is where they come
from, and the docs must say so rather than leaving a reader hunting.

## Phase 3 — `articulate()` over the five domains

One call that runs the domains in the order their dependencies require, with
the silent failures closed:

```
geometry  →  space types (tags + map)  →  loads
             [schedules, infiltration, setpoints, thermostats]
          →  seed constructions  →  HVAC  →  envelope prescriptive
```

```python
from btap import articulate

model = articulate(
    shape="rectangle", width=50, depth=30, storeys=3,
    space_type="Office", hvac="Baseboard gas boiler",
    shw_fuel="NaturalGas", city="Ottawa", code="necb2020",
)
```

The sequencing constraint that matters: **bar output is standards-tagged,
wizard output is not.** So a wizard shape needs a `space_type` or
`space_type_map` before `apply_loads` can assign anything — and without space
types there are no thermostats, which is the actual mechanism behind the D-75
trap. Zones without thermostats make the envelope census return 0 walls and an
FDWR pass bail at **0 subsurfaces, reported as success**. `articulate` must
refuse to return that model.

`require_thermostats` already exists at `btap/modeling/hvac/validation.py:7`
and **nothing on the authoring path invokes it**. Wire it, and witness it at
the call site by deleting the call and naming the test that fails — six guards
this session were correct in isolation while nothing called them.

## Phase 4 — `reference()`

Wrap `btap/codes/necb/path.py#build_reference` so the reference building and
its rule trail are obtainable without a full annual compliance run:

```python
result = reference(model, code="necb2020")

result.model      # the reference OpenStudio model
result.report     # the AHJ HTML
result.articles   # every article invoked, in order, with ruling and ahj
result.audit      # the full AuditLog
```

A reference build already emits **292 article-cited decisions**, and the report
already renders `Decisions and assumptions applied` (with an Article column),
`Full audit trail`, `Reference building systems`, `Compliance checklist` and
`Scope, coverage and warnings`. `result.articles` is a projection of data that
exists — not new citation work. It must keep D-100's three axes separate and
never flatten `ahj` into `article`, and must preserve the case convention
(violations SHOUTED, passes lowercase) the checklist classifier depends on.

## Phase 5 — the spec and `btap-reference`

```yaml
# building.yaml
shape: rectangle
width: 50
depth: 30
storeys: 3
space_type: Office
hvac: Baseboard gas boiler
shw_fuel: NaturalGas
city: Ottawa
```

```bash
btap-reference building.yaml --code necb2020,necb2025 --out ./review
```

Per code id: `reference.osm`, `report.html`, `articles.json`, `audit.txt`, plus
one `spec.resolved.yaml` recording every default applied. The CLI loads the
spec and calls the Phase 3/4 functions and holds no logic of its own, so API
and CLI cannot diverge.

Both editions in one invocation is the point — side by side is what a reviewer
comparing them needs, and the independent per-edition snapshots make it honest.

## Phase 6 — ship samples

Two or three `.osm` samples in the wheel, generated BY `articulate` so they
cannot drift from the API that claims to produce them. Gate them the way
`simulate_all_systems.py --check` gates catalogue systems: a sample that stops
building cleanly fails CI instead of shipping.

## What this plan deliberately does not do

- **No new document-hygiene gates.** The decision-registry and coverage-scanner
  checks stop expanding at #122/#123. The gates worth keeping prove rules
  produce right numbers: the 54 frozen scenarios, rule verification, oracle
  parity.
- **No new `article=` citations in `btap.modeling`.** It declares nothing and
  has no coverage manifest; `lint-imports` enforces the direction.
- **No separate setpoint API.** Setpoints come from space types. Adding one
  would duplicate `_apply_thermostat`.
- **No change to the determination.** `compliance_determination`, the
  conditional label and the exit code are untouched;
  `test_the_exit_code_is_UNCHANGED_by_the_label` stays green.

## Verification

Phase 1 should move no baseline (new product code, nothing calls it yet).
Phases 3–4 will, because articulation decisions enter the audit — each
re-freezes on a clean tree in the same change.

A sample generated by `articulate` and run through `reference` becomes a frozen
scenario in its own right. That is the one pipeline no scenario currently
covers end to end from a spec, and the frozen corpus catches what focused tests
cannot.
