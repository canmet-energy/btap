# NECB questions this tool does not decide — for an authority

**GENERATED** by `python/scripts/generate_ahj_referrals.py` from
`docs/NECB_AHJ_QUESTIONS.md`. Do not edit: edit the register and
regenerate. Every question, article, attribution and interim
behaviour below is the register's own text, so none of it can drift;
the framing sentences are this generator's.

The register holds every question in four statuses. Two of them need
no authority — `ruled` is settled, and `tool-gap` is a defect for us
to close, not a question for anyone else. This document is the other
two: **8 `referral`** entries, where the
Code's text does not decide the question, and
**2 `alternative-solution`**
entries, where it does decide and this tool does not meet it — which
an authority can accept only as an explicitly identified
non-conforming substitution.

Every entry below states what the tool does in the meantime, so a
reader can see what an answer would change rather than only what is
being asked.

---

## `referral`

### AHJ-2 — the annual-energy basis (2)(g) compares, and an irreconcilable Article 13 case

- **Editions:** necb2020, necb2025
- **Article:** 8.4.4.13 and Table 8.4.4.13; 8.4.5.13 and its table; with 8.4.x.9.(5). **Status: `referral`** — the acceptable-solution text does not decide this question. **NARROWED by Sol's `126`.** Article 13 and Article 9 operate CONCURRENTLY — Article 13.(2)(f) bases terminal and auxiliary capacity on the peak load *and* the requirements of Subsections 8.4.1, 8.4.2 and 8.4.4/8.4.5, and Article 13 nowhere says Article 9 ceases to apply. So the referral is not "which article wins". Two independent live branches remain: the ANNUAL-ENERGY BASIS, because 13.(2)(g) says "largest annual energy use" and a 33% share without saying whether the comparison is source/input energy or delivered heat and Division A defines consumption only at the whole-building aggregate; and an actual IRRECONCILABLE case where Article 13.(2)'s mandated capacities cannot satisfy (5)'s ratio. **The 33% proviso does not authorise a structural single-fuel fallback.**
- **Makes a run conditional:** yes, where the (2)(g) comparison is actually made

**The question.** 8.4.x.7.(4) sends heat-pump thermal blocks to Article 13
for the reference system type. Article 13 controls the ASHP topology, its
capacity and operating limits, the terminal/auxiliary capacity, and the
terminal/auxiliary energy-type election in (2)(g). Clause 13.(2)(f) expressly
incorporates Subsections 8.4.1, 8.4.2 and 8.4.4/8.4.5. Sol ruled on fetched
text that there is NO wholesale supersession and the two operate
concurrently — but whether an irreconcilable capacity-allocation case is
governed by Article 13's specific prescriptions or by (5) still needs an
authority where the two cannot both be satisfied.

**Established by.** Sol `119`, `120`, narrowing his own earlier "expressly
unresolved".

**EXTENDED 2026-10-07 to cover D-52's own assumptions**, which Sol's `122`
audit identified. Clause (2)(g) says "largest annual energy use" and does not
define the energy BASIS; D-52 reads it as delivered heat. Nor does it supply a
fallback: D-52 uses a structural fuel proxy when the heat-pump share is at or
below the 33% proviso or when annual data are absent. Both are local choices
the article does not make.

**What the tool does meanwhile.** The (5) disclosure runs on the heat-pump
path as well as the structural one, and says the allocation is NOT VERIFIED.
It does not claim the auxiliary election eliminates electric reference
heating, which was a false statement it used to make. The (2)(g) election
itself proceeds on delivered heat, audited, and falls back to the structural
proxy with its own audit entry — so the choice is visible per run, and it
SETS THE RUN CONDITIONAL wherever the (2)(g) comparison is actually made. It
does not where there is no annual data to compare, which is a mode limitation
rather than a question an authority can settle.

### AHJ-3 — whether 8.4.4.9.(6)(d) permits more than one boiler

- **Editions:** necb2020, necb2025
- **Article:** 8.4.4.9.(6)(d); 8.4.5.9.(6)(d). **Status: `referral`** — the acceptable-solution text does not decide this question.
- **Makes a run conditional:** yes, where a hydronic plant carries both fuels

**The question.** (6)(b) says "one single-stage boiler" and (6)(c) says "two
boilers of equal capacity"; (6)(d) says only "a boiler that is fully
modulating". Sol searched for a singular/plural interpretation rule and an
Appendix A note and found neither, so whether additional boilers are
forbidden above 352 kW is not established by the text.

**Established by.** Sol `119` section C, correcting his own earlier
"conflict across every band" as too categorical.

