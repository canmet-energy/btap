# NECB questions referred to an authority, and gaps recorded beside them

**AUTHORED, not generated.** One entry per Code question this implementation
cannot answer from the acceptable-solution text, plus the closed and
tool-side dispositions that were considered and rejected as referrals — kept
so the register shows its own reasoning rather than only its conclusions.

phylroy's standing direction (2026-10-07): where Claude, Sol and Fable cannot
reach a solution *after real effort*, the tool emits a conditional result
naming the AHJ approval required rather than stalling the work. Questions
needing deeper thought by the NECB committees go to the AHJ by this route.
This file is the register that direction assumed existed; it did not, and the
first entries were recovered from `.reviews/` correspondence, which is
gitignored and therefore not a record.

## What each status means

A `referral` is ONLY for a question the acceptable-solution text does not
decide. Three other statuses exist so that settled and fixable things cannot
sit in the active set and make it look larger than it is — Sol's `122`
blocker 4 found exactly that, with two of the first six entries violating the
contract this file had just stated:

| status | meaning | sets a run conditional? |
| --- | --- | --- |
| `referral` | the text does not decide it; an authority must | yes, where it is reachable |
| `alternative-solution` | the text DOES decide it and we do not comply; an authority can accept it only as an explicitly identified non-conforming substitution | yes |
| `ruled` | settled against normative text; no authority needed | no |
| `tool-gap` | implementable; a defect to close, NOT an interpretation | no |

## Which editions an entry affects

The `editions` column lists the CODE IDS an entry applies to, explicitly —
`necb2020`, `necb2025`, both of them comma-separated, or `unverified` where it
has not been checked per edition.

**It never says "both", and never a collective noun.** An authority reading
this has to know WHICH code their project is under, and a word like "both"
stops meaning anything the moment a third edition is registered — every entry
would silently read as covering an edition nobody checked it against. The code
id is this repository's one public selector, so it is what the column carries.
The vocabulary is `code` and `edition`; "vintage" is retired everywhere here.

A listed id is asserted only where it was ESTABLISHED, not assumed. For AHJ-1 to
AHJ-3 Sol fetched both editions and reported 8.4.4.9 and 8.4.5.9 word-for-word
identical in the governing sentences. For AHJ-7 the codes service states the
chiller defect is "identical in NECB 2020 (8.4.5.5-C) and 2025 (8.4.6.5-C)".
For AHJ-8 it gives per-edition counts, "140 A and 163 B marks per edition", and
both editions' shipped tables were inspected here. AHJ-9's vintage-match
verdict is `identical` for both.

**Adding an edition means revisiting this file.** A new code id does not
retroactively join any entry's list, and `unverified` is the correct value for
an entry nobody has checked against it. `test_ahj_register.py` validates every
listed id against the editions actually registered under
`python/btap/codes/necb/data/`, so a typo or a retired id fails rather than
quietly misinforming a reader.

AHJ-10 to AHJ-16 came from the decision-log audit and were `unverified` when
first written, because the decisions they derive from carried no edition
applicability of their own. **Sol's `126` edition-verified all of them against
both texts**, which is why their rows above now read `necb2020, necb2025`; the
sentence claiming they are still unverified survived that round and was caught
by Fable's `131` F4. One known asymmetry already matters — Sol
noted NECB 2025 has an exceptional-calculation route at 8.4.2.12 with no 2020
equivalent, which bears on how AHJ-1 could be remedied in one edition and not
the other.

**The decisions now carry the same field.** As of 2026-10-07 every
`docs/decisions/D-NN.md` carries `editions`, and `articles` is nested per code
id — because the same number can name a different requirement in each edition
(`8.4.5.9` is Heating System in NECB 2025 and Fuel-Fired Service Water Heater
in NECB 2020). 98 of 99 decisions hold an `unverified` key: establishing them
means reading each decision against each edition's text, which is open work.
The id grammar was exhausted at D-99 and is now `^D-\d+$`.

Calling a tool gap a referral would launder a defect as an ambiguity. Sol
listed twelve decisions in `122` that are tool or data gaps for exactly that
reason, including D-92's variable-speed reference pumps, which are a plain
nonconformity with 8.4.x.9.(6)(e).

