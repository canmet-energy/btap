# Review: is classify + identify the right architecture for the HVAC recipe?

Reviewer: Fable (Claude), 2026-11-06. Read-only; no source touched.
Status: complete. Sections 0-7; the experiment behind section 4 is reproducible from `self_consistency.py` in this directory.

## 0. Short answer

No, and not for the reasons the four defects individually suggest. Each of
the four is a real bug and each has a local fix, but all four are instances
of one structural fact: **the recipe does not describe the building's HVAC;
it describes a QUERY against a catalogue, and the catalogue was built for a
different consumer.** Everything the writer measures is thrown into a
~14-key dict (`btap/stock/hvac.py:35-47`), the dict is scored against 110
fixed bundles (`btap/stock/identify.py:242-624`), and the WINNING BUNDLE —
not the measurement — is what gets built (`btap/stock/reader.py:497-507`).
Any measured fact that no catalogue field encodes is lost at that step, by
construction, and the only way to stop losing it is to add a row — which is
the catalogue-doubling path issue #217 already names.

The honest sentence in the codebase is in `identify.py:9`: "This does not
overturn the refusal rule; it supplies evidence to it." The scorer is a
workaround for a rule (`catalog_name` is never synthesised) that is correct
for its original purpose and simply does not apply to this one. A recipe
does not need to NAME the source system. It needs to REBUILD something that
behaves like it. Those are different problems, and only the second is
solvable.

The measurement that makes this more than an opinion is in section 4: asked to
recover the catalogue's OWN 110 rows from models the catalogue built (loop
names scrubbed), the scorer puts the building row first for 18 of them and
substitutes a different FAMILY for 60 — deleting chillers, fan coils and
PTACs in the process. Fitting more weights will not close that; the
representation will.

(Details, citations and the proposal follow.)

## 1. What the pipeline actually is, read from the code

The pieces, with what each one does to the information:

| Stage | File | What survives |
|---|---|---|
| Model → group facts | `btap/modeling/hvac/classify.py:160-236` (`characterize`), `_base_group` at `:644-678` | ~30 keys per group: fuels, media, terminal kind, zonal unit kinds, DX/hydronic loop cooling, HRV, OA method, DCV, HP sources, cooling kW, plant names, evidence |
| Group facts → recipe | `btap/stock/hvac.py:35-47` (`_DESCRIPTIVE`), `:80-122` | **14 keys**. Dropped: `loop_hydronic_cooling`, `cooling_plants`, `design_cooling_kw`, every heat-pump source key, `terminal_type` variants beyond the string, the count of source loops (recorded as `zone_groups` at `:105` but never read back) |
| Recipe → candidate | `btap/stock/identify.py:627-654` + `_score` at `:242-624` | one catalogue NAME and a score |
| Candidate → model | `btap/stock/reader.py:473-527` | `build_system(model, chosen['system'], zones, remove_existing=True)` at `:506` — the row's fixed bundle, nothing from the recipe |
| Name → topology | `btap/modeling/hvac/builder.py:97-199`, `systems/*.py` | the builder reads only `self.config` = the catalogue row (+ `config=` overrides, which the reader never passes) |

Three observations fall straight out of that table.

**(a) The recipe is not the thing that gets built.** `_build_hvac` passes
the candidate's NAME and nothing else (`reader.py:506-507`). `build_system`
accepts a `config=` override dict (`builder.py:97-98,137-138`) that could
carry measured values into the builder, and the reader never uses it. So
every measured fact that is not ALSO a field of the winning row is discarded
at the moment of building. Defects 2, 3 and 4 are each exactly this: the
HRV (2) was in the row and not in the facts; the economizer limits (3) were
in the recipe and not in the row; the "no air loop" (4) was in the recipe
(`air_loops: []`, `hvac.py:107`) and not in the row's family.