**What the tool does meanwhile.** The (6) coverage gap states that the
applicable subclause is not established at selection time and claims none.

### AHJ-10 — how corner thermal blocks are grouped

- **Editions:** necb2020, necb2025
- **Article:** Table 8.4.x.7.-B, Note (3). **Status: `referral`** — the acceptable-solution text does not decide this question.
- **Makes a run conditional:** yes, on a corner block above four storeys

**The question.** The note says only that blocks are "grouped together based
on facade orientation". D-18 assigns a corner block by largest exterior-wall
area, with a north/east/south/west tie-break. Neither the metric nor the
tie-break is in the text.

**Established by.** Sol `122`, decision-log audit.

**What the tool does meanwhile.** It applies D-18's rule — largest exterior-wall
area with an N/E/S/W tie-break — and **the choice IS audited**, since the
metadata handoff landed. `VAVReheat` records structured grouping evidence
(per external zone: the exterior wall area in each compass bin, the elected
facade, the tie-break rule) and `btap.codes` emits the entry citing
Table 8.4.x.7.-B Note (3) with `ahj='AHJ-10'`.

This entry said for one round that the choice was NOT audited, which was true
when Sol wrote `127` and false once the handoff shipped. Fable's `131` F4 caught
the stale sentence. Before the handoff a reviewer could not see which facade a
corner block was given; now the corner block's identity, its facade areas and
the elected facade are all in the audit.

### AHJ-11 — heating in a two-pipe System 5 reference

- **Editions:** necb2020, necb2025
- **Article:** 8.4.x.1.(5) with Table 8.4.x.7.-B, System 5. **Status: `referral`** — the acceptable-solution text does not decide this question. **Reachable in the Code, NOT YET EVALUABLE by this tool.** `129` claimed a coherent refrigerated model completed the full `necb2025` path. Sol WITHDREW that in `130`: the fixture it rested on established only that four EnergyPlus runs terminated, and a matched reference probe is thermally invalid despite completing — 8,760 cooling-unmet hours per zone, temperatures to 41.75 °C against a 4 °C setpoint. I had repeated the claim here, so it was false on this surface too. The truthful statement: the branch is normatively and physically reachable — `130` identifies the archetype, a medium-temperature cool-storage block with real refrigeration evaporators plus a low-limit unit heater — but **no coherent BTAP annual artifact has yet evaluated it.** Three separate tool gaps stand in the way: AHJ-18 (no plant-side changeover), AHJ-19 (refrigeration invisible to classification, teardown and end-use reporting) and AHJ-20 (a 7 °C comfort chilled-water loop that cannot condition a 2/4 °C cooler). None is part of this ambiguity. **Narrowed reachability** (`130`): a thermal block selected as refrigerated space that has GENUINE SPACE-HEATING equipment in addition to its refrigeration cooling. A cooling-only freezer or cooler does not raise AHJ-11.
- **Makes a run conditional:** yes, where a heated block is assigned System 5

**The question.** A genuine internal tension in the Code, not just in our
reading: sentence (5) requires identical heating presence between proposed and
reference, while the table's System 5 row says heating "None". D-39 retains
heating when the proposed block is heated.

**Established by.** Sol `122`, who called it a genuine internal tension.

**What the tool does meanwhile.** It follows (5) and retains the heating,
audited against both the sentence and the table row.

### AHJ-12 — "where present" humidification

- **Editions:** necb2020, necb2025
- **Article:** Table 8.4.x.7.-B, Note (1). **Status: `referral`** — the acceptable-solution text does not decide this question. **REFRAMED by Sol's `126`.** Note (1) clearly governs the energy SOURCE once humidification is present in the reference; it does not say whether reference humidification is present at all. That silence is the live question, not the source rule. Reachable where a proposed thermal block has humidification and the selected reference topology does not independently establish presence.
- **Makes a run conditional:** yes, on a presence CHOICE — not where the topology settles it

**The question.** D-55 reads "where present" as requiring reference
humidification wherever the PROPOSED has it. Sol reads the note as fixing the
energy source only for humidification already present in the REFERENCE — a
materially different scope.

**Established by.** Sol `122`.

**What the tool does meanwhile.** It applies D-55's reading, which adds
reference humidification the other reading would not.

### AHJ-14 — which part-load class a reference boiler or furnace takes