| id | article | status | editions | sets a run conditional |
| --- | --- | --- | --- | --- |
| AHJ-1 | 8.4.x.9.(5)(a)/(b) | alternative-solution | necb2020, necb2025 | yes — `compliance_determination: conditional` |
| AHJ-2 | the annual-energy basis 8.4.x.13.(2)(g) compares | referral | necb2020, necb2025 | yes, where the (2)(g) comparison is actually made |
| AHJ-3 | 8.4.x.9.(6) cardinality vs a two-fuel ratio | referral | necb2020, necb2025 | yes, where a hydronic plant carries both fuels |
| AHJ-4 | 8.4.2.2.(5) backup exclusion | ruled | necb2020, necb2025 | no |
| AHJ-5 | WSHP source-loop boiler energy counts for (5) | ruled | necb2020, necb2025 | no — but see the PREDICATE DEFECT in the entry |
| AHJ-6 | 8.4.x.9.(4) no oil or propane catalog variant | tool-gap | necb2020, necb2025 | no |
| AHJ-7 | Table 8.4.5.5.-C / 8.4.6.5.-C chiller EIR_FT | alternative-solution | necb2020, necb2025 | not yet — see the entry |
| AHJ-8 | Table 4.2.1.6 Note (1) A/B control marks | tool-gap | necb2020, necb2025 | no |
| AHJ-9 | Table A-8.4.3.2.(1)-G and the '12' column heads | ruled | necb2020, necb2025 | no |
| AHJ-10 | Table 8.4.x.7.-B Note (3) corner-block grouping | referral | necb2020, necb2025 | yes, on a corner block above four storeys |
| AHJ-11 | 8.4.x.1.(5) vs Table 8.4.x.7.-B System 5 heating | referral | necb2020, necb2025 | yes, where a heated block is assigned System 5 |
| AHJ-12 | Table 8.4.x.7.-B Note (1) "where present" humidification | referral | necb2020, necb2025 | yes, on a presence CHOICE — not where the topology settles it |
| AHJ-13 | Table 5.2.12.1.-K Path A vs Path B | ruled | necb2020, necb2025 | no — Path B is express; the IPLV check is a tool gap |
| AHJ-14 | boiler/furnace part-load class selection | referral | necb2020, necb2025 | yes, where the row's own default elected the class |
| AHJ-15 | 8.4.x.9.(3) terminal-vs-plant dispatch priority | referral | necb2020, necb2025 | yes, on the System 3/4 branch where (5)(b) does not prescribe it |
| AHJ-16 | 8.4.x.14 N:1 system correspondence | referral | necb2020, necb2025 | yes, on an in-scope transfer decline |
| AHJ-17 | no air-cooled chiller curve is shipped | tool-gap | necb2020, necb2025 | no |
| AHJ-18 | the two-pipe fan-coil surrogate has no plant-side changeover | tool-gap | necb2020, necb2025 | no |
| AHJ-19 | real refrigeration is invisible to classification, teardown and end-use reporting | tool-gap | necb2020, necb2025 | no |
| AHJ-20 | System 5's chilled-water loop is a 7 °C comfort loop | tool-gap | necb2020, necb2025 | no |

---

## How often a run is conditional, measured

**69% of the frozen corpus — 25 of the 36 scenarios carrying an audit — would
return a CONDITIONAL determination if run annually.** Measured 2026-10-08 by
resolving every `ahj` citation in every frozen audit against this register's
own statuses. By id: AHJ-1 on 11 scenarios, AHJ-14 on 10, AHJ-15 on 10, AHJ-3
on 3, AHJ-16 on 1.

Before AHJ-14 and AHJ-15 were wired it was roughly a third. The jump is not a
regression: both questions were always live, and wiring them only made the
disclosure visible. Sol ruled in `128` that frequency is NOT a reason to
suppress a referral — the gap is common because the Code commonly requires
equipment without electing which of its published options that equipment takes.

**But the number is worth phylroy's attention, because it is a product fact
rather than a normative one.** AHJ-14 fires on every ordinary fuel-fired
boiler or furnace and AHJ-15 on every System 3/4 one-unit-per-block topology,
so an ordinary gas-baseboard office is conditional. A reviewer who sees the
label on nearly every submission may learn to disregard it, which would cost
the cases where it means something specific to that building — AHJ-1's
non-conforming substitution, for instance.

Nothing here suppresses anything. The open question is PRESENTATION, which is
phylroy's call and not Sol's: whether the report should distinguish a
STRUCTURAL question that applies to a whole class of buildings from a
BUILDING-SPECIFIC one that applies because of what this submission contains.
That would preserve the label's discriminating power without hiding a single
question. It is not implemented.

## AHJ-1 — a single-fuel reference is a NON-CONFORMING substitution

**Article.** 8.4.4.9.(5) with 8.4.4.9.(6); 8.4.5.9.(5) with 8.4.5.9.(6).

**The requirement, and why we do not meet it.** Sentence (5)(a) requires the reference heating capacities
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
tool does not establish — the selected variant may adopt the proposed plant,
replace it, tear it down, or stage it by role blind to fuel. It says so: an
UNRESOLVED audit warning per serving system, `8.4.x.9.(5)` held at
`not_implemented`, and the run's determination set to `conditional` naming
this question.

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

