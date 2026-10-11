# NECB questions this tool does not decide — for an authority

**GENERATED** by `python/scripts/generate_ahj_referrals.py` from
`docs/NECB_AHJ_QUESTIONS.md`. Do not edit: edit the register and
regenerate. It carries no figures or wording of its own, so it cannot
drift from the register it summarises.

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
- **Article:** 8.4.4.13 and Table 8.4.4.13; 8.4.5.13 and its table; with 8.4.x.9.(5).
- **Makes a run conditional:** yes, where the (2)(g) comparison is actually made

**The question.** 8.4.x.7.(4) sends heat-pump thermal blocks to Article 13 for the reference system type. Article 13 controls the ASHP topology, its capacity and operating limits, the terminal/auxiliary capacity, and the terminal/auxiliary energy-type election in (2)(g). Clause 13.(2)(f) expressly incorporates Subsections 8.4.1, 8.4.2 and 8.4.4/8.4.5. Sol ruled on fetched text that there is NO wholesale supersession and the two operate concurrently — but whether an irreconcilable capacity-allocation case is governed by Article 13's specific prescriptions or by (5) still needs an authority where the two cannot both be satisfied.

**Established by.** Sol `119`, `120`, narrowing his own earlier "expressly unresolved".

**What the tool does meanwhile.** The (5) disclosure runs on the heat-pump path as well as the structural one, and says the allocation is NOT VERIFIED. It does not claim the auxiliary election eliminates electric reference heating, which was a false statement it used to make. The (2)(g) election itself proceeds on delivered heat, audited, and falls back to the structural proxy with its own audit entry — so the choice is visible per run, and it SETS THE RUN CONDITIONAL wherever the (2)(g) comparison is actually made. It does not where there is no annual data to compare, which is a mode limitation rather than a question an authority can settle.

### AHJ-3 — whether 8.4.4.9.(6)(d) permits more than one boiler

- **Editions:** necb2020, necb2025
- **Article:** 8.4.4.9.(6)(d); 8.4.5.9.(6)(d).
- **Makes a run conditional:** yes, where a hydronic plant carries both fuels

**The question.** (6)(b) says "one single-stage boiler" and (6)(c) says "two boilers of equal capacity"; (6)(d) says only "a boiler that is fully modulating". Sol searched for a singular/plural interpretation rule and an Appendix A note and found neither, so whether additional boilers are forbidden above 352 kW is not established by the text.

**Established by.** Sol `119` section C, correcting his own earlier "conflict across every band" as too categorical.

**What the tool does meanwhile.** The (6) coverage gap states that the applicable subclause is not established at selection time and claims none.

### AHJ-10 — how corner thermal blocks are grouped

- **Editions:** necb2020, necb2025
- **Article:** Table 8.4.x.7.-B, Note (3).
- **Makes a run conditional:** yes, on a corner block above four storeys

**The question.** The note says only that blocks are "grouped together based on facade orientation". D-18 assigns a corner block by largest exterior-wall area, with a north/east/south/west tie-break. Neither the metric nor the tie-break is in the text.

**Established by.** Sol `122`, decision-log audit.

**What the tool does meanwhile.** It applies D-18's rule — largest exterior-wall area with an N/E/S/W tie-break — and **the choice IS audited**, since the metadata handoff landed. `VAVReheat` records structured grouping evidence (per external zone: the exterior wall area in each compass bin, the elected facade, the tie-break rule) and `btap.codes` emits the entry citing Table 8.4.x.7.-B Note (3) with `ahj='AHJ-10'`.

### AHJ-11 — heating in a two-pipe System 5 reference

- **Editions:** necb2020, necb2025
- **Article:** 8.4.x.1.(5) with Table 8.4.x.7.-B, System 5.
- **Makes a run conditional:** yes, where a heated block is assigned System 5

**The question.** A genuine internal tension in the Code, not just in our reading: sentence (5) requires identical heating presence between proposed and reference, while the table's System 5 row says heating "None". D-39 retains heating when the proposed block is heated.

**Established by.** Sol `122`, who called it a genuine internal tension.

**What the tool does meanwhile.** It follows (5) and retains the heating, audited against both the sentence and the table row.

### AHJ-12 — "where present" humidification

- **Editions:** necb2020, necb2025
- **Article:** Table 8.4.x.7.-B, Note (1).
- **Makes a run conditional:** yes, on a presence CHOICE — not where the topology settles it

**The question.** D-55 reads "where present" as requiring reference humidification wherever the PROPOSED has it. Sol reads the note as fixing the energy source only for humidification already present in the REFERENCE — a materially different scope.

**Established by.** Sol `122`.

**What the tool does meanwhile.** It applies D-55's reading, which adds reference humidification the other reading would not.

### AHJ-14 — which part-load class a reference boiler or furnace takes

- **Editions:** necb2020, necb2025
- **Article:** 8.4.x.2/.3 and Tables 5.2.12.1.-N/-O.
- **Makes a run conditional:** yes, where the row's own default elected the class