**(b) The scorer compensates for a lossy intermediate by growing.** Every
comment block in `identify.py` that starts "FIX:" or "MY RATIONALE HERE WAS
FALSE" (`:300-313`, `:381-392`, `:413-420`, `:499-512`, `:535-549`) records
the same event: a fact was found missing or misread, and a new branch with a
new hand weight was added. The weights are not calibrated against anything
— `identify.py:267,289,298,309,321,325,336,342,346` etc. are literals chosen
to make the then-current test fixture rank correctly. That is the signature
of a classifier being fitted to its own test set one case at a time, and
#214/#220 are what it looks like when the next case arrives.

**(c) Two vocabularies in one catalogue** (`identify.py:270-284`): the
NECB-shaped rows say `heating_coil_type`/`baseboard_type`; the six campus
rows say `heating`/`cooling`/`ventilation`/`heating_type`/`reheat`/
`per_zone`. The scorer has to read both and infer builder defaults for
fields that are absent (`_BUILDER_COIL_DEFAULTS`, `:135-142`, mirrored from
builder source and pinned by a test that re-reads that source). This is a
second, hand-maintained schema of the catalogue living inside the scorer.

## 2. A fifth defect, found by running the scorer

I did not take the four defects as the list; I ran `identify_candidates`
on a fact dict for the single most ordinary large-building system in
Canada — a built-up VAV with a chilled-water cooling coil, hot-water reheat
and a gas boiler, no baseboards, with outdoor air:

```
 10.75 furnace      Shared hot water air handler with water reheat   <- WINS: cooling: False
  8.25 furnace      Shared hot water heating-only air handler
  6.00 vav_reheat   PVAV with gas boiler reheat
        - "the GROUP is cooled only by zonal equipment ... but this row puts cooling on the air handler"
  5.00 vav_reheat   VAV chiller with gas boiler reheat
        - (same objection)
```

The top candidate is a heating-only air handler. The building's entire
cooling plant would be dropped, and the audit would say so only in the
`against` list of rows that lost.

Cause, two lines: `_DESCRIPTIVE` (`btap/stock/hvac.py:35-47`) carries
`loop_dx_cooling` and NOT `loop_hydronic_cooling`, although `characterize`
sets both (`classify.py:1083-1085` sets hydronic, `:1133-1134` sets DX); and
the scorer defines `zonal_cools = bool(cool) and not loop_cools` where
`loop_cools` reads only `loop_dx_cooling` (`identify.py:327-328`). A
chilled-water coil on the loop therefore reads as "cooled by zone units",
every cooling row takes -2.5 (`:335-340`) and the two no-cooling campus rows
take +2.0 (`:367-370`). Switching only `loop_dx_cooling` to True flips the
winner to `PVAV with gas boiler reheat` at 9.50.

This is not a sixth thing to patch. It is the same defect as #214 and #220
— a fact the scorer needs is not in the signature — found by asking the
scorer about a system the campus fixtures do not contain. The CLAUDE.md
memory "the suite has shapes it cannot see" is exactly this: every one of
the ~35 tests in `tests/stock/test_identify.py` is a campus shape.

Note also `hvac.py:86-88`: the collapse key is the 14 descriptive keys, so a
chilled-water VAV and a DX VAV with the same fuels collapse into ONE group in
the recipe and are built as one system over the union of their zones.

## 3. The three sub-questions

### 3a. Are fixed catalogue ROWS the right unit for a recipe? No.

A row is a fixed bundle: look at any `vav_reheat` row
(`systems.json`: `heating_coil_type`, `baseboard_type`, `chiller_type`,
`cooling_type`, `boiler_fuel`, `needs_erv` + 11 `erv_*` fields). The 110
rows are the Cartesian product of a handful of axes, enumerated by hand and
then PRUNED: the 21 `psz` rows are {gas, electric, ashp+gas, ashp+electric}
× {HW baseboard, electric baseboard} × {with exhaust, without} plus five
CBECS shapes; the 16 `fan_coils` rows are {FPFC, TPFC} × {DX, hydronic MAU}
× {4 chiller types}. The `vav_reheat` family has 21 rows and NONE with a
gas furnace coil, because the NECB generator never needed one
(`identify.py:413-420` records discovering this the hard way).