## AHJ-2 — the annual-energy basis (2)(g) compares, and an irreconcilable Article 13 case

**Article.** 8.4.4.13 and Table 8.4.4.13; 8.4.5.13 and its table; with
8.4.x.9.(5).

**Status: `referral`** — the acceptable-solution text does not decide this question.

**NARROWED by Sol's `126`.** Article 13 and Article 9 operate CONCURRENTLY —
Article 13.(2)(f) bases terminal and auxiliary capacity on the peak load *and*
the requirements of Subsections 8.4.1, 8.4.2 and 8.4.4/8.4.5, and Article 13
nowhere says Article 9 ceases to apply. So the referral is not "which article
wins". Two independent live branches remain: the ANNUAL-ENERGY BASIS, because
13.(2)(g) says "largest annual energy use" and a 33% share without saying
whether the comparison is source/input energy or delivered heat and Division A
defines consumption only at the whole-building aggregate; and an actual
IRRECONCILABLE case where Article 13.(2)'s mandated capacities cannot satisfy
(5)'s ratio. **The 33% proviso does not authorise a structural single-fuel
fallback.**

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

## AHJ-3 — whether 8.4.4.9.(6)(d) permits more than one boiler

**Article.** 8.4.4.9.(6)(d); 8.4.5.9.(6)(d).

**Status: `referral`** — the acceptable-solution text does not decide this question.

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

**Status: `ruled`. Does not set a run conditional.**

**Article.** 8.4.2.2.(5); 8.4.2.2.(5) in the 2025 edition.

**RULED by Sol on fetched text. No referral needed.** Sol ruled on fetched text that the exclusion
requires controls ensuring the backup operates ONLY when the primary is not
operating, and that `SequentialLoad` does not establish that condition: it
permits the secondary to run while the primary is saturated. Device names,
supply order and the word "Secondary" are not qualifying controls. A project
with an explicit mutually exclusive interlock could qualify, but the modeller
must supply that control evidence. Recorded here because it was raised as a
possible referral and is not one.

## AHJ-5 — a water-loop heat pump's source-loop boiler IS an energy type

**Article.** 8.4.2.2.(5); 8.4.x.9.(5); 8.4.x.13.(1); Appendix note
A-8.4.x.13. Per-edition citations are in the register's provenance for
Sol's `126`.

**Status: `ruled`** — settled; no authority is needed.

**THE RULING, and the DEFECT it exposes.** Sol's `126` settled this against
fetched text: Division A defines a primary system as equipment converting
electricity or fuel to heating and distributing it to secondary systems,
giving boilers as the example, and the Article 13 Appendix definition says a
water-loop heat-pump system's source loop may include an auxiliary heat source,
"e.g. a boiler". Article 13.(1) routes that case back to Table 7-A and does
not exclude Article 9.

So electric compressors and an active fuel-fired source-loop boiler are TWO
energy types used by the heating service set, and 8.4.x.9.(5) fires. In Sol's
words: **"classifying only the group-local compressor fuel and ignoring the
source-loop heat is a predicate defect."**

This entry therefore stops being an open interpretation and becomes a named
TOOL DEFECT with a settled answer. It is not a `tool-gap` entry because the
Code question had to be decided first and now is; the fix is to make the
classifier count the source plant's fuels for the blocks it actually serves.

**The one exclusion.** 8.4.2.2.(5) can exclude a genuinely redundant source
whose controls operate it ONLY when the primary is not operating — the same
mutually-exclusive-controls test AHJ-4 settled. A normal source-loop boiler
that runs while compressors run does not qualify.

**Was the hole.** Until `126` this entry said NOTHING fires for that shape and
called it a hole rather than a disposition. That is now HISTORY, not present
behaviour: the ruling landed, the predicate is fixed, and the disclosure
fires.

**The original observation.** In sample 09 `classify` types the `Heat Pump Loop` as
hot-water with NaturalGas, while every WSHP group's heating energy types read
`['Electricity']` alone. The proposed system therefore draws gas at the loop
boiler and electricity at the compressors, and whether the loop boiler is an
energy type "used by the heating system" for (5) is a scoping question the
text does not settle.

**Established by.** Fable `117` O2.

**What the tool does now.** `service_set_heating_fuels` adds the source-loop
plant's fuels to the group's service set, so 8.4.x.9.(5) is disclosed as
UNRESOLVED once per affected serving group. MEASURED on frozen sample 09: its
warnings went from 55 to 60 and twelve serving groups now disclose. The
8.4.2.2.(5) backup exclusion is not detected, so a genuinely standby boiler is
OVER-disclosed.

