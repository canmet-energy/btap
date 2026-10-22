# Creating Kiva foundations, so 3.2.3.3.(3) is representable

**Status:** phases 1 and 2 landed; phase 3 adjudicated 2026-10-22. The largest
single warning class in the 28-archetype sweep, and the only one that is
compliance-material rather than diagnostic.

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

## Phases 1 and 2 — LANDED

`btap/modeling/envelope/foundations.py` plus
`python/tests/modeling/test_kiva_foundations.py` (13 tests). They run in the
**`python` CI lane** — SDK only, no EnergyPlus, and that job sets
`BTAP_SDK_REQUIRED=1` — so they are on every PR, not dispatch-only.

What the probes established on our own SDK, rather than taking on trust:

- **the courtyard measures 160.0 m**, where the raw polygon perimeter gives 240
  and a hole-filling join gives 120. Each of the eight ring slabs contributes
  exactly two of its four edges;
- **hazard 2 is real here.** `setAdjacentFoundation` on a sun-exposed surface
  leaves `sun='SunExposed' wind='WindExposed'` with the boundary condition
  already `Foundation`. The ordered write gives `NoSun`/`NoWind`. My first
  probe of this was CONFOUNDED — the floor I tested was already `Ground`, hence
  already NoSun, so the hazard appeared not to exist. The control that starts
  from `Outdoors` is the one that shows it, and it is in the test;
- **hazard 3 is real here.** `createSurfacePropertyExposedFoundationPerimeter`
  with a total of `-5.0` returns `initialized=True` and holds `None`; with a
  method of `'Nonsense'` or `'Calculate'` it reads back `''`. `is_initialized()`
  is not a success signal;
- **the massless-layer refusal fires on `openstudio.model.exampleModel()`**,
  whose ground floor carries `CP02 CARPET PAD`. That is the engine's rule
  showing up, not a defect in the check;
- **E11 refuses before writing.** 80 m of wall against a 40 m slab edge leaves
  `kivas=0`, the floor still `Ground`, and no perimeter object.

### What Fable's review changed

Six findings, all fixed in the same PR. Four were real defects the first
implementation shipped:

- **neighbours were drawn from EVERY floor at any elevation and any boundary
  condition.** Upstream filters to at-or-below-grade floors whose boundary
  condition is not `Surface`; the port dropped both filters, so an upper
  storey's plate covered the slab beneath it. On the real archetypes:
  Hangar 38 of 45 slabs zeroed and 143.1 m total, against 13 and 337.0 m
  filtered; MaintenanceShop_1980-2004 14/102.0 against 6/185.8;
  FoodService_pre-1960 10/213.4 against 7/251.3. All three now reproduce
  Fable's filtered figures exactly. The dangerous case is a plate that only
  PARTIALLY overlaps, which gives a WRONG perimeter rather than zero, so
  nothing refuses it;
- **the rollback left a half-written model.** `kiva.remove()` clears
  `adjacentFoundation` but leaves the surface reading `Foundation`, and such a
  surface forward-translates to a BLANK Foundation reference that EnergyPlus
  resolves to its own default `Foundation:Kiva`. A model the caller was told
  was unmodified would have run WITH a foundation. Reachable through the public
  API with `perimeter_m=float('nan')`, because every NaN comparison is False
  and the value therefore passed the small-value gate;
- **E11 under-counted any wall not aligned to the axes.** A wall at 45 degrees
  projects to a 7.07 x 7.07 bounding box, so `max(x_extent, y_extent)` read
  7.07 m for a 10 m wall. Five such walls (50 m true) against a 40 m slab edge
  were ACCEPTED where the unrotated control refused — a model EnergyPlus would
  Fatal on. Now measured as the longest horizontal distance between any two
  vertices;
- **the attribution did not meet the upstream licence.** See Attribution below.

Two were weaker: coincident footprints zeroed each other silently, and three
blockers had no test.

### The mutations

Nine mutations now, each reverted with the restored tree re-run green at 22
tests. Every one is caught: the grade filter (5 failures), the non-finite
refusal (2), the boundary-condition restore (1), the perimeter-object reset
(1), the wall extent (1), the twin exclusion (1), the four-vertex wall (1), the
no-construction branch (2) and the space-less blocker (1).

Three of those witnesses had to be rewritten, and each failure is worth
recording because each looked like coverage:

- **the upper-storey test first used an IDENTICAL footprint**, which the new
  duplicate-footprint rule already excludes, so it passed with the grade filter
  deleted. One of my own fixes was masking the other. A strictly LARGER plate
  is masked too, having no collinear edge. Only a partial overlap and an inset
  plate discriminate, and the test now uses both;
- **the rollback could not be reached at all** once the non-finite refusal
  landed, so deleting the restore left everything green. It is witnessed by
  INJECTING the fault instead — which is legitimate where no input can reach
  the guard, and better than deleting a guard that protects a real SDK
  behaviour;
- **the injected fault first failed without creating the perimeter object**,
  so the rollback's `reset...` call stayed unwitnessed. The real hazard creates
  the object and then discards the value, so the injection now does that too.