**The question.** The Code supplies multiple part-load classes and the efficiency tables do not select one for the reference. D-89 assumes ordinary boilers non-condensing and furnaces atmospheric, from LEGACY PRECEDENT rather than from the text — and the pinned gem has already been caught shipping the non-condensing curve on every boiler row, so the precedent is weak evidence.

**Established by.** Sol `122`, who added one caution: keep the purchased-energy case separate, because 8.4.x.6 explicitly specifies a MODULATING boiler, so there the Code does elect.

**What the tool does meanwhile.** It applies D-89's classes, and the purchased route separately applies the modulating class the article names (D-89's own scope note).

### AHJ-15 — whether (3) governs dispatch priority at all

- **Editions:** necb2020, necb2025
- **Article:** 8.4.x.9.(3) with 8.4.2.10.(2).
- **Makes a run conditional:** yes, on the System 3/4 branch where (5)(b) does not prescribe it

**The question.** Sentence (3) specifies terminal and plant CAPACITY, not an annual dispatch sequence. D-91 selects air-terminal-first dispatch. Other viable sequences move reference energy by about **48 MWh per year**, which makes this the largest single unreferred assumption the audit found.

**Established by.** Sol `122`. D-91 remains the interim project ruling.

**What the tool does meanwhile.** It dispatches air-terminal-first per D-91 and audits it. The magnitude is why this entry exists rather than sitting in the decision log alone.

### AHJ-16 — N:1 system correspondence for hydronic pumps

- **Editions:** necb2020, necb2025
- **Article:** 8.4.x.14 and its Appendix A note.
- **Makes a run conditional:** yes, on an in-scope transfer decline

**The question.** The note explains multiple pumps WITHIN one proposed system. It does not address several proposed hydronic systems corresponding to one grouped reference system, nor the case where no unique correspondence exists. D-93 and D-97 decline in those cases and retain a simulator default.

**Established by.** Sol `122`, as one combined referral for both decisions.

**What the tool does meanwhile.** It DECLINES rather than guessing, emitting an unresolved warning per affected loop and leaving the simulator default in place. That is NOT a conservative bound, which this entry previously claimed: D-97's runtime warning and Sol's `126` both say the retained default may bias the reference in EITHER direction. Declining to guess is defensible; calling the result conservative was not.

---

## `alternative-solution`

### AHJ-1 — a single-fuel reference is a NON-CONFORMING substitution

- **Editions:** necb2020, necb2025
- **Article:** 8.4.4.9.(5) with 8.4.4.9.(6); 8.4.5.9.(5) with 8.4.5.9.(6).
- **Makes a run conditional:** yes — `compliance_determination: conditional`

**Established by.** Sol `110`, `112`, `119`, `120`; Fable `117`, `118`. Sol fetched both editions through the codes MCP; Fable reproduced the implementation's behaviour with code.

**What the tool does meanwhile.** It elects ONE energy type for the reference SELECTION and computes no capacity ratio, so it satisfies neither clause of (5). What the reference's FINAL equipment carries is a separate question this tool does not establish — the selected variant may REPLACE the proposed plant with a newly built one of the elected variant, tear it down and not rebuild it where the variant needs no boiler, or stage it by role blind to fuel. It says so: an UNRESOLVED audit warning per serving system, `8.4.x.9.(5)` held at `not_implemented`, and the run's determination set to `conditional` naming this question.

### AHJ-7 — three published chiller EIR_FT rows are arithmetically wrong

- **Editions:** necb2020, necb2025
- **Article:** Table 8.4.5.5.-C (NECB 2020); Table 8.4.6.5.-C (NECB 2025).
- **Makes a run conditional:** not yet — see the entry

**Established by.** The codes service's own errata (`services/codes/docs/errata-necb-chiller-eir-ft.md`), surfaced in the `known_issue` of the archived payload at `necb2020/provenance/vintage_match/8.4.5.5.-C.result.json`. Recovered into this register on 2026-10-07 after phylroy recalled that table errors had been found in an earlier session; they were recorded in provenance and in the vintage-match verification, but not as an AHJ-weighable question.

**What the tool does meanwhile.** It ships the CORRECTED values for two of the three rows, and the manifest provenance records that it does so and why: "the water-cooled Scroll and Reciprocating rows agree only after the codes service's own published errata for those two rows ... so the misprint is the printed source's and the shipped curve already carries the corrected value". That is a documented deviation from the printed Code, which is the defensible choice and still a deviation.

---

## How a run says this out loud

Only `referral` and `alternative-solution` make a result
conditional. Where one applies to a final choice, the report carries
`compliance_determination: conditional` with a reason block naming
the approval required, one record per unique final choice, and the
exit code is deliberately unchanged. The CLI prints it inside the
verdict string and the HTML report badges it beside the pass/fail
badge, because the report is the artifact an authority reads.