## AHJ-6 — the catalog offers no oil or propane variant

**Status: `tool-gap`, NOT a referral.** Sol's `122`: (4) says identical energy type and Division A requires the same energy sources, so this is a catalog defect to close. It is recorded here because it was raised as a referral and is not one.

**Article.** 8.4.4.9.(4); 8.4.5.9.(4); with Division A's building-energy-target
definition.

**The gap.** (4) requires the reference energy type to be modeled as IDENTICAL
to the proposed, and Division A requires the same energy SOURCES for the same
functions. `_reference_energy_type` elects by a cascade returning `'gas'` for
any recognised fossil fuel, so oil and propane both get the GAS catalog
variant — there is no oil or propane variant to get.

**That is a SELECTION fact, and the final equipment is configuration-dependent**
(Sol, `125`.1). Measured on an oil-fired proposed building: where the hot-water
plant is ADOPTED the reference keeps `FuelOilNo2`, and where a
hot-water-baseboard variant tears it down the reference carries `NaturalGas`.
So a final-fuel mismatch is real but not universal, and the earlier wording —
"an oil- or propane-heated building is compared against a natural-gas
reference" — stated the selector's answer as the reference's.

Sol ruled the sources stay distinct and that this is a catalog gap, not a Code
reading. Unlike AHJ-1 it IS fixable tool-side by adding the variants, and
belongs here only until that is done. Propane's final outcome has not been
measured; only oil's has.

**Established by.** Sol `110`, confirmed against fetched text in `121`
blocker 2.

**What the tool does meanwhile.** 8.4.x.9.(4) is held at `partial` and the
collapse is stated in its coverage gap. It does NOT currently set the run's
determination to conditional, because the fix is implementation rather than
interpretation.

## AHJ-7 — three published chiller EIR_FT rows are arithmetically wrong

**Article.** Table 8.4.5.5.-C (NECB 2020); Table 8.4.6.5.-C (NECB 2025).

**Status: `alternative-solution`** — the text DOES decide it and we do not
comply. Sol's `126`: the printed coefficients are unambiguous, although
defective, so using suspected corrected values DEPARTS from the published
acceptable solution and needs approval when an affected row is used. It was
previously filed as a `referral`, which was wrong — there is no ambiguity in
the text, only an error in it.

**The requirement, and why we do not meet it.** THE DEFECT IS IN THE PUBLISHED
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

## AHJ-8 — Table 4.2.1.6's A and B control marks are not carried at all

**Article.** Table 4.2.1.6 and its Note (1), both editions.

**Status: `tool-gap`, NOT a referral.** The Code is clear; we do not carry what
it requires. Recorded here because the codes service warned about exactly this
consumer shape and nothing in this repository had picked the warning up.

**What the Code requires.** Note (1) defines the nine control columns' marks:
controls marked `X` must ALL be implemented, and **at least one `A` and at
least one `B` must also be**. The service's `known_issue` on this table says so
and names the consequence: "a consumer that keeps only 'X' silently drops the
A/B group requirements (140 A and 163 B marks per edition)".

**We are that consumer.** `tables/daylighting_controls_4_2_1_6.json` reduces
the nine columns to two fields, `sidelighting` and `toplighting`, with only two
states, and its own evidence strings name only the two cell kinds it read:

```
'required'      186   evidence: "Table 4.2.1.6 cell 'X'"
'not_required'    12   evidence: "Table 4.2.1.6 cell '-'"
```

No `A` or `B` value appears anywhere in either edition's shipped table.
Nothing in `btap/codes/necb/lighting/` implements an A/B group rule, and the
data could not support it if it tried.

**Established by.** The codes service's own `known_issue` on Table 4.2.1.6
(`services/codes/docs/known-limits-necb-4.2.1.6.md`), archived at
`necb2020/provenance/daylighting_controls_4_2_1_6.result.json`; the omission in
our shipped data and the absence of any A/B rule in product code were verified
here on 2026-10-07, after phylroy asked for the table errata to be surfaced.

**Coverage says `implemented`.** Both editions claim `4.2.1.6.` as implemented,
with `how` text describing only the lighting-power-density values. The article
also carries the control columns, and the id is prefix-matched, so the claim
reaches them. That is an overclaim of the same shape this register's first six
entries were created for.

**What the tool does meanwhile.** Nothing — and nothing warns. This is a gap to
CLOSE, not a question for an authority: carry the A and B marks, implement
Note (1)'s group requirement, and correct the coverage claim. Until then a
building is not checked against a requirement the Code states plainly.