- **Editions:** necb2020, necb2025
- **Article:** 8.4.x.2/.3 and Tables 5.2.12.1.-N/-O. **Status: `referral`** — the acceptable-solution text does not decide this question. **NARROWED by Sol's `126`.** Only equipment for which NO provision elects a curve class. A purchased boiler is explicitly modulating under Article 6, and an ordinary boiler above 352 kW is explicitly modulating too — neither is a referral. What remains: an ordinary non-purchased fuel-fired boiler at or below 352 kW required by 9.(6)(b) or (c), where condensing versus non-condensing is unresolved; or a fuel-fired furnace where no provision identifies its Part 8 curve class, since 9.(7)'s stage count does not decide atmospheric versus condensing. Electric equipment is not conditioned.
- **Makes a run conditional:** yes, where the row's own default elected the class

**The question.** The Code supplies multiple part-load classes and the
efficiency tables do not select one for the reference. D-89 assumes ordinary
boilers non-condensing and furnaces atmospheric, from LEGACY PRECEDENT rather
than from the text — and the pinned gem has already been caught shipping the
non-condensing curve on every boiler row, so the precedent is weak evidence.

**Established by.** Sol `122`, who added one caution: keep the
purchased-energy case separate, because 8.4.x.6 explicitly specifies a
MODULATING boiler, so there the Code does elect.

**What the tool does meanwhile.** It applies D-89's classes, and the purchased
route separately applies the modulating class the article names (D-89's own
scope note).

### AHJ-15 — whether (3) governs dispatch priority at all

- **Editions:** necb2020, necb2025
- **Article:** 8.4.x.9.(3) with 8.4.2.10.(2). **Status: `referral`** — the acceptable-solution text does not decide this question. **NARROWED by Sol's `126`.** Only where Article 9.(5)(b) does not already prescribe the proposed multi-energy priority — where it does, the priority is carried over rather than chosen. Reachable where the reference selection requires BOTH secondary-system heating and terminal heating under 9.(3), both with non-zero capacity serving overlapping demand: concretely the System 3/4 furnace-plus-baseboard topology under D-91's current scope. A shared unit needs its own analysis and must not silently inherit this predicate.
- **Makes a run conditional:** yes, on the System 3/4 branch where (5)(b) does not prescribe it

**The question.** Sentence (3) specifies terminal and plant CAPACITY, not an
annual dispatch sequence. D-91 selects air-terminal-first dispatch. Other
viable sequences move reference energy by about **48 MWh per year**, which
makes this the largest single unreferred assumption the audit found.

**Established by.** Sol `122`. D-91 remains the interim project ruling.

**What the tool does meanwhile.** It dispatches air-terminal-first per D-91
and audits it. The magnitude is why this entry exists rather than sitting in
the decision log alone.

### AHJ-16 — N:1 system correspondence for hydronic pumps

- **Editions:** necb2020, necb2025
- **Article:** 8.4.x.14 and its Appendix A note. **Status: `referral`** — the acceptable-solution text does not decide this question.
- **Makes a run conditional:** yes, on an in-scope transfer decline

**The question.** The note explains multiple pumps WITHIN one proposed
system. It does not address several proposed hydronic systems corresponding to
one grouped reference system, nor the case where no unique correspondence
exists. D-93 and D-97 decline in those cases and retain a simulator default.

**Established by.** Sol `122`, as one combined referral for both decisions.

**What the tool does meanwhile.** It DECLINES rather than guessing, emitting an
unresolved warning per affected loop and leaving the simulator default in
place. That is NOT a conservative bound, which this entry previously
claimed: D-97's runtime warning and Sol's `126` both say the retained
default may bias the reference in EITHER direction. Declining to guess is
defensible; calling the result conservative was not.

---

## `alternative-solution`

### AHJ-1 — a single-fuel reference is a NON-CONFORMING substitution

- **Editions:** necb2020, necb2025
- **Article:** 8.4.4.9.(5) with 8.4.4.9.(6); 8.4.5.9.(5) with 8.4.5.9.(6). **The requirement, and why we do not meet it.** Sentence (5)(a) requires the reference heating capacities to match the ratio of the proposed building's capacity allocation per energy type, and (5)(b) requires the proposed operating schedule and priority of use. Sentence (6) independently bands the reference hydronic plant's boiler count: (6)(b) "one single-stage boiler" at or below 176 kW, (6)(c) "two boilers of equal capacity" or one two-staged boiler to 352 kW, (6)(d) "a boiler that is fully modulating" above. Every simulation boiler object carries ONE fixed fuel. The acceptable-solution text does not say how a two-fuel ratio is to be represented inside those cardinality constraints, and Sol confirmed on fetched normative text that (6) nowhere says it replaces (5), nor (5) that it overrides (6).
- **Makes a run conditional:** yes — `compliance_determination: conditional`