That is fine for the catalogue's ORIGINAL consumer. `btap.codes` does not
search the catalogue at all: it computes a Table 8.4.4.7.-A system number
and an energy type, then looks up `definitions[str(system)][energy_type]`
→ `variant['name']` (`btap/codes/necb/hvac/reference.py:912-914`). That is
a deterministic key into a small, adjudicated subset of rows. The rows ARE
the right unit there, because the Code prescribes bundles.

A building survey is the opposite case. A real building's HVAC is a POINT
in that product space that the catalogue may or may not have enumerated,
and #214 is what happens when it has not: the only row with hot-water
baseboards on a DX VAV also carried an HRV, so "baseboards and no HRV" had
no row, and two rows were added to close one case
(`PVAV ... and hot water baseboard`, `VAV chiller ... and hot water
baseboard`). Issue #217 then counts 55 of 77 OA-bearing rows that cannot
take an HRV and asks whether to double the catalogue. Every new axis the
survey needs — economizer type, OA fraction, per-zone vs shared, fan
pressure, DCV, exhaust — multiplies the row count or is silently dropped.
Rows cannot win that race; they are the wrong unit for an open-world input.

**What the recipe should carry instead** is the parameters themselves,
in exactly the vocabulary the builders already read from `self.config`:

```json
"hvac": {"systems": [{
  "zones": [...],                          // or a selector, see 5c
  "air_side":  {"kind": "vav", "cooling_coil": "chilled_water",
                "heating_coil": "hot_water", "reheat": "hot_water",
                "outdoor_air": true, "heat_recovery": null,
                "economizer": {"control_type": "FixedDryBulb",
                               "maximum_limit_drybulb_c": 19.0},
                "dcv": false, "per_zone": false, "loops": 2},
  "zone_side": {"baseboard": null, "unit": null},
  "plants":    {"hot_water": {"source": "boiler", "fuel": "NaturalGas"},
                "chilled_water": {"source": "water_cooled",
                                  "chiller_type": "Scroll"}}
}]}
```

Every field above is something `characterize` already measures or could
measure in one accessor, and every field is something a builder already
takes as a config key (`heating_coil_type`, `baseboard_type`, `reheat`,
`ventilation`, `per_zone`, `needs_erv`, `chiller_type`, `chw_source`,
`hw_source`, `boiler_fuel` — see the key census in `systems.json` and
`furnace.py:233-236`, `mau_ptac.py:28-30`, `zone_terminal.py:25-27`,
`fan_coils.py:43-47`). The catalogue row then becomes what it really is:
a NAMED PRESET of such a spec. `catalog.resolve(name)` returns a spec; a
recipe may name one or spell one out; the builder cannot tell the
difference. That keeps `build_system(name)` and every consumer of it intact.

### 3b. Is a flat fact dictionary the right intermediate? No, and the
flatness is the specific thing that has hurt.

`_base_group` (`classify.py:644-678`) is one namespace for three
different objects: the LOOP (its coil media, DX/hydronic cooling, OA
method, HRV), the ZONE EQUIPMENT (`zonal_units`, zonal fuels), and the
PLANT (fuels resolved through it). The scorer's own comments say this is
what blocked the composite fix: "the catalogue keeps loop-side and
zone-side coils in one namespace ... so a merged row cannot say WHICH SIDE
a coil is on" (`identify.py:535-549`). `cooled` is a union of loop and
zonal cooling (`:499-505`); `heating_energy_types` is a union of loop,
terminal and zonal fuels (`_scan_heating_component` is called from the
supply walk at `:471`, the terminal walk at `:1370`, and the zonal merge via
`_zonal_fuels` at `:1418`); `cooling_energy_types` likewise. Then `_DESCRIPTIVE` projects
that union down to 14 keys and `hvac.py:86-88` uses the projection as the
IDENTITY of the group. Two systems that differ in any un-projected way are
the same group.