**Also on this table, and lower severity.** The service flags one space-type
label as OCR-damaged — `Class Il facility(8)` for the printed `Class II
facility`, a capital-I followed by a lowercase-L — and two Space Category
labels as normalised rather than verbatim. Both spellings are present in our
shipped file. Its guidance is to match case-insensitively or normalise
`Il` -> `II`, and to key on Space Type plus LPD when identity matters rather
than on the synthesised category. Whether our lookups do that is unverified.

## AHJ-9 — two table-structure errata with definitive guidance

**Article.** Table A-8.4.3.2.(1)-G and the schedule tables behind
`loads_rules`, both editions.

**Status: `ruled`. No authority needed, and no run conditional.** Recorded so
the register shows it considered these and why they are not referrals.

**A-8.4.3.2.(1)-G's section labels are missing.** The printed schedule divides
into blocks — Occupants, Lighting, Receptacle Equipment, Fans, Cooling System,
Heating System, Service Water Heating — and the service's repair produced no
column to hold the labels, so its 21 rows read as repeated Mon-Fri/Sat/Sun
triples with nothing to distinguish one block from another. The guidance is
definitive: rows 1-3 Occupants, 4-6 Lighting, 7-9 Receptacle Equipment, 10-12
Fans, 13-15 Cooling System, 16-18 Heating System, 19-21 Service Water Heating,
and every sibling table A..K carries the labels in a column. The hourly values
are correct and in printed order.

**The printed table heads both noon and midnight `12`.** Rows are served keyed
by column label, which cannot hold a duplicate key, so the two are served as
`12p` for noon and `12a` for midnight. Both are recovered from the raw
extraction, not inferred.

**What the tool does meanwhile.** It consumes the service's disambiguated form
as given — `12p`/`12a` as served, and the 21 rows in printed order — and adds
no reading instruction of its own. Nothing verifies either mapping, which is
the risk recorded below.

**Established by.** The codes service's `known_issue` on each table, archived
at `necb2020/provenance/vintage_match/A-8.4.3.2.(1)-G.result.json` and
`necb2020/provenance/loads_rules.result.json`. Surfaced into this register on
2026-10-07.

**Why these are not referrals.** Neither is an ambiguity in what the Code
REQUIRES — the values and their order are known, and the service states them.
They are reading instructions for a consumer of the data. They are recorded
because getting either wrong would silently shift a whole schedule: mapping
the 21 rows to the wrong blocks, or reading `12a` as noon, would move every
hourly profile by twelve hours or attribute one block's values to another.
**VERIFIED 2026-10-07, and both are honoured.** The vintage-match pass
compares `tables/schedules.json` against the MCP payloads for all eleven
schedule tables, the label-less G table among them, and the verdict is
**identical** in BOTH editions with zero differing leaves. Our values therefore
equal the served form, so the 21-row block mapping and the noon/midnight
disambiguation were carried correctly at extraction. No `12p`/`12a` key appears
in our shipped data and no product code reads one; the schedules are stored as
24-value hourly series.

A weaker check was tried first and rejected: flagging occupancy-type rows whose
value at 00:00 exceeds the value at noon. It returns 23 rows, and inspection
shows they are flat 24/7 profiles and legitimately night-occupied building
types, not shifted schedules. It cannot distinguish the two, so it is not
evidence either way. The vintage-match verdict is.

---

# Referrals from the decision-log audit

Sol audited all 60 `runtime`, `data` and `runtime_unwired` decisions against
normative text on 2026-10-07, after phylroy observed that decisions he had
adjudicated might embed readings an authority should weigh in on. Nine needed
referral; the other 51 are text-settled, modelling mechanics, historical
record, or outside NECB interpretation. **Twelve were explicitly rejected as
referrals and named as tool or data gaps** — D-05, D-14, D-22, D-35, D-41,
D-47, D-48, D-49, D-50, D-57, D-92 and AHJ-6 — because calling a defect an
ambiguity would launder it.

**That paragraph is now history.** It used to say none of these set a run
conditional and that wiring them was follow-on work. All seven are wired —
AHJ-2, AHJ-10, AHJ-11, AHJ-12, AHJ-14, AHJ-15 and AHJ-16 — each at the site
that makes the choice, with the narrowing Sol's `126`/`127` established and a
boundary negative for every exclusion. Two of them, AHJ-14 and AHJ-15, reach a
real annual determination in the frozen corpus.

What remains open is EVIDENCE, not wiring: AHJ-2, AHJ-3, AHJ-10, AHJ-11,
AHJ-12 and AHJ-16 have no frozen artifact that reaches a determination, because
the annual tier runs `--quick` and the shapes that would exercise them sit in
tiers that stop earlier. The status column says so per entry.

## AHJ-10 — how corner thermal blocks are grouped

**Article.** Table 8.4.x.7.-B, Note (3).

**Status: `referral`** — the acceptable-solution text does not decide this question.

