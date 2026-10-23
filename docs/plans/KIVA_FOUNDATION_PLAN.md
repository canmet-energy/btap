# Ground-floor method symmetry and Kiva foundations

**Status:** phases 1 and 2 landed; phase 3 was corrected to the method-neutral
D-32 disposition on 2026-10-23. Kiva is the higher-fidelity default, simple
Ground uses a declared equivalent-UA reference target, and untranslated
whole-foundation factors are an explicit tool limitation.

## The original gap, measured

Before the Kiva implementation, `btap/codes/necb/envelope/prescriptive.py`
stated:

> Nothing in this package creates Kiva foundations, so the condition is a
> property of the INPUT model

`FoundationKiva(` then appeared in no product file — only in four test
fixtures. So
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

**Only the creation half was missing.** The scope was therefore narrower than
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

## Phase 3 — corrected: preserve the method, express the Code target within it

Article 3.2.3.3.(1) sets the overall thermal-transmittance target and Sentence
(3) sets a minimum placement extent: not less than 1.2 m from the perimeter or
over the full area. Kiva is not indispensable to compliance. It remains the
higher-fidelity default because it resolves the concentrated slab-edge loss,
and it is applied symmetrically before sizing wherever the submitted
simple-Ground floor can be converted without invented properties.

For a simple-Ground floor, both proposed and reference remain simple. The
reference uses this declared approximation:

```text
Astrip = min(Afloor, exposed_perimeter * 1.2 m)
f = Astrip / Afloor
Ustrip = min(Ufield, Utable)
Ueq = f * Ustrip + (1 - f) * Ufield
```

The area is an approximation, not an exact geometric band; overlapping corner
regions and the location of partially exposed edges are unavailable. All U
values use one overall-U basis and the interior film is handled consistently
when converting `Ueq` to construction conductance. `min(Ufield, Utable)`
protects a better-than-prescriptive submitted slab. A confirmed zero edge gives
`f = 0` and no reference conductance change. The normal reference lightweight
rebuild follows and keeps that conductance while supplying mass and dynamic
response; this is not a massless scalar replacement.

The caller's model is never mutated. Article 3.4.1.2.(1) exempts the proposed
performance-path assembly from the prescriptive treatment, while 8.4.1.1.(1)
requires it in the reference target. Under symmetric Kiva, only the reference
receives physical perimeter insulation. Under symmetric simple Ground, only
the reference receives the equivalent-UA construction.

Phase 2b preflight is method-neutral. It gates missing/non-finite geometry or
perimeter, a parentless floor, missing or unusable simple-Ground construction,
a `Foundation` boundary without its object, and an exact co-planar counterpart
that proves a false Ground adjacency. Absolute elevation alone is not a
defect. Unknown no-mass layers and air gaps remain valid simple-Ground inputs;
if Kiva cannot translate them, the run falls back to symmetric simple Ground.
The known `CP02 CARPET PAD` conversion remains available for Kiva and preserves
resistance and absorptances.

`GroundFCfactorMethod` cannot use the area blend. EnergyPlus F-factor describes
whole floor-plus-soil heat transfer per exposed perimeter, not NECB assembly
U, so `U * area / perimeter` is not a valid conversion. The submitted method
is preserved and the diagnostic lifecycle completes, but no determination is
emitted (exit 6) until a validated NECB F-factor applier exists. This is a tool
gap, not an input defect or AHJ referral. The same interim disposition applies
to other unsupported whole-foundation preprocessors.

The NECB 2025 Article 8.4.4 archetype-EUI alternate path returns before the
reference lifecycle's `prepare_model` phase. It builds no reference target, so
the method-symmetry ruling does not apply there and the proposed retains its
submitted ground method. Sensitivity of that absolute EUI metric to its ground
model is a separate question.
The reference-path `--eui-supplement` does not bypass `prepare_model`; it
receives the already ground-prepared proposed model (Kiva where supported,
otherwise the retained submitted method) and any normalized rerun clones that
prepared model.

## Phase 4 — witnesses and freeze

The production-call witness checks the reference construction's calculated
`Ueq`, not an audit string. Separate controls pin symmetric Kiva, a
better-than-table slab, the measured-zero waiver, air-gap fallback, valid
F-factor no-determination, full-area treatment, and method-neutral preflight.
The phase-2b perimeter map is witnessed at the actual reference-envelope call.
Behavior-only mutations must fail those named tests while their controls stay
green.
#128's lesson applies, that a scenario reaching the SELECTION is not one
reaching the FAILURE. For E11 specifically the witness is a model whose walls
exceed the perimeter, which must be refused rather than reaching EnergyPlus.

## What this plan does not do

- **No vendored archetype table**, for the provenance reason above.
- **No submitted-model repair and no reference-only ground method.** The
  pipeline's private proposed copy and its reference use a common method; only
  the reference receives NECB's physical Kiva strip or equivalent-UA target.
- **No `openstudio-mcp` dependency** — it is a server and useful as a
  reference/source of attributed ported code, not as a product import.
- **No change to the D-105 embedded-floor trio.** The simple-Ground
  approximation is an additional ordinary-floor realization beside the
  existing `_apply_ground_strip`.

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
