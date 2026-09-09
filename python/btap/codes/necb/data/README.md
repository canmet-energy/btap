# NECB data — one independent snapshot per edition

Since Stage 3 of the multi-edition plan (`docs/NECB_MULTI_EDITION_PLAN.md`)
**code lives by domain and data lives by edition**. Everything an edition needs
sits under `necb<edition>/`; nothing at runtime reads another edition's files.
There is no `extends`, no alias and no fallback rung: a missing file is an error
naming the edition and the path. Removing a supported edition is `git rm -r` of
one directory. Two editions whose tables were verified identical ship two
byte-identical copies, because "identical today" is a finding about two
snapshots, never a dependency between them.

```
necb2020/                      necb2025/
  manifest.json                  manifest.json
  necb_rules.json                necb_rules.json
  envelope_rules.json            envelope_rules.json
  reference_rules.json           reference_rules.json
  efficiencies.json              efficiencies.json
  lighting_rules.json            lighting_rules.json
  loads_rules.json               loads_rules.json
  shw_rules.json                 shw_rules.json
  tables/                        eui_targets.json  ghg_factors.json
  coverage/articles_8_4.json     tables/   coverage/articles_8_4.json
```

`manifest.json` is what discovery reads — its `rules` map, `tables` list and
`coverage_text` pointer replace the old `*_rules_<vintage>.json` filename
grammar in `btap.codes`' registry, both coverage generators, the orphan-key lint
and `tests/test_coverage_code_refs.py`. It also carries this edition's
`articles` (the edition-specific article numbers rules cite) and
`literal_remaps` (how this edition renumbers article literals the source is
written in) and, since Stage 5, its `behaviours`. Adding an edition means adding
a directory with a manifest, not widening a fallback.

Product code never builds these paths itself: every loader resolves through
`btap.codes.necb._data_root()` at call time and caches keyed by that root, so a
test can point the family at a tree holding one edition (`_set_data_root(path,
_testing=True)`) and prove nothing reaches outside it. The hook is test-only by
design — a production override would let a deployed run silently replace
adjudicated package data.

**Runtime never contacts the MCP.** These files are generated/verified offline;
when a new edition lands, regenerate its snapshot and diff.

---

## `manifest.json`'s `behaviours` block — edition-specific CODE

Most of what separates two editions is data, and belongs in the files below.
What genuinely cannot be is bound here: `behaviours` maps a stable behaviour
name to the dotted module that implements it for THIS edition.

```json
"behaviours": {
  "archetype_eui_path": "btap.codes.necb.editions.necb2025.eui_archetypes",
  "part11_ghg":         "btap.codes.necb.editions.necb2025.part11_ghg"
}
```

`necb2020` declares `"behaviours": {}` — an **explicit empty declaration**, not
an omitted key, so the manifest states positively that this edition binds no
code of its own. (The reader treats an absent key the same way; the empty
object is the documented form.)

`Ruleset.behaviour(name)` returns the imported module, or `None` when this
edition binds nothing under that name — and every call site reads `None` as
"this edition has no such feature". That is how NECB 2020 has no 8.4.4
archetype-EUI path and no Part 11 GHG scoring without a single `edition ==
"2025"` test surviving in `compliance.py`.

Three rules hold the binding together, all gated by
`python/tests/necb/test_behaviour_binding.py`:

- The name vocabulary is `btap.codes.BEHAVIOURS`, in CODE, and an unknown name
  raises. It is deliberately not derived from the manifests present on disk: a
  one-edition install must still answer `None` for a behaviour another edition
  owns instead of crashing. The gate keeps the vocabulary equal, in both
  directions, to the union of what the manifests bind and what product code
  asks for — so a binding nobody reads, and a call site nobody implements, are
  both build failures.
- A manifest binding a name outside the vocabulary is refused when the manifest
  is read.
- Every bound module must import.

**Promotion rule.** When a later edition shares the logic, MOVE the module out
of `editions/<id>/` into the shared tree and point BOTH manifests at the new
dotted name — never bind one edition to another edition's module, and never
copy the code. Promotion changes what the shared tree means, so it **requires a
D-XX entry** recording why the two editions are now one implementation.
(Stage 5 itself needs no new decision: it binds code that was already
2025-only, with no change in behaviour.)