**The ambiguity.** The note says only that blocks are "grouped together based
on facade orientation". D-18 assigns a corner block by largest exterior-wall
area, with a north/east/south/west tie-break. Neither the metric nor the
tie-break is in the text.

**Established by.** Sol `122`, decision-log audit.

**What the tool does now.** It applies D-18's rule — largest exterior-wall
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

## AHJ-11 — heating in a two-pipe System 5 reference

**Article.** 8.4.x.1.(5) with Table 8.4.x.7.-B, System 5.

**Status: `referral`** — the acceptable-solution text does not decide this question.

**Reachable in the Code, NOT YET EVALUABLE by this tool.** `129` claimed a
coherent refrigerated model completed the full `necb2025` path. Sol WITHDREW
that in `130`: the fixture it rested on established only that four EnergyPlus
runs terminated, and a matched reference probe is thermally invalid despite
completing — 8,760 cooling-unmet hours per zone, temperatures to 41.75 °C
against a 4 °C setpoint. I had repeated the claim here, so it was false on this
surface too.

The truthful statement: the branch is normatively and physically reachable —
`130` identifies the archetype, a medium-temperature cool-storage block with
real refrigeration evaporators plus a low-limit unit heater — but **no coherent
BTAP annual artifact has yet evaluated it.** Three separate tool gaps stand in
the way: AHJ-18 (no plant-side changeover), AHJ-19 (refrigeration invisible to
classification, teardown and end-use reporting) and AHJ-20 (a 7 °C comfort
chilled-water loop that cannot condition a 2/4 °C cooler). None is part of this
ambiguity.

**Narrowed reachability** (`130`): a thermal block selected as refrigerated
space that has GENUINE SPACE-HEATING equipment in addition to its refrigeration
cooling. A cooling-only freezer or cooler does not raise AHJ-11.

**The ambiguity.** A genuine internal tension in the Code, not just in our
reading: sentence (5) requires identical heating presence between proposed and
reference, while the table's System 5 row says heating "None". D-39 retains
heating when the proposed block is heated.

**Established by.** Sol `122`, who called it a genuine internal tension.

**What the tool does meanwhile.** It follows (5) and retains the heating,
audited against both the sentence and the table row.

## AHJ-12 — "where present" humidification

**Article.** Table 8.4.x.7.-B, Note (1).

**Status: `referral`** — the acceptable-solution text does not decide this question.

**REFRAMED by Sol's `126`.** Note (1) clearly governs the energy SOURCE once
humidification is present in the reference; it does not say whether reference
humidification is present at all. That silence is the live question, not the
source rule. Reachable where a proposed thermal block has humidification and
the selected reference topology does not independently establish presence.

**The ambiguity.** D-55 reads "where present" as requiring reference
humidification wherever the PROPOSED has it. Sol reads the note as fixing the
energy source only for humidification already present in the REFERENCE — a
materially different scope.

**Established by.** Sol `122`.

**What the tool does meanwhile.** It applies D-55's reading, which adds
reference humidification the other reading would not.

## AHJ-13 — Path B is permitted; whether we meet its IPLV is unverified

**Article.** Table 5.2.12.1.-K.

**Status: `ruled`** — settled; no authority is needed.

**The question, and the ruling.** The table supplies both Path A and Path B,
and D-59 elects Path B. Sol's `126` ruled that both are EXPRESS table paths
and Path B is permitted, so electing it needs no authority — the table offering
two compliant paths is not the same as the Code failing to decide.

**What remains is a TOOL-VERIFICATION gap, not a referral.** Path B carries
both a full-load COP and an IPLV. D-59 treats full-load COP plus the reference
curves as the IPLV realisation, and whether the tool actually MEETS Path B's
IPLV has not been verified. Reachable where the reference holds a packaged
water chiller whose applicable Table K row has Path B populated and the tool
selects Path B; rows carrying only Path A present no choice.

**Established by.** Sol `122`, re-dispositioned in `126` against fetched text.

**What the tool does meanwhile.** It applies Path B, recorded in D-59.

## AHJ-14 — which part-load class a reference boiler or furnace takes

**Article.** 8.4.x.2/.3 and Tables 5.2.12.1.-N/-O.

**Status: `referral`** — the acceptable-solution text does not decide this question.

**NARROWED by Sol's `126`.** Only equipment for which NO provision elects a
curve class. A purchased boiler is explicitly modulating under Article 6, and
an ordinary boiler above 352 kW is explicitly modulating too — neither is a
referral. What remains: an ordinary non-purchased fuel-fired boiler at or below
352 kW required by 9.(6)(b) or (c), where condensing versus non-condensing is
unresolved; or a fuel-fired furnace where no provision identifies its Part 8
curve class, since 9.(7)'s stage count does not decide atmospheric versus
condensing. Electric equipment is not conditioned.

