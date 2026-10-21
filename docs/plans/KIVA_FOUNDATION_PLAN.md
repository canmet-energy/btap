# Creating Kiva foundations, so 3.2.3.3.(3) is representable

**Status:** planned, 2026-10-21. The largest single warning class in the
28-archetype sweep, and the only one that is compliance-material rather than
diagnostic.

## The gap, measured

`btap/codes/necb/envelope/prescriptive.py:203` states it plainly:

> Nothing in this package creates Kiva foundations, so the condition is a
> property of the INPUT model

`FoundationKiva(` appears in no product file — only in four test fixtures. So
when a ground floor in a perimeter-strip zone has no `adjacentFoundation`,
the aggregated warning at line 254 fires:

> N ground floors have NO Kiva foundation in a perimeter-strip zone — the
> 1.2 m insulated strip required by 3.2.3.3.(3) is not representable and those
> slabs are left AS MODELLED, so the prescribed perimeter insulation is NOT
> applied

`article="3.2.3.3.(3)", ruling="D-32"`. It fired **588 times across 26
archetypes** (~22 per model) before #125 aggregated it. Table 3.2.3.1's floors
row below zone 8 prescribes the strip; without a foundation the reference keeps
the proposed slab and the allowance is not applied.

## What we already have — more than a first look suggests

This plan is NOT starting from zero, and an early draft of it got this wrong.
When a Kiva foundation IS present the product already:

- **applies the strip.** `_apply_ground_strip` computes
  `r_add = 1/target - slab_r` and sets Kiva interior horizontal insulation;
- **reads the exposed perimeter.** `_floor_exposed_perimeter` takes
  `totalExposedPerimeter`, else `exposedPerimeterFraction x` the polygon
  perimeter, else the geometric perimeter — "also the forward translator's
  default for a Kiva floor";
- **validates three failure modes under D-105**, each cited to `3.2.3.3.(5)`:
  MIXED adjoining wall heights (one vertical-insulation depth over-insulates
  the shorter instances), a PARTIAL-PERIMETER wall condition (EnergyPlus
  creates a zero-wall-height slab-remainder instance), and a foundation SHARED
  by multiple floor surfaces, quoting the engine's own
  "only one floor per Foundation:Kiva Object allowed".

**Only the creation half is missing.** The scope is therefore narrower than
"port a Kiva subsystem": it is the write path, plus the one computation we have
never needed because we only ever read the property.

## There is a working external reference

`canmet-energy/openstudio-mcp` (SWR 26-035, in *SoftwareX*, BSD-licensed,
`openstudio==3.11.0` with NO openstudio-standards — the same contract this
package holds, and the same SDK the CI image pins) carries a complete Kiva
subsystem: `kiva_foundation.py`, `kiva_apply.py`, `kiva_eligibility.py`,
`kiva_archetypes.py`, `tools_kiva.py`, and 69 KB of tests.

BSD into GPL-3.0-or-later is the permitted direction, so code may be ported
WITH ATTRIBUTION. It is a server, so it cannot be a dependency of a library;
what transfers is the knowledge and the structure.

### Five SDK facts it has already paid for

Probed against OpenStudio 3.11.0 / EnergyPlus 25.2.0 — the exact pair our CI
image pins. Each is a defect we would otherwise ship once and find later:

1. **`model.getFoundationKivaSettings()` CREATES the unique object**;
   `getOptionalFoundationKivaSettings()` does not. A read path using the
   non-optional form silently mutates the caller's model — the same hazard
   class as `_set_data_root`'s test-only hook.
2. **`Surface.setAdjacentFoundation(kiva)` leaves SunExposed/WindExposed
   intact** — fictitious solar gain on a buried slab. Order must be
   `setOutsideBoundaryCondition("Foundation")` FIRST, which derives
   NoSun/NoWind, THEN `setAdjacentFoundation`.
3. **`createSurfacePropertyExposedFoundationPerimeter` returns an INITIALIZED
   optional even when it rejected the input.** `is_initialized()` is not a
   success signal: whitelist the method, range-check, then read back and
   compare. A second call returns an empty optional rather than overwriting,
   so re-applying needs `resetSurfacePropertyExposedFoundationPerimeter()`.
4. **`Surface.exposedPerimeter()` SEGFAULTS on a space-less surface** — no
   exception, the interpreter dies, reproduced twice on 3.11.0. Every path
   must check `space().is_initialized()` first.
5. **Neither `Surface.exposedPerimeter()` nor `joinAllPolygons()` can compute
   the perimeter**: both assert `|z| <= tolerance` on every point, so a
   basement floor scores 0.0; and the join fills holes, so a building around
   an open courtyard lost 40 m — a 3x3 ring of 10 m slabs gave 120 m instead
   of 160 m. Their interval-subtraction method projects edges to z=0 and
   subtracts intervals under a collinear edge of another floor, agreeing with
   the SDK on `exampleModel()` where the SDK is right.