**Self-description rule (D-88).** A snapshot names another edition ONLY as
its origin, in provenance fields (`provenance`, `notes`, `derivation`,
`*_note`, `*_provenance`), never comparatively ("identical to 2020",
"renumbered from") and never forward (a 2020 file does not know 2025
exists). Everything the snapshot emits, consumes or displays — curve
identifiers, `article_coverage` prose, table columns, rule keys — speaks in
its own numbering. Comparisons belong in the generated
`docs/NECB_EDITION_DELTAS.md`; identity in the manifest's
`byte_identical_to`. `tests/necb/test_snapshot_self_description.py`
enforces it; `scripts/refresh_provenance_hashes.py` refreshes the result
hashes after any data edit.

---

## `manifest.json`'s `provenance` block — and `provenance/`

Stage 4 of the multi-edition plan added a **checked** `provenance` block to each
manifest. It covers **exactly the manifest-declared outputs** — every entry in
`rules`, `tables` and `coverage_text`, plus 2025's `eui_targets` and
`ghg_factors` — and nothing else: not `manifest.json` itself (a self-hash is
recursive) and not the files under `provenance/` (an archived artifact would
then need its own archived artifact, and so on).

```json
"tables/lpd_space_functions.json": {
  "source": "mcp:necb:2025",          // or oracle:<REF>, printed:<citation>, self:<what>
  "request": {"tool": "get_table", "code": "necb", "edition": "2025",
              "division": "B", "table_number": "4.2.1.6"},
  "source_revision": null,            // MCP: no build id is exposed. Oracle: the REF sha
  "source_sha256": "…",               // the RETAINED artifact's hash (see below)
  "extractor": "manual (transcription from the archived MCP payload)",
  "retrieved": "2026-07-12",
  "method": "transcribed",            // transcribed | copied | generated
  "source_verification": "archived",  // archived | revision_addressable | current_only | manual
  "note": "…",
  "result_sha256": "…"                // the SHIPPED file's bytes
}
```

**Two dimensions, not one status.** `method` says how the file came to be;
`source_verification` says how strongly its origin can be re-established. A
result hash proves integrity, never origin — which is why each entry pins the
source side too:

- **`archived`** — the canonical source payload is retained in this snapshot at
  `provenance/<basename>.result.json` and `source_sha256` hashes THAT file. The
  payload is a JSON object keyed by canonical request
  (`get_table:necb:2025:4.2.1.6`) whose values are the tool RESULTS, never the
  JSON-RPC/SSE envelope (whose request ids and transport metadata change per
  call), written with sorted keys, `(",", ":")` separators and no trailing
  newline. Two entries are archived *as themselves*: each edition's
  `coverage/articles_8_4.json` IS the retained artifact, so its `source_sha256`
  equals its `result_sha256` and its entry says so.
- **`revision_addressable`** — the source is the pinned legacy oracle, and
  `source_revision` is a sha a reader can check out (`legacy_pin/REF`). For one
  source file `request` is `{"path": …}` and `source_sha256` is that file's hash
  at REF; for several, `request` is a list of `{"path", "sha256"}` and
  `source_sha256` hashes the canonical form of that list.
- **`current_only`** — a live source with nothing retained; an honest, lesser
  attestation. No entry ships this today.
- **`manual`** — transcription with no retrievable artifact (the two umbrella
  self-declarations).

**`byte_identical_to` is an annotation, never a dependency.** 2025's six shared
tables are `copied` and carry their OWN `source_*` fields, because the copy was
made from the same retained artifact and not from another edition's live file —
including a duplicate of the archived payload under `necb2025/provenance/`. The
annotation is checked only when both editions are present, and it never gates
the edition that declares it. Removing an edition stays `git rm -r` of one
directory.

Re-check one file against what its entry pins:

```bash
btap-necb-coverage verify-source necb2020 tables/space_types.json
```

Exit 0 verified, 1 a hash mismatch, 3 not checkable on this machine (the oracle
is not installed, or the entry is `current_only`/`manual`). The oracle checkout
comes from the ENVIRONMENT, never from an assumed repository layout — an
installed wheel has no repository around it, and
`tests/test_self_containment.py` keeps this package out of one:

```bash
BUNDLE_GEMFILE="$PWD/legacy_pin/Gemfile" \
  btap-necb-coverage verify-source necb2020 efficiencies.json   # asks bundler
BTAP_ORACLE_CHECKOUT=/path/to/openstudio-standards-at-REF \
  btap-necb-coverage verify-source necb2020 efficiencies.json   # or point at it
```