**The ambiguity.** The Code supplies multiple part-load classes and the
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

## AHJ-15 — whether (3) governs dispatch priority at all

**Article.** 8.4.x.9.(3) with 8.4.2.10.(2).

**Status: `referral`** — the acceptable-solution text does not decide this question.

**NARROWED by Sol's `126`.** Only where Article 9.(5)(b) does not already
prescribe the proposed multi-energy priority — where it does, the priority is
carried over rather than chosen. Reachable where the reference selection
requires BOTH secondary-system heating and terminal heating under 9.(3), both
with non-zero capacity serving overlapping demand: concretely the System 3/4
furnace-plus-baseboard topology under D-91's current scope. A shared unit needs
its own analysis and must not silently inherit this predicate.

**The ambiguity.** Sentence (3) specifies terminal and plant CAPACITY, not an
annual dispatch sequence. D-91 selects air-terminal-first dispatch. Other
viable sequences move reference energy by about **48 MWh per year**, which
makes this the largest single unreferred assumption the audit found.

**Established by.** Sol `122`. D-91 remains the interim project ruling.

**What the tool does meanwhile.** It dispatches air-terminal-first per D-91
and audits it. The magnitude is why this entry exists rather than sitting in
the decision log alone.

## AHJ-16 — N:1 system correspondence for hydronic pumps

**Article.** 8.4.x.14 and its Appendix A note.

**Status: `referral`** — the acceptable-solution text does not decide this question.

**The ambiguity.** The note explains multiple pumps WITHIN one proposed
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

## AHJ-17 — no air-cooled chiller performance curve is shipped

**Article.** Table 8.4.5.5.-C / 8.4.6.5.-C; with 8.4.x.6.(2) and
8.4.x.10.(6)(f).

**Status: `tool-gap`, NOT a referral.** Split out of AHJ-7 so that entry
carries only the published-table defect. The Code supplies the curves; we do
not ship them. Nothing here needs an authority.

**What is missing.** `efficiencies.json` carries 19 `WaterCooled` chiller rows
and exactly ONE `AirCooled` row, and that row has `compressor_type: null` and
`eirft: null`. Curves are applied from the row via
`setElectricInputToCoolingOutputRatioFunctionOfTemperature`, so an air-cooled
reference chiller keeps the **OpenStudio default** performance curve rather
than a Table 8.4.5.5.-C one. Every curve reference that IS present resolves —
0 dangling of 60 checked — so this is an absence, not a broken link.

**Why it matters.** 8.4.x.6.(2) represents purchased cooling with an
air-cooled electric chiller, and 8.4.x.10.(6)(f) governs the reference chiller
type, so the path is reachable rather than hypothetical.

**Established by.** Verified here on 2026-10-07 by evaluating the shipped
curves at the AHRI rating point and enumerating the chiller rows; split from
AHJ-7 on Sol's clearance review.

**What the tool does meanwhile.** It uses the simulator default, with no
warning. Closing this means carrying the air-cooled rows — and the Screw row
among them is the one AHJ-7's erratum affects, so closing it requires adopting
that correction deliberately rather than transcribing the printed value.

## AHJ-18 — the two-pipe fan-coil surrogate has no plant-side changeover

**Article.** Table 8.4.4.7.-B / Table 8.4.5.7.-B, the System 5 row.

**Status: `tool-gap`** — implementable, so it is a defect to close, never an
interpretation. It does NOT make a verdict conditional.

**The gap.** Table 7-B defines System 5 as a TWO-PIPE fan coil. The build gives
each zone a `ZoneHVACFourPipeFanCoil` with a water-heating coil on an
independent hot-water loop and a water-cooling coil on an independent
chilled-water loop. `tpfc_htg_availability` and `tpfc_clg_availability` make the
COILS seasonally exclusive; **neither plant loop receives the corresponding
availability control.**

Two simulation loops are not themselves disqualifying — Sol's `129` notes the
pinned library's own `model_two_pipe_loop` keeps separate loops "for sizing
reasons" — but it adds inverse PLANT availability and this port does not. In
cooling season the hot-water loop can circulate through unavailable heating
coils with no heat sink and run away.

**Established by.** Sol `129`, isolating one factor at a time. With four-pipe
fan coils the runaway does not occur; with inverse scheduled availability added
to both plant loops it disappears. Measured here: a heated System 5 reference
terminates with `CheckForRunawayPlantTemps` in August.