**The question.** Sentence (5)(a) requires the reference heating capacities
to match the ratio of the proposed building's capacity allocation per energy
type, and (5)(b) requires the proposed operating schedule and priority of
use. Sentence (6) independently bands the reference hydronic plant's boiler
count: (6)(b) "one single-stage boiler" at or below 176 kW, (6)(c) "two
boilers of equal capacity" or one two-staged boiler to 352 kW, (6)(d) "a
boiler that is fully modulating" above. Every simulation boiler object
carries ONE fixed fuel. The acceptable-solution text does not say how a
two-fuel ratio is to be represented inside those cardinality constraints, and
Sol confirmed on fetched normative text that (6) nowhere says it replaces (5),
nor (5) that it overrides (6).

**Established by.** Sol `110`, `112`, `119`, `120`; Fable `117`, `118`. Sol
fetched both editions through the codes MCP; Fable reproduced the
implementation's behaviour with code.

**What the tool does meanwhile.** It elects ONE energy type for the reference
SELECTION and computes no capacity ratio, so it satisfies neither clause of
(5). What the reference's FINAL equipment carries is a separate question this
tool does not establish — the selected variant may REPLACE the proposed plant
with a newly built one of the elected variant, tear it down and not rebuild it
where the variant needs no boiler, or stage it by role blind to fuel. It says
so: an UNRESOLVED audit warning per serving system, `8.4.x.9.(5)` held at
`not_implemented`, and the run's determination set to `conditional` naming
this question.

**`adopted` was removed from this list on 2026-10-09**, and the removal is a
finding rather than an edit. An AHJ-1-cited choice is a block whose heating was
collapsed to ONE energy type, and such a block is always an `action == "build"`
assignment: `_finalize` returns before the election and this disclosure for a
`copy_proposed` block, so a retained block raises no AHJ-1 question at all. The
only measured adoption was an all-`copy_proposed` residential service with
ZERO AHJ-1 records, which Sol's `143` refused as evidence for this entry, and
after D-101's plant-ownership split a built block cannot reach the proposed
plant either. No conformance check exists that would let one. So `copy_proposed`
CAN retain a proposed plant — that statement stands on its own and is tested —
but it is not an outcome of the question this entry asks.

**Status: `alternative-solution`, not `referral`.** Sol's `122` corrected my
framing: (5)(a) says the capacities "shall match the ratio", so whether one
elected fuel may stand in is NOT an open reading — the text decides it, and
this tool does not comply. An authority can accept the comparison only as an
explicitly identified non-conforming modelling substitution. The runtime
condition says exactly that.

What remains a genuine `referral` is the narrower question in AHJ-3: how a
two-fuel ratio may be REPRESENTED on a hydronic plant given (6)'s cardinality
bands. That one the text does not resolve.

**D-90 folds in here.** Sol's `122`: the primary/secondary role assignment
that decides which fuel survives staging is part of this question, not a
separate one. Computing the allocation, recognising roles and verifying the
ratio remain tool-side work; only the irreconcilable equipment and cardinality
shapes are referrals.

**Not a candidate for a tool-side fix of the election.** Sol ruled that no
single-fuel basis — fossil-first cascade, capacity-dominant, lead-fuel or
annual-dominant — satisfies (5)(a). A capacity-dominant election was built,
measured and abandoned for that reason (`118`). Computing the ratio and
verifying it IS tool-side work and is not excused by this entry.

### AHJ-7 — three published chiller EIR_FT rows are arithmetically wrong

- **Editions:** necb2020, necb2025
- **Article:** Table 8.4.5.5.-C (NECB 2020); Table 8.4.6.5.-C (NECB 2025). **Status: `alternative-solution`** — the text DOES decide it and we do not comply. Sol's `126`: the printed coefficients are unambiguous, although defective, so using suspected corrected values DEPARTS from the published acceptable solution and needs approval when an affected row is used. It was previously filed as a `referral`, which was wrong — there is no ambiguity in the text, only an error in it. **The requirement, and why we do not meet it.** THE DEFECT IS IN THE PUBLISHED CODE, not in our extraction. Three electric-chiller EIR_FT rows fail the AHRI 550/590 rating-point normalization, which requires EIR_FT = 1.0 at 44 °F chilled water with 85 °F condenser water or 95 °F condenser air: | row | coefficient | printed | evaluates to | suspected correct | | --- | --- | --- | --- | --- | | Water-cooled Scroll | d | -0.0128136 | 0.018 | -0.00128136 | | Water-cooled Reciprocating | b | -0.0882156 | -2.49 | -0.00882156 | | Air-cooled Screw | a | 0.013545636 | 0.88 | 0.13545636 (approx; fit 1.005) | All three look like a single misplaced decimal place. A rating point of 0.018 means a chiller drawing under two per cent of its rated power, and -2.49 is not physically interpretable at all. The codes MCP flags this itself as a `known_issue`, says the rows are "transcribed faithfully from the printed NECB", states that "the defect is in the source publication, not this database", that it is identical in both editions, and advises: "Do not use the Water-cooled Scroll/Reciprocating or Air-cooled Screw EIR_FT rows without correction; verify each polynomial at its rating point before use." **Why an authority must weigh in.** Complying literally with the printed coefficient produces an absurd result; using the corrected coefficient departs from the text as published. Neither is a calculation a tool can be said to have got right, and the choice changes modelled chiller energy. A project relying on either needs its authority to accept which reading applies.
- **Makes a run conditional:** not yet — see the entry

