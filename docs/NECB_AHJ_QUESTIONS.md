# NECB interpretations referred to an authority having jurisdiction

**AUTHORED, not generated.** One entry per Code question this implementation
cannot answer from the acceptable-solution text. Each entry says what is
ambiguous, who established that, what the tool does in the meantime, and
where a reader meets it at runtime.

phylroy's standing direction (2026-10-07): where Claude, Sol and Fable cannot
reach a solution *after real effort*, the tool emits a conditional result
naming the AHJ approval required rather than stalling the work. Questions
needing deeper thought by the NECB committees go to the AHJ by this route.
This file is the register that direction assumed existed; it did not, and
these entries were recovered from `.reviews/` correspondence, which is
gitignored and therefore not a record.

A runtime condition is NOT a substitute for implementing a requirement that
*can* be implemented. An entry belongs here only when the acceptable-solution
text does not decide the question.

| id | article | status | surfaced at runtime |
| --- | --- | --- | --- |
| AHJ-1 | 8.4.4.9.(5) / 8.4.5.9.(5) with (6) | open | `compliance_determination: conditional` |
| AHJ-2 | 8.4.4.9.(5) vs 8.4.4.13 for a heat-pump group | narrowed, open | the (5) disclosure on an ASHP group |
| AHJ-3 | 8.4.4.9.(6)(d) boiler cardinality | open | the (6) coverage gap |
| AHJ-4 | 8.4.2.2.(5) backup-equipment exclusion | ruled, no referral needed | — |
| AHJ-5 | water-loop heat-pump source boiler as an "energy type" | open, unreferred | nothing yet |
| AHJ-6 | 8.4.4.9.(4) oil and propane to a gas reference | open | the (4) coverage gap |

---

## AHJ-1 — how a multi-energy capacity allocation may be REPRESENTED

**Article.** 8.4.4.9.(5) with 8.4.4.9.(6); 8.4.5.9.(5) with 8.4.5.9.(6).

**The ambiguity.** Sentence (5)(a) requires the reference heating capacities
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

**What the tool does meanwhile.** It elects ONE reference energy type, which
satisfies neither clause, and says so: an UNRESOLVED audit warning per
serving system, `8.4.x.9.(5)` held at `not_implemented`, and the run's
determination set to `conditional` naming this question.

**Not a candidate for a tool-side fix.** Sol ruled that no single-fuel basis —
fossil-first cascade, capacity-dominant, lead-fuel or annual-dominant —
satisfies (5)(a). A capacity-dominant election was built, measured and
abandoned for that reason (`118`).

## AHJ-2 — whether 8.4.4.13 displaces (5) for a heat-pump group

**Article.** 8.4.4.13 and Table 8.4.4.13; 8.4.5.13 and its table; with
8.4.x.9.(5).

**The ambiguity.** 8.4.x.7.(4) sends heat-pump thermal blocks to Article 13
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

**What the tool does meanwhile.** The (5) disclosure runs on the heat-pump
path as well as the structural one, and says the allocation is NOT VERIFIED.
It does not claim the auxiliary election eliminates electric reference
heating, which was a false statement it used to make.

## AHJ-3 — whether 8.4.4.9.(6)(d) permits more than one boiler

**Article.** 8.4.4.9.(6)(d); 8.4.5.9.(6)(d).

**The ambiguity.** (6)(b) says "one single-stage boiler" and (6)(c) says "two
boilers of equal capacity"; (6)(d) says only "a boiler that is fully
modulating". Sol searched for a singular/plural interpretation rule and an
Appendix A note and found neither, so whether additional boilers are
forbidden above 352 kW is not established by the text.

**Established by.** Sol `119` section C, correcting his own earlier
"conflict across every band" as too categorical.

**What the tool does meanwhile.** The (6) coverage gap states that the
applicable subclause is not established at selection time and claims none.

## AHJ-4 — the 8.4.2.2.(5) backup-equipment exclusion

**Article.** 8.4.2.2.(5); 8.4.2.2.(5) in the 2025 edition.

**RULED by Sol on fetched text. No referral needed.** Sol ruled on fetched text that the exclusion
requires controls ensuring the backup operates ONLY when the primary is not
operating, and that `SequentialLoad` does not establish that condition: it
permits the secondary to run while the primary is saturated. Device names,
supply order and the word "Secondary" are not qualifying controls. A project
with an explicit mutually exclusive interlock could qualify, but the modeller
must supply that control evidence. Recorded here because it was raised as a
possible referral and is not one.

## AHJ-5 — a water-loop heat pump's source boiler as an "energy type"

**Article.** 8.4.x.9.(5)'s trigger, "where more than one energy type is used
by the proposed building's heating system".

**The ambiguity.** In sample 09 `classify` types the `Heat Pump Loop` as
hot-water with NaturalGas, while every WSHP group's heating energy types read
`['Electricity']` alone. The proposed system therefore draws gas at the loop
boiler and electricity at the compressors, and whether the loop boiler is an
energy type "used by the heating system" for (5) is a scoping question the
text does not settle.

**Established by.** Fable `117` O2.

**What the tool does meanwhile.** NOTHING — no disclosure fires for that
shape, because the group's own fuel list is single-valued. This entry is
UNREFERRED: it has no runtime surface yet, and that is a gap in this register's
coverage rather than a decision.

## AHJ-6 — oil and propane rendered as a natural-gas reference

**Article.** 8.4.4.9.(4); 8.4.5.9.(4); with Division A's building-energy-target
definition.

**The ambiguity.** (4) requires the reference energy type to be modeled as
IDENTICAL to the proposed, and Division A requires the same energy SOURCES for
the same functions. The implementation maps `FuelOilNo2` and `PropaneGas` to
the gas catalog variant, so an oil- or propane-heated building is compared
against a natural-gas reference. Sol ruled the sources stay distinct and that
this is a catalog gap, not a Code reading — so unlike AHJ-1 this one IS
fixable tool-side by adding the catalog variants, and belongs here only until
that is done.

**Established by.** Sol `110`, confirmed against fetched text in `121`
blocker 2.

**What the tool does meanwhile.** 8.4.x.9.(4) is held at `partial` and the
collapse is stated in its coverage gap. It does NOT currently set the run's
determination to conditional, because the fix is implementation rather than
interpretation.
