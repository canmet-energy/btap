# NECB lighting data — provenance and regeneration

- `led_lighting_2020.json` — the merged legacy `led_lighting_data` table (308
  records; LED alternative LPDs W/ft² + heat fractions per NREL 63807).
- `lpd_space_functions_2025.json` — NECB 2025 Table 4.2.1.6 transcribed in full
  via the building-codes MCP: LPD (W/m²) **plus the per-row 4.2.2.1
  lighting-control requirement matrix** new in 2025 (X = required, A/B =
  alternative groups).
- `lpd_building_types_2025.json` — NECB 2025 Table 4.2.1.5 (building-type
  method, W/m²).
- `daylighting_controls_4_2_1_6.json` — Table 4.2.1.6's two **daylight-control**
  columns (`... for Sidelighting [see 4.2.2.1.(10)]` / `... for Toplighting
  [see 4.2.2.1.(13)]`), keyed by the 105 NECB **space-function catalog names**
  rather than by table row, so the 4.2.2.1.(10)/(13) gate is a direct lookup.
  FIVE-state per column: `required` / `not_required` / `not_applicable` /
  `not_listed` / `unknown`. **D-57.** See "Table 4.2.1.6 control data" below;
  since the 2026-07-30 upstream fix a single corrected MCP call is exactly what
  generates it.
- `lighting_rules_<vintage>.json` — provenance, sensor-schedule threshold
  (8.6 W/m²), dwelling-unit LPD (8.4.4.5.(2)), the LED atrium equations
  (legacy `space_height` NameError defect documented and fixed), and the
  Part 4 + 8.4.4.5 article-coverage manifest.

## The 2025 verification

The 4.2.1.6 edition diff looked significant (similarity 0.68) but is
**structural**: 2025 added ~9 control columns and renamed rows. The transcribed
2025 table was joined to the 2020 space-type records (openstudio-loads gem) by
normalized name — 162 exact matches, **zero LPD differences**, atrium bins
4.2/5.2/6.5 W/m² identical, every rename spot-checked identical. 2025 therefore
aliases the 2020 LPD data (`data_vintage_alias`), while the 2025 control matrix
and both 2025 tables ship as native data.

## Table 4.2.1.6 control data — how it was vendored, and what is still unknown

The two daylight-control columns were re-read **2026-07-30** from the corrected
upstream extraction and are now VERIFIED: the table's nine control columns agree
exactly between the 2020 and 2025 editions, 0 differing cells of 909, asserted
at generation time. The 2025-primary / 2020-corroborating conflict machinery
that used to live here is GONE, and so are the four conflicting rows it existed
for (`Classroom/Lecture hall/Training room other`, `Health care facility
physical therapy room`, `Manufacturing facility low bay area`, `Museum general
exhibition area`) — all four resolved.

> Historical note: before that fix BOTH extractions were partly corrupted, and
> differently — the 2020 one lagged its `Space Category` column and carried
> `Manual` = X on only 57 of 103 rows. The reasoning is preserved in
> `necb_decisions.md` under D-57 and its 2026-07-30 amendment. Do not resurrect
> the workaround: it now REMOVES verified data.

Cell semantics: `X` → required; `-` → not_required; a BLANK appears only on the
four rows carrying a Note that defers the space type elsewhere, and those keep
their curated state. Some cells are genuine cross-references, not flags, and are
stated as such: `Storage garage interior` → Article 4.2.2.2. (which has its
*own* daylight rule in Sentence (4)); `Guest room` → Sentence 4.2.2.6.(2);
`medical supply room` → the Storage Room rows under Common Space Types.

Mapping validation: each catalog name was mapped by hand to a table row, then
every hard mapping was checked by comparing the catalog's `lighting_per_area`
(W/ft² × 10.7639) against the row's LPD (W/m²) — **102 of 102 agree** within
0.06 W/m² / 1%.

**What remains unknown is STRUCTURAL, not an extraction limit.** Five names in
the file's `residue` array have no row in Table 4.2.1.6 at all: the
`- undefined -` sentinel, both `Dwelling units` rows, `Audience seating area
permanent - convention centre`, and `WholeBuilding` (building-type method —
4.2.2.1.(2) ties the control requirement to the space-by-space types the tag
does not identify). The dwelling-unit rows resolve from the code text itself
(state `not_listed`: 4.2.2.1.(10)/(13) reach only spaces requiring the control
"in accordance with Table 4.2.1.6."). The other three WARN loudly at runtime and
take the documented conservative default (`required` — photocontrols in the
*reference* lower its lighting energy and so tighten the target, which cannot
hand a non-conforming building a pass). `unknown_control_requirement:
'not_required'` flips it, still warning.

**Caution for anyone re-vendoring:** this file consumes only the two daylight
columns, which are pure X/-/blank. The table's OTHER seven control columns carry
`A` and `B` marks that Note (1) defines as at-least-one-of-group requirements —
a consumer that keeps only `X` silently drops them.

Interior LPDs for 2020 live in the openstudio-loads gem's space-type records
(`lighting_per_area` W/ft² + fractions + `occ_sense`/`rel_absence_occ`/
`personal_control` = the Table 4.3.2.10 factors); this gem reads them through
`OpenStudioLoads::NECB::SpaceTypes`. Runtime never contacts the MCP.
