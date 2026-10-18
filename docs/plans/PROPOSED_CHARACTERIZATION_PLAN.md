# Characterizing the proposed building in the audit trail

**Status:** planned, 2026-10-18. Raised as "finding 6" of the archetype sweep
behind #125, deferred from that PR because it ADDS disclosure rather than
removing noise, and because its scope is a Code question as much as an
engineering one.

## The finding

An authority reading a run can fully audit **how the reference was built** and
cannot audit **what the tool understood the submitted building to be**.

Measured on `main` at `86dc55c3`, two Hangar archetypes of different vintage
(different SHA-256, different envelopes), both `--simulate none`:

```
Hangar pre-1960     353 entries   hash c9ccc0d4afa1
Hangar 1980-2004    353 entries   hash f1dda3a2cafe
entries that differ:  1 of 353
```

The single differing entry is a side effect, not a characterization:

```
[243] opaque assemblies rebuilt as lightweight light-frame
      pre-1960 : unique_assemblies: 4
      1980-2004: unique_assemblies: 3
```

Attribution across the trail:

| Attributed to | Entries |
|---|---|
| reference building | **279** |
| input model | 60 |
| proposed building | 2 |

And those 60 input-model entries are almost entirely *what the tool did* plus
coverage declarations — 17 "space type carries no spaces", 6 "NECB schedule
built", one each of "people set" / "lights set" / "ventilation outdoor air
set", "input model loaded and structurally simulate-able", and ~25 coverage
status lines. **Exactly one records a measured property of the submitted
building**, which is why it is also the only thing distinguishing two
different buildings.

For contrast, the reference side records every assembly with its value and its
table:

```
outdoors roofceiling  conductance 0.1594 W/m2K   Table 3.2.2.2.
outdoors wall         conductance 0.2759 W/m2K   Table 3.2.2.2.
door                  conductance 2.6552         Table 3.2.2.3.
window                SimpleGlazing U 1.9        Table 3.2.2.3.
ground wall           conductance 0.397 W/m2K    Table 3.2.3.1.
```

`report.json` carries `proposed: 0 keys` and `reference: 0 keys` with no
characterization block, on a sized run as well as an unsized one.

## Why it matters

A reviewer needs two things, and the tool answers one of them:

- *how was the reference built* — answered exhaustively, 156 distinct articles;
- *what did the tool take my building to be* — effectively unanswered.

The second is not academic. The sweep behind #125 found the tool can read a
proposed model as having **no internal loads at all** for some space types, and
until that PR it said so in a form that looked like 17 modelling gaps. A
reviewer who cannot see what was read cannot catch a misreading.

It also means two submissions with materially different envelopes produce
near-identical trails, so the trail cannot evidence which building it describes.

## What already exists

This is a REPORTING gap, not a computation gap. Most of the data is computed
and discarded:

- `btap/modeling/envelope/geometry.py#exposed_walls` returns
  `wall_area_m2`, `subsurface_area_m2` and the as-found `fdwr`;
- `#exposed_roofs` returns the roof census;
- `btap/codes/necb/envelope/climate.py#hdd18` already audits the HDD source;
- the prescriptive pass walks every surface and reads its EXISTING
  construction to decide what to retarget — the proposed's U-values pass
  through code that currently records only the reference's new value;
- `btap/modeling/hvac/classify.py` already emits a **`characterize`** step
  (31 entries on the Hangar run) with `plant loop classified`, `zone group
  characterized` and `proposed air loop carries demand` — but every entry
  lands under `building: reference building`, because it runs inside the
  reference's `audit.with_building` context.

So the step name, the vocabulary and most of the measurements are in place.
What is missing is a pass that states them about the INPUT model, attributed
to it.

## The scope question to settle FIRST

**How much of this is disclosure and how much is verification?**

Recording "the submitted wall is U-0.31 as modelled" is disclosure. Comparing
it against the prescriptive maximum and flagging it is a PRESCRIPTIVE CHECK,
which the Part 8 performance path deliberately does not perform — the
performance path's verdict is the 8.4.1.2 energy comparison, not an
assembly-by-assembly pass/fail.

This plan assumes **disclosure only**: record values, cite the article they
bear on, and emit no verdict. Entries are `decision` or `info`, never a
violation, and nothing reaches `compliant` or
`compliance_determination`.