**Refreshing an archived payload is a maintainer MCP operation**, deliberately
outside the CLI: replay the entry's `request` through `btap._mcp.MCPClient`
("codes" server), canonicalise the results into the same keyed object, and
update `source_sha256`. Ordinary runtime stays offline.

---

## `necb_rules.json` — the umbrella

Carries `article_coverage` (verdicts and iteration logic live in
`compliance.py`, EUI arithmetic in `tiers.py` / `editions/necb2025/`) plus one
rule the umbrella itself needs per edition:

- `unmet_cooling.minimum_allowance_h` — the absolute floor, in hours, under
  8.4.1.2.(4)'s cooling unmet-hours allowance (`+10%` of the reference **or**
  this, whichever is greater). 2025 declares `20.0`; 2020, whose wording has no
  floor, declares `0.0`. **Every edition declares it**, and the reader takes it
  with no default: an edition that forgot the key must fail, because a silent
  `0.0` where the code meant `20.0` is a wrong determination, not a missing
  feature.

## `envelope_rules.json`

Machine-readable transcription of the NECB envelope requirements:

- **U-values** (`u_values`): maximum overall (**effective**, per 3.1.1.7 —
  thermal bridging included) thermal transmittance by boundary
  (outdoors/ground), surface type (wall/roofceiling/floor/window/skylight/door)
  and HDD climate-zone bin (ceilings {3000,4000,5000,6000,7000,9999} = zones
  4/5/6/7A/7B/8). Lookup rule is legacy-exact: first value where `hdd < bin`,
  fallback 0.110.
- **FDWR** (`fdwr`): Article 3.2.1.4.(1) as **structured piecewise data, never
  eval'd** (constant / linear pieces). Boundary note: code text says ≤4000 →
  0.40; legacy uses <4000 with the linear branch yielding the identical 0.40 at
  exactly 4000.
- **SRR** (`srr_max`): 3.2.1.4.(2), 2% of gross roof area (2017+ value; NECB
  2011 was 5% — relevant only to a future edition backfill).
- **Reference envelope** (`reference_envelope`): the 8.4.4.3/8.4.4.4 (2025:
  8.4.5.3/.4) parameters — lightweight layers pinned from Note A-8.4.4.4.(1),
  air leakage from 8.4.3.3.(3).
- **article_coverage**: the completeness manifest — every governed article with
  status; emitted into every run's audit.

Sources:
- **2020**: Tables 3.2.2.2 / 3.2.2.3 / 3.2.3.1 + Article 3.2.1.4, retrieved via
  the building-codes MCP server (necb:2020) and **cross-checked cell-by-cell
  against legacy openstudio-standards
  `NECB2020/data/surface_thermal_transmittance.json` — exact match** (door row
  per legacy refs PCF 1536/1537).
- **2025**: Tables 3.2.2.2 / 3.2.2.3 / **3.2.2.4 (doors, split out in 2025)** /
  3.2.3.1 + 3.2.1.4 via MCP (necb:2025). **All values verified identical to
  2020** (opaque/fenestration/ground byte-match; the new door table equals the
  2020 door row). Performance-path articles renumbered 8.4.4.x → 8.4.5.x
  (verbatim text).

## `reference_rules.json`