**Why it is not simply fixed in place, measured.** The plant loops are SHARED.
`plant_loops.hot_water(..., reuse=True)` returns one loop per model, and a
mixed reference was measured carrying ONE 'Hot Water Loop' with 8 demand coils
across two different systems. Stamping seasonal availability on it would make
heating unavailable in summer for every other system drawing on it — a worse
defect than the one being fixed. Closing this properly needs either a dedicated
loop for the two-pipe system or a changeover that does not disable the loop for
its other consumers, which is a design decision rather than a one-line control.

**What the tool does meanwhile.** It builds the four-pipe surrogate. A heated
System 5 reference may fail to simulate, and when it does the run fails loudly
rather than reporting a number. AHJ-11 cross-references this entry while it is
open, and the two remain separate.

This paragraph previously ended by saying a coherent refrigerated model
completes the full `necb2025` path with zero severe and zero fatal errors. Sol
withdrew that in `130` and I had repeated it: a clean termination is not
evidence of thermal validity, on either side of the comparison.

## AHJ-19 — real refrigeration is invisible to classification, teardown and end-use reporting

**Article.** Table 8.4.4.7.-A / Table 8.4.5.7.-A, the "all sizes of
refrigerated space" row; with 8.4.x.1.(5) and 8.4.2.10.

**Status: `tool-gap`** — implementable, so a defect to close and never an
interpretation. It sets no verdict conditional.

**The gap, in three places.** Sol's `130` built OpenStudio models carrying
`Refrigeration:AirChiller` objects and measured the real code paths:

1. **Classification.** `btap.modeling.hvac.classify.ZONAL` has no refrigeration
   entry. A refrigeration-only block reads `heated=False, cooled=False` and is
   dropped by `reference.py`'s `if not (group['heated'] or group['cooled'])`.
   With a low-limit heater it reads `heated=True, cooled=False` — so the tool
   says a genuinely cooled block is **not cooled**. A refrigeration air chiller
   that removes heat from the room IS a cooling system for 8.4.x.1.(5).
2. **Teardown.** `remove_hvac_from_zones` removed all ten air chillers and left
   their `RefrigerationCompressorRack` behind with zero loads, which is fatal:
   `Refrigeration:CompressorRack="COOL STORAGE RACK" has no loads` then
   `GetRefrigerationInput: Previous errors cause program termination`. A shared
   rack must be detached and removed once orphaned, as the teardown fixpoint
   already does for plant equipment.
3. **Reporting.** `runner.energy_results()` includes refrigeration in total site
   energy through the SDK total, but `end_uses_kwh` has no `refrigeration` key.
   A scenario can therefore show a plausible total while hiding whether its
   defining system ran at all.

**Established by.** Sol `130`, by building the models and reading the outputs
rather than the code.

**What the tool does meanwhile.** A refrigeration-only block gets no reference
system; a block with a low-limit heater reaches System 5 only because the heater
makes it look conditioned and the caller supplies `refrigerated_zones`. The
run's total energy includes refrigeration, and nothing in the report says so.


## AHJ-20 — System 5's chilled-water loop is a 7 °C comfort loop

**Article.** Table 8.4.4.7.-B / Table 8.4.5.7.-B, the System 5 row; with
8.4.2.10.

**Status: `tool-gap`** — implementable, so a defect to close. It sets no verdict
conditional.

**The gap.** `systems/plant_loops.py` hard-codes the reference chilled-water
loop to 7 °C, and the chillers' reference leaving-water temperature is 6.67 °C.
Table -B prescribes a water-cooled water chiller; **it does not prescribe 7 °C.**
A 2/4 °C cold room cannot be served by that fluid, and a colder space submitted
under the same row makes the mismatch larger.

**Why it is dangerous rather than merely wrong.** Sol's `130` measured the
reference that results: it completed with ZERO severe and ZERO fatal errors, a
site EUI of about 314 kWh/m² — entirely plausible — and **refrigerated nothing**.
Zone temperatures ran 9.32 °C to 41.75 °C against a 4 °C cooling setpoint, with
8,760 cooling-unmet hours in every zone. At the reverted fixture's 4/8 °C
setpoints the same reference recorded 8,736.5 to 8,760 unmet hours and
temperatures to 41.02 °C.

So a clean termination AND a plausible EUI are both insufficient. Article
8.4.2.10 requires the reference components to be modelled, limited capacities to
affect space temperature and energy, and unmet-load hours to be determined;
"EnergyPlus exited zero" is not the Code's test. The frozen-scenario EUI guard
added after my own absurd fixture would not have caught this one.

**Established by.** Sol `130`, measuring zone temperatures and unmet hours.

**What the tool does meanwhile.** It builds the comfort loop. Configuring a
water-chiller reference that can actually serve a refrigerated block — an
appropriate low-temperature fluid and equipment representation — is an
implementable modelling problem, not an interpretation an authority must bless.