That assumption needs phylroy's or Sol's ruling before Phase 2 is written,
because the opposite reading — that an AHJ-facing artifact should flag a
proposed assembly worse than prescriptive — is defensible and would change the
audit levels, the checklist classifier's input and possibly the determination.
Getting it wrong in the direction of verification would make the tool assert a
compliance opinion the Code does not ask it for.

## Phase 1 — attribute what already runs

`classify.py`'s `characterize` entries describe the PROPOSED's loops and zone
groups but are attributed to the reference, because of the enclosing
`with_building`. Decide per entry whether it describes the input model or the
reference selection, and attribute accordingly.

No new measurement. This alone makes a reader able to see the proposed's
system topology, and it is the cheapest correction of the asymmetry.

Expect baseline movement: `building` is a top-level AuditLog field, so every
re-attributed entry moves. Re-freeze accordingly, and verify the usual
property — decision SETS unchanged except for the `building` value itself.

## Phase 2 — a characterization pass on the input model

One pass, run once on the proposed before any transform, inside
`audit.with_building("input model")`, emitting one entry per fact:

- **Envelope, as modelled.** Opaque assembly conductance by surface class and
  boundary (wall/roof/floor × outdoors/ground), fenestration U and SHGC, the
  as-submitted FDWR and SRR. `exposed_walls` and `exposed_roofs` already
  return the areas and the FDWR; the conductances are read where the
  prescriptive pass reads them.
- **Geometry.** Conditioned floor area, above-grade storeys, exposed wall and
  roof area, and the space multipliers in effect — a multiplier of 36 on a
  28-storey record is a fact a reviewer must see.
- **Systems.** HVAC systems present by catalogue identity, SHW fuel, and
  whether a DOAS is present (`btap/modeling/CLAUDE.md` records that a
  user-authored DOAS graph can be malformed in ways EnergyPlus accepts
  silently, so its presence is worth stating).
- **Loads.** Which space types resolved to NECB records and which did not,
  with the affected floor area — the 17-warning case from #125, stated as a
  quantity rather than a count of tags.
- **Infiltration.** The space-type modelling infiltration actually applied,
  which is distinct from the envelope's 8.4.3.3 air-leakage rule and is
  already recorded per space type.

Each entry cites the article it bears on so it joins the existing trail rather
than sitting beside it, and carries its value in `value` with the measurement
in `inputs`, following the reference side's own convention.

## Phase 3 — a characterization block in `report.json`

`report.json` has `proposed: 0 keys`. Add a `characterization` block carrying
the Phase 2 facts as data, so the HTML report and any downstream consumer read
it without parsing the audit. The report already renders a
`Reference building systems` section; the proposed deserves its counterpart.

## Phase 4 — the vintage test

The property that makes this verifiable: **two archetypes that differ only in
vintage must produce audits that differ.** Today they differ in 1 of 353
entries. A test that freezes two vintages of one archetype and asserts their
characterization entries differ in the envelope facts is the regression guard,
and it is the one check that could not pass while the gap exists.

Pair it with the inverse — the same model run twice produces identical
characterization — so the test cannot be satisfied by noise.

## What this plan deliberately does not do

- **No verdicts on the proposed.** See the scope question. Values without
  pass/fail until that is ruled on.
- **No new computation where a measurement exists.** If `exposed_walls`
  already returns it, the pass reads it rather than recomputing.
- **No change to the determination.** `compliant`,
  `compliance_determination`, the conditional label and the exit code are
  untouched; `test_the_exit_code_is_UNCHANGED_by_the_label` stays green.
- **No prescriptive-path work.** The prescriptive path already reports
  per-assembly compliance; this is about the performance path's trail.

## Verification

Phases 1–3 move audit output, so each re-freezes on a clean tree in the same
change. The property to assert each time, as in #125: decision SETS and
verdict fields unchanged, with the movement confined to the entries the phase
adds or re-attributes.

Scope the freeze by what can actually move — #125's 15-of-54 scoping held up
under review because the changed sites were byte-equivalent in the unaffected
lanes. A characterization pass runs in every lane, so expect all 54.

## Provenance

Finding 6 of the 56-run archetype sweep behind #125 (28 models × 2 editions).
The other five findings were defects in what the trail SAID; this one is about
what it does not say. Evidence re-verified on `main` at `86dc55c3`.