**The question.** THE DEFECT IS IN THE PUBLISHED
CODE, not in our extraction.
Three electric-chiller EIR_FT rows fail the AHRI 550/590 rating-point
normalization, which requires EIR_FT = 1.0 at 44 °F chilled water with 85 °F
condenser water or 95 °F condenser air:

| row | coefficient | printed | evaluates to | suspected correct |
| --- | --- | --- | --- | --- |
| Water-cooled Scroll | d | -0.0128136 | 0.018 | -0.00128136 |
| Water-cooled Reciprocating | b | -0.0882156 | -2.49 | -0.00882156 |
| Air-cooled Screw | a | 0.013545636 | 0.88 | 0.13545636 (approx; fit 1.005) |

All three look like a single misplaced decimal place. A rating point of 0.018
means a chiller drawing under two per cent of its rated power, and -2.49 is
not physically interpretable at all. The codes MCP flags this itself as a
`known_issue`, says the rows are "transcribed faithfully from the printed
NECB", states that "the defect is in the source publication, not this
database", that it is identical in both editions, and advises: "Do not use the
Water-cooled Scroll/Reciprocating or Air-cooled Screw EIR_FT rows without
correction; verify each polynomial at its rating point before use."

**Why an authority must weigh in.** Complying literally with the printed
coefficient produces an absurd result; using the corrected coefficient departs
from the text as published. Neither is a calculation a tool can be said to
have got right, and the choice changes modelled chiller energy. A project
relying on either needs its authority to accept which reading applies.

**Established by.** The codes service's own errata
(`services/codes/docs/errata-necb-chiller-eir-ft.md`), surfaced in the
`known_issue` of the archived payload at
`necb2020/provenance/vintage_match/8.4.5.5.-C.result.json`. Recovered into
this register on 2026-10-07 after phylroy recalled that table errors had been
found in an earlier session; they were recorded in provenance and in the
vintage-match verification, but not as an AHJ-weighable question.

**What the tool does meanwhile.** It ships the CORRECTED values for two of the
three rows, and the manifest provenance records that it does so and why: "the
water-cooled Scroll and Reciprocating rows agree only after the codes
service's own published errata for those two rows ... so the misprint is the
printed source's and the shipped curve already carries the corrected value".
That is a documented deviation from the printed Code, which is the defensible
choice and still a deviation.

**VERIFIED 2026-10-07 by evaluating the shipped surfaces, not by reading the
provenance.** Every water-cooled EIR_FT curve hits the AHRI rating point
(44 °F leaving chilled water, 85 °F entering condenser water), in both
editions:

```
  WaterCooled_Reciprocating_EIRFT   0.9999    printed coefficient gives -2.49
  WaterCooled_Scroll_EIRFT          0.9983    printed coefficient gives  0.018
  WaterCooled_Screw_EIRFT           0.9964
  WaterCooled_Centrifugal_EIRFT     0.9953
```

So the corrections are genuinely in the product data, and the two rows the
erratum names would be unusable without them.

**The Air-cooled Screw row does not reach us, because no air-cooled chiller
curve is shipped at all.** That answers the erratum for this entry; the
absence itself is a separate `tool-gap` and is now **AHJ-17**, because one
entry cannot carry a referral and a tool gap under one status without making
the taxonomy untruthful (Sol, clearance review of be2118d).

**STILL OPEN, and phylroy's call.** The deviation sets no run conditional, so a
building with a water-cooled scroll or reciprocating chiller is modelled on
corrected coefficients with nothing in its report saying so. Same shape of
hole as AHJ-5.

---

## How a run says this out loud

Only `referral` and `alternative-solution` make a result
conditional. Where one applies to a final choice, the report carries
`compliance_determination: conditional` with a reason block naming
the approval required, one record per unique final choice, and the
exit code is deliberately unchanged. The CLI prints it inside the
verdict string and the HTML report badges it beside the pass/fail
badge, because the report is the artifact an authority reads.
