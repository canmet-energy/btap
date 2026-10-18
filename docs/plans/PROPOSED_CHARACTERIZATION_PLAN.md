# Report what the input gate accepted

**Status:** planned, 2026-10-18. Rewritten after phylroy corrected the framing:
a proposed model missing information NECB requires — an undeterminable storey
count, space types not named against the catalog — must WARN AND STOP, not
proceed. That gate already exists. This plan is about what the trail says once
it passes.

## The architecture is already right

**Required inputs are gated and fatal.** Verified by running, not reading.
Without the space-type on-ramp, a real archetype is refused before any
simulation, exit 3:

```
ERROR: the model was REJECTED before any simulation ran.
pre-flight FAILED: 17 space type(s) do not resolve against the NECB 2020
space-type catalog, so the reference buil…
  'Shop-Machinery-Hangar' [nil, nil] (1 space(s)) — untagged: run the loads
  'Office Category 1' [nil, nil] (13 space(s)) — untagged: run the loads
  … every offending type, its space count, and the fix
```

`btap/codes/necb/path.py#validate` runs three gates inside
`audit.with_building("input model")`, and `compliance.PreflightError` maps to
`EXIT["preflight"] = 3`:

- `pipeline._validate_input_model` — no spaces / zones / surfaces is fatal, and
  so is **no thermostat anywhere**. Its own comment names that as the dangerous
  case "because it RUNS: every zone free-floats, equipment sizes to nothing,
  and the determination is numerically valid and physically meaningless".
  Partial thermostat coverage warns, since storage and plenum zones
  legitimately float.
- The **storey gate**, `require_storeys=True`: fatal unless the count is
  declared on `Building`, derivable from `BuildingStorys` with above-grade
  spaces, or passed as `building={'storeys':}` — because Table 8.4.4.7.-A's
  System 3-vs-6 split depends on it and "the fallback would silently treat the
  building as ONE storey".
- `_validate_space_types` — every floor-area space type must resolve against
  the catalog BEFORE any transform, because the per-space-type transforms skip
  unmatched types silently, "so an unresolvable space type yields a reference
  identical to the proposed for exactly that space: the allowance is waived and
  the proposed is compared against itself. You cannot certify a building whose
  reference silently failed to build; fail here, loudly, with the full list".

That reasoning is the whole requirement, already implemented. **This plan adds
no gate and relaxes none.**

### Two corrections to the previous draft

The first version of this plan was written as a disclosure problem with a
disclosure-versus-verification question for phylroy or Sol to rule on. That
question is already settled by the architecture above: required inputs are
fatal, and what lies past the gate is disclosure. The tool does not check a
proposed assembly against a prescriptive maximum because Part 8's verdict is
the 8.4.1.2 energy comparison — but it does refuse to run without what it
needs. **The question is withdrawn.**

It also claimed the 17 untagged space types were a live gap. They are not: they
appear only because `--space-type` reassigns every space to one NECB type,
orphaning the model's own. A genuinely untagged model never reaches that code —
it is refused at the gate. And it claimed `storeys_source` was discarded into a
local; it is in the audit.

## What the trail actually says once the gate passes

Measured on `main` at `86dc55c3`:

```
input model loaded and structurally simulate-able        level=info  article=None
  {"spaces": 56, "thermal_zones": 55, "surfaces": 600,
   "storeys_source": "derived from BuildingStorys",
   "zones_with_thermostats": 55, "openstudio_version": "3.11.0"}

space-type pre-flight passed — every floor-area space type resolves
                                                          level=info  article=None
  {"floor_area_spaces_checked": 56, "code": "necb2020", "edition": "2020"}
```

So the trail records that the gates ran and what they counted. Four things it
does not record:

1. **Which NECB space type each space resolved TO.** Only counts exist:
   `spaces_assigned: 56`, `space_types_created: 1`. The gate proves every space
   type resolved; the trail never says to WHAT. For a reviewer this is the
   single most consequential omission, because the space type drives the LPD
   allowance, the loads and the SHW demand — the allowance the whole
   determination rests on.
2. **The storey COUNT as an accepted input.** The source is recorded
   (`"derived from BuildingStorys"`) but the number is not. `{'storeys': 4}`
   does appear, in `building info for selection` — attributed to the
   **reference building**, because it is emitted from
   `hvac/reference.py:1863` inside the reference's `with_building`.