**One guard remains unwitnessed, and it is kept deliberately.** Deleting the
exposed-perimeter METHOD read-back leaves the suite green:
`PERIMETER_METHOD_TOTAL` is a module constant no caller can vary, so the check
can only fire if someone edits the constant to an invalid string. Fable
confirmed independently that it is unreachable from the public API. It stays as
documentation of a real SDK behaviour — `'Nonsense'` and `'Calculate'` both
read back as `''` — and is honestly untested.

### Known simplifications, shared with the source

A basement floor at z=-3 abutting a slab at z=0 covers the shared edge in
plan, in both directions. That is a step-down the upstream makes too, not a
port defect, and it is noted in the module rather than silently inherited.

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

**Done.** `create_kiva_foundation(model, floor, walls=(), *, perimeter_m=None,
name=None)` returns a result dict and leaves the model untouched on refusal.

One function in `btap.modeling.envelope`, code-agnostic, creating a
`FoundationKiva` per eligible ground floor — one floor per object — in the
probed order: boundary condition, then `setAdjacentFoundation`, then the
exposed-perimeter object read back and compared rather than trusted.

It sets NO insulation. NECB's strip is `btap.codes.necb`'s to prescribe and
`_apply_ground_strip` already does it, so this keeps the D-77 direction intact
and puts no `article=` in `btap.modeling`.

## Phase 3 — adjudicated: one method on both sides

D-32 now requires the same EnergyPlus Kiva ground-heat-transfer method on the
pipeline's proposed and reference copies before sizing. Reference-only Kiva
would make the 8.4.1.2 comparison carry two changes: the prescribed perimeter
strip and a change of ground solver. Symmetric Kiva is calculation-method
normalization under 8.4.2.1, 8.4.2.2, 8.4.2.4 and 8.4.2.8, not a correction of
the submitted building:

- the caller's model is never mutated;
- the proposed copy retains its submitted slab-field thermal resistance and
  receives no prescribed perimeter insulation;
- the reference inherits that Kiva foundation and then receives D-32's 1.2 m
  strip.

This ruling is deliberately narrower than "put Kiva on every ground floor."
It applies only to ordinary floors in the perimeter-strip branch. Full-area
climates remain on the existing full-area construction path. Detected embedded
floors and unresolved embedded-system cases remain on D-105's path. Floors with
invalid topology, no exposed perimeter, or an unsupported material
representation remain unchanged and visibly refused.

Kiva cannot translate a massless layer. The one known fixture representation,
`CP02 CARPET PAD`, is converted on each eligible floor's private construction
using the pinned oracle's thin-carpet properties while preserving resistance
and submitted absorptances. Unknown no-mass layers and air gaps are not guessed.
The conversion adds sourced carpet heat capacity and is disclosed as such.

An EPW is not an equivalent substitute. It does not uniquely prescribe the
monthly `Site:GroundTemperature:BuildingSurface` series without another
depth/model choice, and a simple `Ground` boundary still cannot represent the
2-D perimeter strip.

## Phase 4 — the witness, and the freeze

A Kiva foundation changes the solved soil domain, so it moves energy. Expect
all 56 scenarios, and expect NUMERIC movement — unlike every re-freeze in the
last three days, this one legitimately changes results, which makes the
before/after diff the review surface rather than a formality.

The witness must be at the call site and mutated: deleting the neutral
pipeline's `prepare_model` call must make a real compliance determination lose
its proposed and reference Kiva foundations, while the full-area control stays
green. The witness also checks that only the reference has the 1.2 m strip and
that a zero-perimeter floor is refused before its construction changes.
#128's lesson applies, that a scenario reaching the SELECTION is not one
reaching the FAILURE. For E11 specifically the witness is a model whose walls
exceed the perimeter, which must be refused rather than reaching EnergyPlus.

## What this plan does not do

- **No vendored archetype table**, for the provenance reason above.
- **No submitted-model repair and no reference-only ground method.** The
  pipeline's private proposed copy and its reference use the same Kiva method;
  only the reference receives NECB's strip.
- **No `openstudio-mcp` dependency** — a server, BSD, useful as a reference
  and a source of ported code, not as an import.
- **No change to `_apply_ground_strip` or the D-105 trio.** Both already work
  when a foundation exists; this plan is about making it exist.

## Attribution

**The upstream licence is not BSD**, which an earlier draft of this plan and
the first implementation both said. It is the four-condition OpenStudio(R)
licence, copyright Alliance for Energy Innovation, LLC, and its condition (1)
requires a source redistribution to retain the copyright notice, the list of
conditions and the disclaimer. A docstring naming the repository does not
satisfy that.

So ported code carries `python/btap/modeling/envelope/data/ATTRIBUTION.md`,
which ships in the wheel under the `data/**/*.md` package-data glob and
reproduces the licence in full, names the ported revision
(`17e4deeae8465f6931c84a69ce3f7d06bbbb26da`, `develop` at fetch time), the
Zenodo DOI `10.5281/zenodo.21905081` and the SoftwareX DOI
`10.1016/j.softx.2026.103020`, and lists which functions derive from it. The
module docstring points at that file.

The pre-existing `btap/codes/data/coverage/ATTRIBUTION.md` is NOT the pattern
for this: it covers Crown-copyright NECB text, not third-party code, and both
the first draft of this plan and the first docstring cited it at a path that
does not exist.