The intermediate the recipe needs is the spec in 3a: a loop record, a
zone-equipment record and plant references, **as separate sub-objects**.
`characterize` already walks those three things separately
(`_air_loop_group` → `coils.supply_components`; `_terminal_facts`;
`_merge_zonal_equipment`); it only merges them at the end because its
original consumer — Table 8.4.4.7.-A — asks union questions ("is the block
heated", "what energy types"). Keep that flattening as a VIEW for
`btap.codes` and stop using it as the recipe's source.

### 3c. Is fuzzy scoring the right selection mechanism? No — and this is
the one I would state most strongly.

Fuzzy scoring is the right tool when the target is a latent category and
the evidence is noisy. Neither holds here. The evidence is an OSM: every
coil, controller and plant is a typed object the SDK reads exactly. The
target is a buildable description, and the builder takes a description.
There is no inference step in the problem; the scorer exists only because
the output was constrained to be a catalogue NAME (`reader.py:506`) and
the catalogue does not contain every building.

Three concrete consequences of scoring where you could compose:

1. **Nearest row ≠ faithful row.** The score rewards agreement and
   penalises disagreement, but the LOSS of building the wrong row is not
   symmetric or additive: dropping a chilled-water plant (section 2) is not
   "-2.5 worse" than adding an HRV. The asymmetric hand weights at
   `identify.py:575-598` are an attempt to encode loss by hand; they will
   need re-tuning for every new fact.
2. **Hard constraints cannot be expressed.** "This group has no air loop"
   (`air_loops: []`, #220) is not a -N penalty; it is a filter. The scorer
   has no filter stage, by design (`identify.py:246-249`: "a disagreement
   does NOT disqualify"). That design is defensible for a *guess*; it is
   wrong for a *measurement*.
3. **The ranking is unfalsifiable except case-by-case.** Nothing says what
   a score of 6.25 means. There is no held-out set, and the fixtures that
   calibrated the weights are the campus archetypes the scorer is applied
   to. The self-consistency run in section 4 is the first measurement
   against anything else.

Where fuzzy matching DOES belong: mapping a described spec to a catalogue
PRESET for a human-readable label ("this is approximately 'PVAV with gas
boiler reheat'"), as an annotation. Never as the thing that is built.

## 4. The measurement: can the scorer recover the catalogue's own rows?

Script: `self_consistency.py` beside this file; raw results in
`self_consistency.json`, log in `self_consistency.log`. Method, copied
from `tests/necb/test_hvac_reference_selection_matrix.py:130-136`'s
"scrubbed" pass: for each of the 110 rows, `build_system` it on the
5-zone fixture, rename every air and plant loop so `_recognize_gem_name`
cannot resolve it, run `hvac_section` (the writer) and
`identify_candidates` (the scorer) on each resulting group, and ask
whether the row that built the model is the top candidate. This is the
easiest possible case for the scorer: the vocabulary is the catalogue's
own, every fact `characterize` can read is present, and the answer is
known.

```
110 rows, 0 build errors
top candidate is the building row:   18   (16%)
building row somewhere in the top 5: 40   (36%)
building row NOT in the top 5:       70   (64%)

by family (top-1 / rows):
  psz 7/21   vav_reheat 5/21   fan_coils 0/16   composite 0/12   mau_ptac 0/9
  furnace 1/4   zone_terminal 1/4   baseboards 2/3   unit_heaters 2/3
  every other family 0/n (chilled_beams, crah, doas, doas_pthp, dual_duct,
  ecm_* (7), evap_cooler, vrf, wshp, zone_ervs)

of the 92 misses: 23 pick another row of the SAME family (chiller type,
"with exhaust", baseboard medium — axes the facts do not carry), and
60 pick a DIFFERENT FAMILY:
  composite -> psz 12      vav_reheat -> furnace 9     fan_coils -> psz 8
  fan_coils -> furnace 8   mau_ptac -> psz 5           zone_terminal -> mau_ptac 3
  ecm_* -> psz/furnace 7   doas -> psz 1   doas_pthp -> psz 1   crah -> furnace 1
  wshp -> composite 1      vrf -> composite 1          evap_cooler -> furnace 1
```

What the cross-family substitutions mean physically:

- all eight `MZ BU RTU Hot Water ... Chiller` rows (chilled-water VAV with
  hot-water reheat) → `Shared hot water air handler with water reheat`,
  a `cooling: False` row: **the chiller plant is deleted**. This is
  section 2, now observed on a model rather than a hand-written dict.
- all sixteen `fan_coils` rows → `PSZ-AC with gas coil` or `Forced air
  furnace`: the DOAS/MAU loop is kept as a PSZ or furnace and **the fan
  coils and the chiller are dropped**. The `fan_coil` zonal units are seen
  (`classify.py:1386`) but `_ZONAL_FAMILY` maps only `unit_heater`, `ptac`
  and `baseboard` (`identify.py:74-75`), so they earn nothing.
- all nine `mau_ptac` rows → a `PSZ RTU` row: **the PTACs are dropped**
  and a DX rooftop takes their cooling.
- all twelve `composite` rows → `psz`: every DOAS+{fan coil, VRF, WSHP}
  building becomes a packaged rooftop. The layering credit at
  `identify.py:550-573` never outscores the PSZ field credits.
- `PTAC with baseboard gas boiler` (no air loop) → `PSZ RTU ASHP ... with
  Electric Reheat` at 7.0, a heat-pump rooftop with reheat terminals:
  this is #220 reproduced on the catalogue's own row, and the winning
  substitute is worse than the one #220 reports.
- `Dual-duct VAV` → no candidate at all (section 5i).

I want to be fair about the 23 same-family misses: picking
`Centrifugal` over `Scroll`, or "with exhaust" over without, is a
catalogue-granularity tie that the facts cannot break and arguably should
not. Those are not scorer failures. The 60 cross-family ones are, and 60
of 110 on the scorer's own vocabulary is the number to put beside
"~21% below the source on `Office_pre-1960`" in `btap/stock/CLAUDE.md`.

The experiment also shows why the campus-fixture tests pass: the 18
recovered rows are precisely the shapes the Gagetown archetypes contain
(PSZ with gas coil, baseboards, unit heaters, one furnace, a few VAVs).
The scorer was fitted to those and it fits them.

## 5. Things not on the list of four

**5a. A fifth defect** — section 2: a chilled-water VAV is rebuilt as a
heating-only air handler. Cause at `btap/stock/hvac.py:35-47` and
`btap/stock/identify.py:327-328`.

**5b. The economizer reader applies ONE loop's settings to EVERY loop.**
The writer records a row per air loop (`controls.py:119-140`,
`by_air_loop`). The reader takes `rows[0]` (`reader.py:284-285`) and calls
`Ventilation.set_economizer_in_model(...)` (`:319-321`), which sets every
controller in the model (`ventilation.py:227-247`). DCV likewise: if ANY
row has `dcv_enabled`, every loop gets DCV (`reader.py:325-328`). A
building with an economizer on its office RTU and none on its shop MAU is
rebuilt with economizers everywhere. This is the same shape as #219 one
level up: the recipe carries per-loop data and the reader has no per-loop
binding to apply it to. In the spec of 3a the economizer lives inside the
system record, so it is applied to the loop it describes.

**5c. The HVAC path is not portable at all today**, as you verified
(`reader.py:498-499` binds by exact zone name; `:500-504` refuses
otherwise). The CLAUDE.md for `btap.stock` says a recipe is "generic, not
exhaustive" so it "can be applied to different geometry". Loads and
envelope are; HVAC is keyed to the source's zone names. Nothing in the
recipe says WHICH zones of a new geometry should get which system. The
missing piece is a zone SELECTOR — by space type, by storey, by
exterior/interior, by "everything not otherwise claimed" — and that is a
design question the row-vs-parameter question does not answer. It needs
deciding before the HVAC recipe can claim portability; I would decide it
alongside 3a rather than after, because the selector is also what fixes
5d.

**5d. Loop multiplicity is recorded and then thrown away.** `hvac.py:105`
records `zone_groups: len(members)` — how many source loops collapsed
into this description — and `reader.py` never reads it (grep: the only
`zone_groups` reference at `:587` is the list of groups). So three
`Forced air furnace` loops over three zones become one shared loop over
three zones if the chosen row is `per_zone: False`, and one shared loop
over three zones becomes three loops if it is `per_zone: True`. Issue
#220 calls the merge "inherent to a recipe being an abstraction"; it is
not — `per_zone` and a loop count are two fields.

**5e. Heat recovery is a field that only one builder honours** (#217,
already filed). I agree with that issue's remedy — insert at
`base_system.build_oa_system` (`base_system.py:148-154`) driven by
`needs_erv` — and note that it is only workable if `needs_erv` can reach
the builder WITHOUT a row, i.e. through the `config=` override the reader
does not pass (`builder.py:137-138`). That is 3a again.

**5f. The identifier's tests are all one fixture family.**
`tests/stock/test_identify.py` has ~35 tests; every fact dict in it is
hand-written to a Gagetown shape, and the `test_the_RANKING_FLIPS...` /
`test_CONTROL_...` pairs mutate the SCORER's inputs, not the catalogue or
the model. There is no test that builds a catalogue system, scrubs it, and
asks the scorer to find it — which is the one test that would have shown
section 4's number on day one. (`tests/necb/test_hvac_reference_selection_
matrix.py:130-136` already does exactly that scrub for `btap.codes`.)

**5g. `family_guess` is a fourth classification vocabulary.**
`_structural_family_guess` (`classify.py:1574-1596`) emits
`multizone_vav`, `central_doas_or_cv`, `packaged_single_zone`,
`zonal_heat_cool` ...; `FAMILY_CANDIDATES` (`identify.py:39-69`) maps
those onto builder families; `_ZONAL_FAMILY` and `_ZONAL_UNIT_FAMILY`
(`:74-99`) map zone-equipment kinds onto families; and the catalogue has
its own `family`. Four partially overlapping taxonomies, each with a
comment explaining a case where the mapping between two of them was
wrong (`:47-53`, `:77-87`). A spec with `air_side.kind` and
`zone_side.unit` as first-class fields needs none of these maps.

**5i. Four of the ten `family_guess` values can never produce a candidate.**
`_structural_family_guess` (`classify.py:1574-1596`) emits `chilled_beam`,
`dual_duct_vav`, `multizone_cv` and `zonal_cooling_only`; none is a key of
`FAMILY_CANDIDATES` (`identify.py:39-69`), so `identify_candidates` returns
`[]` (`:641-643`) and the reader refuses the group with "no candidate"
(`reader.py:491-496`). The catalogue HAS a dual-duct row and two
chilled-beam rows; the experiment in section 4 shows the dual-duct build
coming back with an empty candidate list. A spec-based reader has no
such map to forget.

**5j. The baseboard MEDIUM is not a fact.** `ZONAL` (`classify.py:1379-1397`)
records `kind: 'baseboard'` for electric and hot-water baseboards alike;
the medium goes only into the UNION `heating_energy_types`
(`:1418`), where it is indistinguishable from the loop coil's fuel. So a
gas-coil PSZ with ELECTRIC baseboards reads `heat = {gas, electric}`, and
the scorer credits a hot-water-baseboard row for "hot-water baseboard with
gas heating" (`identify.py:291-293`) and `needs_boiler` (`:492-494`). That
is why 'PSZ RTU Gas and DX Coils and Electric Baseboard' comes back as its
hot-water sibling in section 4, with a boiler the building does not have.

**5h. The writer's door bug (defect 1) is a different class from 2-5**
and is now fixed correctly at `envelope.py:233-258` (bucket by
`isOpaque()`, not by `subSurfaceType`). I have no architectural objection
to the envelope section; its aggregate-with-spread design is sound and the
HVAC section should look more like it, not less.

## 6. What breaks under the proposal, and what it costs

**`btap.codes` and the D-58 golden: nothing**, provided the catalogue keeps
its names and the builders keep reading `self.config`. The reference path
never calls `identify`; it resolves `variant['name']` from its own
per-edition definitions (`reference.py:912-914`) and calls
`modeling.build_system(reference, assignment.catalog_name, zones, ...)`
(`:1518`). If `catalog.resolve(name)` keeps returning the same dict, the
108-row sizing sweep, the adjudicated matrix, the canonical-name grammar
(`canonical.py`) and the catalogue report are untouched. The proposal
adds a second ENTRY — `build_system(model, spec_dict, zones)` or a
`compose(spec)` that returns a config dict — and leaves the first alone.

**What the builders need:** the ability to take every row field as a
parameter, which they mostly already do, plus a handful they do not:
`needs_erv` outside `vav_reheat` (#217), an economizer block, `per_zone`
on families that hard-code it, and "no outdoor air" on families that
always build it. That is incremental work inside `btap.modeling`, and it
is the SAME work #217 and #219 already ask for.

**What `btap.stock` loses:** `identify.py` (678 lines) as the path to a
built model, `_DESCRIPTIVE`, the four taxonomy maps, the collapse-by-
signature key, and most of `test_identify.py`. What replaces them is
smaller: a `describe(group) -> spec` in the writer that is a direct
projection of `characterize`'s per-loop / per-zone-equipment / per-plant
walks, and a `compose(spec) -> config` in the reader that validates the
spec against the builder vocabulary and refuses — by name, as the reader
already does for unresolved groups — any field combination no builder
can realise. Refusal becomes "no builder takes a gas-coil VAV with
chilled-water cooling", a true statement about the library, rather than
"family_guess is a guess", a statement about the scorer.

**What is genuinely lost:** the catalogue preset as a *label*. A recipe
spelled out as parameters is less legible than "PVAV with gas boiler
reheat". Keep `identify` as an annotator that names the closest preset
and reports the diff ("closest: PVAV with gas boiler reheat; differs:
no HRV, economizer FixedDryBulb 19 C"). That is what a scorer is good
for, and nothing is built from it.

**Cost estimate**, honestly rough: the writer-side `describe` is a
re-projection of data `characterize` already has — days. The reader-side
`compose` plus the builder parameter gaps is where the work is — the
`needs_erv` chokepoint and an economizer block are each small; `per_zone`
and `ventilation` across families is a sweep of 21 modules. Call it two
to three weeks for one person, and it retires three open issues (#217,
#219, #220) and the undiscovered ones of the same shape.

## 7. What I would do FIRST

Not the spec. First, the measurement that tells you how far the current
design is from working, so the rebuild can be judged against a number:

1. **Commit section 4's self-consistency script as a test**
   (`tests/stock/test_identify_recovers_the_catalogue.py`): build each
   catalogue row on the fixture, scrub the names, run
   `hvac_section` + `identify_candidates`, assert the building row is the
   top candidate. It will fail. Mark the failing rows as expected failures
   WITH the current count pinned, so the number can only go down. This is
   cheap (the script in the scratchpad already runs), it uses no new
   infrastructure, and it is the test 5f says is missing.

2. **Add `loop_hydronic_cooling` to `_DESCRIPTIVE`** and make
   `loop_cools` read either flag (`identify.py:327`). One-line fix for
   section 2, same shape as #214's fix, and it stops the next person from
   shipping a cooling-plant deletion while the real change is designed.

3. **Then write the spec schema** (3a) as a document with the builder
   vocabulary census beside it — which fields each of the 21 builders
   reads from `self.config` today — and get phylroy to rule on the zone
   selector (5c), because that decision shapes the recipe more than any
   other and no amount of scoring work touches it.

4. Only then: `describe` in the writer, `compose` in the reader, and the
   builder parameter sweep, in that order, each landing behind the
   self-consistency test from step 1 — whose pass count is the acceptance
   criterion.

I would NOT start by adding rows (#217's "double the catalogue" branch),
by adding more facts to `_DESCRIPTIVE`, or by re-tuning weights. Each of
those is a step further into the design this review says is the wrong
one.