3. **The envelope as modelled.** No conductance, U, SHGC or as-submitted FDWR
   for the proposed, although `exposed_walls` already returns the areas and the
   FDWR and the prescriptive pass already reads each existing construction to
   decide what to retarget.
4. **A citation.** Both gate entries carry `article=None` and `level=info`, so
   they sit outside the article trail the rest of the audit is organised by.

The consequence is measurable: two Hangar archetypes of different vintage —
different files, different envelopes — produce **353 audit entries each that
differ in exactly one**, and that one is a thermal-mass side effect.

## Phase 1 — attribute the accepted inputs to the input model

`hvac/classify.py` and `hvac/reference.py` already characterize the proposed —
31 `characterize` entries on the Hangar run, including the storey count — and
every one lands under `building: reference building` because of the enclosing
`with_building`. Decide per entry whether it states a fact about the input
model or a choice about the reference selection, and attribute accordingly.

No new measurement. This alone lets a reviewer see the accepted storey count
and the proposed's loop topology as properties of their submission.

Baseline movement: `building` is a top-level AuditLog field, so every
re-attributed entry moves. Verify the usual property — decision SETS unchanged
apart from the `building` value.

## Phase 2 — state what the gate accepted, per space type

Extend the two passing-gate entries from counts to contents:

- **the space-type resolution map**: each space type as named in the model, the
  NECB `[building_type, space_type]` it resolved to, and the floor area it
  covers. This is what makes the gate's pass auditable rather than asserted;
- **the accepted storey count and its source**, as an input-model fact;
- **thermostat coverage** as the fraction already computed.

Promote both entries from `info` to `decision` and cite them — the storey gate
to Table 8.4.4.7.-A, which is the requirement that makes the count load-bearing;
the space-type gate to the loads/LPD articles the resolution feeds. A fact the
determination depends on belongs in the article trail.

## Phase 3 — the envelope as modelled

One pass on the input model, before any transform, recording the proposed's
envelope the way the reference's is already recorded: opaque conductance by
surface class and boundary, fenestration U and SHGC, the as-submitted FDWR and
SRR, conditioned floor area, exposed wall and roof area, and the space
multipliers in effect.

Read from where the data already is (`exposed_walls`, `exposed_roofs`, the
constructions the prescriptive pass inspects) rather than recomputing. Values
and citations, no verdicts.

## Phase 4 — `report.json`

`report.json` carries `proposed: 0 keys` and `reference: 0 keys`. Add a
`characterization` block with the Phase 2 and 3 facts as data, so the HTML
report and downstream consumers read it without parsing the audit. The report
already renders `Reference building systems`; this is its counterpart.

## Phase 5 — the guard

**Two archetypes differing only in vintage must produce audits that differ.**
Today they differ in 1 of 353 entries. That property cannot hold while the gap
exists, which is what makes it a guard rather than a description.

Pair it with the inverse — the same model twice produces identical
characterization — so it cannot be satisfied by noise.

Add a gate regression too: a model whose space types do not resolve must still
exit 3 with every offending type named, and an undeterminable storey count must
still exit 3. Those behaviours are the reason this plan is small, and nothing
here may weaken them.

## What this plan deliberately does not do

- **No new gates, and no relaxed ones.** The three preflight gates stay fatal.
- **No verdicts on the proposed.** Part 8's verdict is the energy comparison;
  an assembly-by-assembly pass/fail is the prescriptive path's job.
- **No recomputation** where a measurement already exists.
- **No change to the determination.** `compliant`,
  `compliance_determination`, the conditional label and the exit codes are
  untouched; `test_the_exit_code_is_UNCHANGED_by_the_label` stays green.

## Verification

Each phase moves audit output and re-freezes on a clean tree in the same
change, asserting what #125 established: decision SETS and verdict fields
unchanged, movement confined to the entries the phase adds or re-attributes.
A characterization pass runs in every lane, so expect all 54 scenarios rather
than the 15 that #125 could scope to.

## Provenance

Finding 6 of the 56-run archetype sweep behind #125 (28 models × 2 editions),
reframed by phylroy on 2026-10-18. Gate behaviour verified by running an
untagged archetype to exit 3; trail contents measured on `main` at `86dc55c3`.