The NECB performance-path reference-HVAC rules: system-selection table, system
definitions (mapped to the modeling catalog's names), and the modeling rules
(oversizing, heating/cooling plant staging, fans, hydronic pumps, purchased
energy).

- **2020**: Division B, Subsection **8.4.4** (Tables 8.4.4.7.-A/-B/8.4.4.13).
- **2025**: NECB 2025 **renumbered the performance path** — the
  reference-building rules moved to Subsection **8.4.5** (Tables
  8.4.5.7.-A/-B/8.4.5.13; part-load curves to 8.4.6). All rule *values* were
  verified identical to 2020 via MCP retrieval + edition diff; only article
  citations differ.
- Every rule block carries an `article` citation; the audit log repeats these
  per decision. **Category keywords** extend the Table 8.4.4.7.-A space lists
  with common synonyms so arbitrary space-type strings map to a category;
  unmatched types fall back to the default category per 8.4.4.7.(3) with an
  audit warning.

## `efficiencies.json`

Capacity-binned minimum-performance tables (boilers, chillers, unitary ACs, heat
pumps, furnaces, heat rejection) + the NECB performance curves. A transcribed
code TABLE rather than a rule manifest, which is why the orphan-key lint
deliberately leaves it out of scope (`necb_orphan_keys.NON_RULE_MANIFESTS`).

- **2020**: vendored verbatim from openstudio-standards NECB2020 `data/*.json`
  (= Table 5.2.12.1 values), curves from NECB2011 `curves.json`.
- **2025**: transcribed/verified per-table from the NECB 2025 Table 5.2.12.1
  series via the MCP (letter map: -K chillers, -N boilers, -O furnaces, -A
  unitary ACs & HPs; the file's `provenance.verification` block records the
  per-table result). Verified **identical** to 2020: chillers (Path B COPc,
  every bin), boilers, furnaces, and the unitary-AC/HP cooling SEER/EER ladders.
  **Real 2025 change**: split-system HP heating HSPF 7.4 → 7.8. Additions:
  single-phase SEER2/HSPF2 class rows (distinct subcategories, engine-neutral),
  COPh at −8.3 °C (informational), and the NEW Table 5.2.12.1.-M plant-heat-pump
  heating COPs by leaving water temperature (`plant_heat_pumps_heating`,
  informational). SEER2/EER2/HSPF2 convert with the SEER/EER/HSPF formulas,
  matching the documented openstudio-standards assumption. Table -C (PTAC/PTHP
  coefficients) changed moderately in 2025; that coefficient path is not
  implemented by the engine (documented gap, same as 2020).

## `lighting_rules.json`

Provenance, the sensor-schedule threshold (8.6 W/m²), the dwelling-unit LPD
(8.4.4.5.(2)), the LED atrium equations (the legacy `space_height` NameError
defect is documented and fixed), and the Part 4 + 8.4.4.5 article-coverage
manifest.

**The 2025 verification.** The 4.2.1.6 edition diff looked significant
(similarity 0.68) but is **structural**: 2025 added ~9 control columns and
renamed rows. The transcribed 2025 table was joined to the 2020 space-type
records by normalized name — 162 exact matches, **zero LPD differences**, atrium
bins 4.2/5.2/6.5 W/m² identical, every rename spot-checked identical. Before
Stage 3, 2025 aliased 2020's LPD data; it now ships its own copies of the shared
tables instead, with the same verified content.

## `loads_rules.json`

Provenance, the schedule-table citation prefix (a per-edition fact declared
`non_rule_keys` — see the file's `non_rule_keys_note`), and the article-coverage
manifest for Subsection 8.4.3.

**2025** was verified via the building-codes MCP server (necb:2025): Table
A-8.4.3.2.(2)-B was retrieved in full for BOTH editions and compared row-by-row
— all 89 space functions carry identical occupant density, receptacle load, SWH
load, schedule letter, and illuminance; schedule set A cell-verified identical.
The only 2025 changes are structural: Article 8.4.3.2 was reorganized into
clauses and the schedule tables renumbered `A-8.4.3.2.(1)-X` →
`A-8.4.3.2.(1)(b)-X`.

## `shw_rules.json`

Top keys: `autosize` (tank/loop sizing parameters), `efficiency` (Table 6.2.2.1
performance: electric standby-loss inputs, gas/oil UEF bins, large-equipment Et,
parasitic fractions, the 8.4.5.9/8.4.6.9 part-load curve spec, and
`heat_pump` — the storage-type heat-pump water heater floor applied as the DX
coil's rated COP, `minimum_cop` with the `metric` label the audit prints, 2020
`EF >= 2.1` / 2025 `UEF >= 2.23`), `solar_pool_minimums` (D-63: solar SEF +
pool-heater minimums, applied only when the model carries the equipment),
`article_coverage` and `provenance`.

**The formula strings are documentation, not configuration.** Rows like
`"sl_w_small_low_volume": "40 + 0.2 x V_litres (V < 270, bottom inlet)"` record
WHERE a coefficient comes from; the live coefficients are named constants in
`shw/efficiency.py`. Editing a formula string here changes nothing at runtime —
change the code and the string together. Numeric values that ARE consumed (bin
intercepts/slopes, thermal-efficiency floors, parasitic fractions, curve
coefficients, the solar/pool minimums) are read through `shw.rules(edition)` and
covered by the orphan-key lint: a vendored key nobody reads fails the build.

Verification trail: transcribed from the legacy pass, cross-verified against the
printed NECB Table 6.2.2.1 via the MCP (see each file's `provenance` block for
dates); the 6.2.2.1 solar/pool values were re-verified against hbix's restored
table extraction (D-61/D-63, 2026-08).

---

## `tables/` — the transcribed code tables

Each edition holds its own copy of every table it uses.

- `space_types.json` — the 308 NECB2020-lineage space-type records, vendored
  VERBATIM from the openstudio-standards **MERGED** standards_data (inheritance
  chain NECB2011←2015←2017←2020, later keys win — the raw per-vintage files are
  partial; the merge is what legacy actually runs). Every record keeps 78 of the
  merge's 80 keys, including `lighting_*` and `service_water_heating_*`; the two
  it drops are the vendored template columns `lighting_standard` and
  `target_illuminance_setpoint_ref`, removed 2026-09-09 under D-88 because they
  labelled every row `NECB2020` in BOTH editions' copies and nothing read them
  (`led_lighting.json` drops `lighting_standard` for the same reason). Units are
  IP as in legacy (documented in the provenance block); the apply layer converts
  exactly as legacy does.
- `schedules.json` — the 240 `NECB-<letter>-<category>` schedule records (Hourly
  24-value rows per `day_types` token + Constant records), vendored from the
  merged standards_data (the schedules table is inherited from NECB2015 —
  2017/2020 ship none of their own).
- `led_lighting.json` — the merged legacy `led_lighting_data` table (308
  records; LED alternative LPDs W/ft² + heat fractions per NREL 63807).
- `exterior_lighting.json` — Tables 4.2.3.1.-A..-E, the exterior lighting power
  allowances (2025 verified essentially unchanged; Table -D similarity 0.978).
- `table_c1.json` — NECB Table C-1 climatic data (679 cities: lat/long, HDD18,
  design temperatures), vendored from legacy
  `NECB2011/data/necb_2015_table_c1.json`, used for the nearest-city HDD lookup
  (haversine, 500 km tolerance) mirroring legacy `get_necb_hdd18`. The NECB 2025
  Table C-1 (680 rows) is on the MCP as a future cross-check/refresh source.
- `daylighting_controls_4_2_1_6.json` — Table 4.2.1.6's two **daylight-control**
  columns (`... for Sidelighting [see 4.2.2.1.(10)]` / `... for Toplighting [see
  4.2.2.1.(13)]`), keyed by the 105 NECB **space-function catalog names** rather
  than by table row, so the 4.2.2.1.(10)/(13) gate is a direct lookup.
  FIVE-state per column: `required` / `not_required` / `not_applicable` /
  `not_listed` / `unknown`. **D-57.** See below.
- `lpd_space_functions.json` (2025 only) — NECB 2025 Table 4.2.1.6 transcribed
  in full via the MCP: LPD (W/m²) **plus the per-row 4.2.2.1 lighting-control
  requirement matrix** new in 2025 (X = required, A/B = alternative groups).
- `lpd_building_types.json` (2025 only) — NECB 2025 Table 4.2.1.5 (building-type
  method, W/m²).

### Table 4.2.1.6 control data — how it was vendored, and what is still unknown

The two daylight-control columns were re-read **2026-07-30** from the corrected
upstream extraction and are now VERIFIED: the table's nine control columns agree
exactly between the 2020 and 2025 editions, 0 differing cells of 909, asserted
at generation time. The 2025-primary / 2020-corroborating conflict machinery
that used to live here is GONE, and so are the four conflicting rows it existed
for (`Classroom/Lecture hall/Training room other`, `Health care facility
physical therapy room`, `Manufacturing facility low bay area`, `Museum general
exhibition area`) — all four resolved. That finding is now expressed as two
byte-identical per-edition files, never as a shared file or a dependency.

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

---

## `coverage/articles_8_4.json`

That edition's packaged Section 8.4 article text, read offline by
`btap.codes.coverage` and by the Section 8.4 coverage generator. Refresh with
`python3 python/scripts/fetch_necb_8_4_text.py --edition <edition>`; ordinary
runtime stays offline. The Crown-copyright notice covering this text is
`btap/codes/data/coverage/ATTRIBUTION.md`, which is deliberately NOT per-edition
— one notice covers all cached NECB text, and `coverage.attribution()` takes no
edition.

## 2025-only files

`eui_targets.json` (Table 8.4.4.1 archetype EUI targets, the 2025 EUI path) and
`ghg_factors.json` (Part 11 provincial emission factors) exist only in
`necb2025/` and are declared under their own manifest keys. `btap.codes.necb`'s
`editions/necb2025/` modules read them; no other edition looks for them.