`BySegment` is legal IDD and deliberately not offered: EnergyPlus cannot
auto-correct a clockwise floor polygon under it.

### Their refusal list, against ours

From the 25.2 binary's own error strings. Marked for what we already cover:

| Rule | Us |
|---|---|
| only ONE floor per `Foundation:Kiva` object | **warned** (D-105) |
| only floor and wall surfaces may reference Foundation | — |
| a Foundation surface with no exposed-perimeter property is FATAL | — |
| Kiva walls must have at most four vertices | — |
| Foundation surfaces need regular materials, no massless | partly (`reference.py:262`) |
| Foundation is not allowed with windows | — |
| Kiva requires a weather file; no design-day-only run | — |
| paired wall lengths must not exceed the floor's exposed perimeter | — |

The last is **Fable's E11**, found while reviewing #121 and recorded only in
`.reviews/to-claude/293-fable-pr121.md`. CLAUDE.md is explicit that `.reviews/`
is gitignored "and so was never a record of them", so capturing it here is
part of the point. His measurement: selected walls 80 m against an exposed
40 m gives `** Fatal ** Kiva: Errors discovered, program terminates.` We
compute `_wall_floor_contact_length` already and never compare it to the
perimeter, so the check is close to free. `kiva_apply.py` refuses it before
writing anything.

## Phase 1 — compute the exposed perimeter, and refuse what E+ will reject

Port the eligibility half first. It writes nothing, needs no EnergyPlus run,
and its absence is what would make Phase 2 dangerous:

- `_has_space()` as a non-optional guard before any `exposedPerimeter` call;
- the interval-subtraction perimeter, which must agree with
  `_floor_exposed_perimeter` wherever that already returns a value. The
  courtyard case (160 m, not 120 m) is the witness that the SDK join was not
  usable;
- the refusal table above, each with a REASON, extending the D-105 trio rather
  than duplicating it. E11 lands here.

## Phase 2 — create the foundation

One function in `btap.modeling.envelope`, code-agnostic, creating a
`FoundationKiva` per eligible ground floor — one floor per object — in the
probed order: boundary condition, then `setAdjacentFoundation`, then the
exposed-perimeter object read back and compared rather than trusted.

It sets NO insulation. NECB's strip is `btap.codes.necb`'s to prescribe and
`_apply_ground_strip` already does it, so this keeps the D-77 direction intact
and puts no `article=` in `btap.modeling`.

## Phase 3 — decide WHEN the reference creates one

The adjudicated part. Needs Sol.

Today the reference inherits whatever foundations the proposed carries and
warns when there are none. Creating one changes the reference building. For:
3.2.3.3.(3) prescribes the strip, we cannot apply it, and the alternative is a
reference slab identical to the proposed. Against: a Kiva foundation is a
modelling choice about soil and footing geometry the proposed did not make, and
phylroy's ruling of 2026-10-21 is that reference creation builds from what is
available rather than correcting the proposed.

Those pull opposite ways and the answer is not mine to pick. Creating on the
REFERENCE only is the posture `_reconcile_declared_storeys` already takes, for
the reason its comment gives: the caller's model is not ours to edit.

If yes, it needs a decision record, and the archetype question arrives with it:
Kiva wants insulation position and extent. NECB prescribes the extent (1.2 m);
position and soil it does not. `kiva_archetypes.py` is explicit that its own
numbers are "conventional starting points rather than anything sourced", so
they cannot be imported as though sourced.

## Phase 4 — the witness, and the freeze

A Kiva foundation changes the solved soil domain, so it moves energy. Expect
all 56 scenarios, and expect NUMERIC movement — unlike every re-freeze in the
last three days, this one legitimately changes results, which makes the
before/after diff the review surface rather than a formality.

The witness must be at the call site and mutated: delete the creation call and
the aggregated "N ground floors have NO Kiva foundation" warning must return.
No scenario currently exercises a created foundation, so one is needed — and
#128's lesson applies, that a scenario reaching the SELECTION is not one
reaching the FAILURE. For E11 specifically the witness is a model whose walls
exceed the perimeter, which must be refused rather than reaching EnergyPlus.

## What this plan does not do

- **No vendored archetype table**, for the provenance reason above.
- **No proposed-model foundations.** Phase 2 creates on request; Phase 3 may
  authorise the reference only.
- **No `openstudio-mcp` dependency** — a server, BSD, useful as a reference
  and a source of ported code, not as an import.
- **No change to `_apply_ground_strip` or the D-105 trio.** Both already work
  when a foundation exists; this plan is about making it exist.

## Attribution

Ported code carries its origin in the module docstring: repository, revision,
the SoftwareX DOI and the BSD notice. `btap/codes/data/ATTRIBUTION.md` is the
existing pattern.
