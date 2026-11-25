# HVAC system taxonomy and rename: stable model IDs and plain-English names

Revision 3. Revision 2 adopted Astra's first review (4 BLOCKER and 7 SHOULD findings). Revision 3 adopts her follow-up (2026-11-25): one new BLOCKER and four smaller items, listed under **Revision 3** at the end.

## Context

The 110-system HVAC catalogue (`src/btap/modeling/hvac/data/systems.json`) was assembled from six sources, and each uses its own naming style:

- NECB legacy: "PSZ RTU Gas and DX Coils and Hot Water Baseboard", "MZ BU RTU ..."
- US CBECS: "Baseboard gas boiler", "PSZ-AC with gas coil"
- campus: "Shared PSZ ..."
- ECM IDs: `hs09_ccashp_baseboard`
- reference heat pumps
- generic

Its 21 "families" follow those origins rather than system types. phylroy asked on 2026-11-25 for a catalogue in which a mechanical engineer can quickly find systems and their variants, with clearer names.

Decisions already taken with phylroy:

1. **Model ID plus display name.** A short, file-safe **ID** goes into the `.osm` and `.idf`. People see a **plain-English display name** in the catalogue, search, reports and audit.
   - Measured on 2026-11-25: `,` `;` `!` break IDF and OSM syntax, and `|` is reserved by our `name | zone` loop naming. EnergyPlus upper-cases names. The IDD states a 100-character limit.
2. **One thorough rename now, in one PR.** There are no other users yet, and the alpha label already warns that the API may change.
3. **Old names become `legacy_name`.** They stay searchable and are accepted as input, so phylroy's existing OSMs and recipes still resolve. They are never written into a model.

Step 0: once the plan is approved, save it to `docs/plans/HVAC_TAXONOMY_PLAN.md` and send the revised version to Astra.

## The hierarchy engineers browse (worked example)

The tree is **Category > System type > variants**. Variants within a type differ by **facets**, and the facets also drive the filters.

The categories are practical browsing groups, not distribution-medium claims (Astra #6). The distribution medium (all-air, air-and-water, all-water, refrigerant) is a separate facet.

```
A  Central ducted systems                         (one air handler serves the zones)
   A1 Packaged single-zone rooftop unit (PSZ) ........................ 21 variants
      psz-gas-hwbb-gasboiler
         Packaged single-zone rooftop unit (PSZ): gas heat, DX cooling,
         hot water baseboards - gas boiler          [NECB System 3 lineage]
      psz-gas-hwbb-gasboiler-necbs4
         ... (NECB System 4 form - same equipment as System 3)
      psz-ashp-elecsupp-elecbb
         ASHP heat with electric backup, DX cooling, electric baseboards
      psz-gas-perzone      gas heat, DX cooling, one unit per zone        [CBECS]
      psz-hw-hwbb-gasboiler-shared
         hot water heat, DX cooling, one unit serving several zones
         from one control zone                                            [campus]
   A2 Packaged VAV with reheat (PVAV) ................................. 3
   A3 Built-up VAV with reheat (VAV) .................................. 18
      vav-hw-hwbb-gasboiler-scrollchiller                 [NECB System 6 lineage]
         Built-up VAV with reheat (VAV): hot water reheat, chilled water cooling,
         hot water baseboards - gas boiler, water-cooled scroll chiller
   A4 Dual-duct VAV ..................................................... 1
   A5 Constant-volume reheat air handlers (CV reheat, incl. heating-and-
      ventilating unit with reheat) ...................................... 5
   A6 Furnaces, split AC, heating and ventilating units ................... 4
B  Outdoor-air unit + zone terminals             (DOAS or make-up air unit + zonal units)
   B1 MAU/DOAS + PTAC .................................................... 7
      mau-ptac-elec-elecbb                             [NECB System 1 lineage]
      doas-ptac-ccashp-elecsupp-elecbb     (formerly hs09_ccashp_baseboard)
   B2 MAU/DOAS + fan coils (2-pipe / 4-pipe) ............................ 25
      mau-fc4-gas-gasboiler-scrollchiller
         MAU + four-pipe fan coils: MAU gas heat + DX cooling; fan coils on
         hot water and chilled water - gas boiler, scroll chiller  [NECB System 2]
   B3 DOAS + zone heat pumps (PTHP, WSHP) ................................ 4
   B4 DOAS + VRF ......................................................... 3
   B5 DOAS + chilled beams (active / passive) ............................ 2
C  Zone equipment only                            (no central air)
   C1 Packaged terminal units (PTAC, PTHP, window AC) .................... 4
   C2 VRF ................................................................ 1
   C3 Water-source heat pumps (WSHP) ..................................... 1
   C4 Evaporative coolers ................................................ 2
D  Heating only      D1 Baseboards (3)      D2 Unit heaters (3)
E  Ventilation only  E1 DOAS ventilation only (1)      E2 Zone ERVs (1)
F  Process           F1 Computer-room air handler (CRAH) (1)
                                                                    total 110
```

**How an engineer searches:**

| Looking for | Catalogue page | Python |
|---|---|---|
| a rooftop unit with gas heat | open A1, tick *gas* | `systems(system_type="psz", ahu_heating="gas")` |
| what NECB uses for System 6 | click the *NECB System 6* chip | `systems(necb_reference=6)`, the actual reference use |
| fan coils on a heat-pump plant | B2, tick *air-to-water HP plant* | `systems(terminal="fc4", hw_plant="awhp")` |
| ventilation heat recovery | tick *ERV* (VRF refrigerant heat recovery is a separate chip) | `systems(vent_heat_recovery="erv")` |
| the old "PSZ RTU Gas..." name | type it; the card shows "formerly: ..." | `resolve("PSZ RTU Gas and DX Coils...")` |

## Identity rules

These rules come from Astra's findings 1, 2, 8 and 9.

- **An ID names a base catalogue row. It is opaque and immutable.**
  - IDs are minted once by the grammar below and **stored** in `systems.json`. After that they are never regenerated.
  - A test pins the full 110-ID registry. A changed configuration gets a **new** ID, and a retired ID is listed and never reused.
  - Consumers do not parse IDs.
- **The configured build is described separately.** A runtime override, such as NECB System 2 electric = the fan-coil row with `{"boiler_fuel": "Electricity"}`, or a composite part's `mau=False` or district source, is shown by:
  - **facets and display computed from the merged config**, and
  - audit text that reads `System 2 -> 'mau-fc4-...' + {boiler_fuel: Electricity} (... electric boiler)`.

  The ID never claims a plant it doesn't build. Override cases are part of the verification matrix.
- **No invented equipment.** NECB Systems 3 and 4 have identical topology (`systems/psz.py`). The System 4 rows get a **provenance discriminator** (`-necbs4`) and a display label that says "same equipment as System 3". There is no "exhaust" token.
- **Grammar** (mints new IDs only):
  - characters `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, at most 40 characters, ASCII only, no `, ; ! |`, unique case-insensitively;
  - segment order: type, heating, backup, cooling, reheat, zone add-ons, ventilation heat recovery, HW plant, CHW plant, heat rejection, scope, discriminator;
  - facets distinguish **explicit absence**, **unknown** and **implied default**, so omitting a segment never merges two configurations;
  - heat-pump sources are explicit: `ashp`, `ccashp`, `gshp`, `awhp`.
- **Display name** (never written into a model):
  - form: `<Type title> (<ABBR>): <air-handler duty>; <terminal duty> - <plant list>`;
  - ASCII only, with no `| ; !`;
  - must be unique, which the System 4 label guarantees. Display names are searchable but **IDs and aliases are the unambiguous resolution keys**.
- **Emitted-name safety** is tested on real builds:
  - an ID combined with a 50-character zone name and the longest component suffix;
  - repeated builds and forward translation;
  - case-insensitive collisions.

  Long zone names are a user input, so the test documents the bound rather than guaranteeing 100 characters. The `necb_pipe_name` namer remains an explicit exception.

## Facets (derived in code, no SDK import)

Astra #7 asked for facets organised by equipment role:

| Role | Facets |
|---|---|
| Air handler | `ahu_heating` (fuel or source: gas, electric, hot water, ashp, ccashp, ...), `ahu_cooling` (dx, chilled water, evaporative, none), `outdoor_air` (mixed, 100% OA, recirculation only, none), `vent_heat_recovery` (erv, hrv, none) |
| Terminal / zone | `terminal` (fc2, fc4, ptac, pthp, vrf terminal, wshp, active or passive beam, unit heater, ...), `terminal_heating` and `terminal_cooling`, `zone_heating` (hot water or electric baseboard), `reheat` |
| Plant | `hw_plant` (gas or electric boiler, district, heat pump, none), `chw_plant` (chiller type x water- or air-cooled, district, heat pump), `heat_rejection` |
| Whole system | `distribution` (all-air, air-and-water, all-water, refrigerant), `scope` (one per zone, shared from one control zone), `humidity_control`, `changeover` (simultaneous or seasonal), `refrigerant_heat_recovery` (VRF) |
| Lineage | `necb_lineage` (from `sys_abbr`; **lineage, not applicability**: the ECM rows hs14-16 also carry `sys_1`), `necb_reference` (the System 1-6 and hp definitions that **actually use** the row, read from both editions' `reference_rules.json`), `ecm`, `origin` |

Implicit-source rules are **conditional**. For example, WSHP builds a boiler **except** with `heat_rejection: ground`, and that rule is checked by re-reading the builder source.

Plant defaults (hot water source boiler, chilled water source water-cooled, boiler fuel natural gas) are **constants in `taxonomy.py`**. A test cross-checks them against `plant_loops` under the SDK, so catalogue discovery stays importable without OpenStudio (Astra #5).

## The HVAC catalogue page (`btap.modeling.catalog_html()`)

The page is how most engineers will meet the taxonomy, so it is rebuilt around **search plus filters**. It stays one self-contained, offline file with no external references, extending the small inline script it already has.

```
+------------------------------------------------------------------------------+
| HVAC System Catalog            [ search: "gas rooftop", "System 6", "PSZ RTU" ] |
| Showing 4 of 110   [clear all]                                                |
+----------------------+-------------------------------------------------------+
| FILTERS              |  A1 Packaged single-zone rooftop unit (PSZ)           |
| Category             |  +--------------------------------------------------+ |
|  [x] Central ducted 49|  | psz-gas-hwbb-gasboiler            [NECB Sys 3]   | |
|  [ ] OA unit + zone 41|  | Packaged single-zone rooftop unit (PSZ): gas heat,| |
|  ...                 |  | DX cooling, hot water baseboards - gas boiler     | |
| Air-handler heating  |  | formerly: PSZ RTU Gas and DX Coils and Hot Water  | |
|  [x] gas         12   |  |           Baseboard                               | |
|  [ ] electric     9   |  | [gas] [DX] [HW baseboard] [gas boiler] [shared]   | |
|  [ ] ASHP / ccASHP 14 |  +--------------------------------------------------+ |
| Cooling              |  ...                                                  |
| Terminal / zone      |  (click a card: loop diagrams, facts, and the code    |
| Plant (HW / CHW)     |   to build it: modeling.build_system(m, "psz-gas-...",|
| Ventilation, HR      |   zones))                                             |
| Scope                |                                                       |
| NECB reference / ECM |                                                       |
| Origin               |                                                       |
+----------------------+-------------------------------------------------------+
```

**Search**
- Free text over the ID, display name, legacy name, aliases, type title and abbreviation, and facet labels.
- Matching is case-insensitive and multi-word AND ("gas rooftop" finds rows containing both).
- Common synonyms map to the same chips, for example *RTU* = rooftop, *FPFC* = four-pipe fan coil, *ccASHP* = cold-climate ASHP.

**Filters**
- One group per facet. Ticks inside a group combine with OR; groups combine with AND.
- **Every chip shows a live count**, and chips that would return zero are greyed out, so an engineer never filters into an empty page.
- The tree on the left collapses to the types that still match.

**Shareable state**
- The search text and filters are kept in the URL fragment, for example `#q=gas&ahu_heating=gas&terminal=fc4`, so a filtered view can be linked or bookmarked.

**Cards**
- Display name, ID in monospace, lineage chips (NECB System / ECM / origin), and "formerly: <legacy name>".
- Clicking opens the existing loop diagrams, plus a copyable `build_system` line using the ID.

**Accessibility**
- Keyboard: `/` focuses the search box and `Esc` clears it.
- Filters are real checkboxes with labels, and the page still renders all systems if JavaScript is off.

**Data**
- Each card carries `data-facets` (JSON) and `data-search` attributes, generated from `taxonomy.py`.
- The page and the Python `systems()` filters therefore use **the same facet values**, and a test enforces that.

**Tests**
- Every one of the 110 systems is reachable through the tree and through search by its ID, display name and legacy name.
- For a set of filter combinations, the page's `data-facets` and Python `systems(**filters)` select the same IDs. The same filter logic is applied over the page's data in Python, so no browser is needed.
- The existing self-containment test still passes: no external references.
- Chip counts sum correctly.
- One rendered snapshot (no browser) is checked for structure, not pixels.

## Implementation: one PR, ordered commits

**C1. Taxonomy, with no behaviour change** (`systems.json` untouched)
- Move the facet helpers from `src/btap/stock/identify.py` down to a new `src/btap/modeling/hvac/row_facts.py`: `_row_heating_media`, `_BUILDER_COIL_DEFAULTS`, `_composite_shape` and `_ZONAL_UNIT_FAMILY`. The modeling layer may not import `btap.stock`; `identify.py` re-imports them.
- These helpers must **raise** on an unresolved composite part or a depth overflow, instead of silently skipping it, because they now feed naming.
- New `src/btap/modeling/hvac/taxonomy.py` holds:
  - the facets by role;
  - `TYPES`, which replaces `FAMILY_TITLES` and `FAMILY_BLURB` in `catalog_report.py`;
  - placement rules:
    - `mau_ptac` with `reference_hp` goes to CV reheat;
    - the campus H&V unit with reheat goes to CV reheat;
    - composites are typed by their parts;
  - `mint_id()`, `display(config)`, `tree()`.

**C2. Catalogue and builders switch to IDs**
- `systems.json` changes:
  - every row gets `id`;
  - `name` becomes `legacy_name`;
  - today's canonical strings go into `aliases`;
  - composite `parts[].name` becomes `parts[].id`.
- **Resolver bootstrap order** (Astra #5):
  1. index id, legacy name and aliases;
  2. validate composite references and cycles;
  3. derive facets and displays lazily.

  One lower-cased index raises if any key maps to two rows. The resolved config carries `id`, `legacy_name`, `display` and **no `name`**.
- **Audit every name-dependent predicate, not only `config["name"]` reads** (Astra #3). `stock/identify.py:382` infers loop cooling from `'DX' in row['name']`. Replace it with the `ahu_cooling` facet first, and prove that identify's **scores for every row are unchanged**: a per-row before/after table must be equal.
- **The identify tie-break keeps sorting by the immutable `legacy_name`.** The sort-by-ID change is cut from this PR.
- Builders stamp `config["id"]`: `naming.apply`, `systems/psz.py`, `vav_reheat.py`, `fan_coils.py`, `mau_ptac.py`, `doas*.py`, `furnace.py`, `base_system.py`, and the crah, doas and chilled-beam object prefixes.
- `canonical.py`'s per-family branches are deleted.
- `classify._recognize_gem_name` resolves through the index, so old models still classify.
- Stock recipes write IDs and read any key.
- `catalog_report.py`: the HTML catalogue is rebuilt around search and filters. See **The HVAC catalogue page** below.
- Public API: `systems()` gains facet keyword filters with closed vocabularies, and an unknown value raises with the valid list. Add `system_taxonomy()`. Update `tests/test_public_api.py`.

**C3. NECB reference data**
- In both editions' `reference_rules.json`, switch the **14** `system_definitions` variants to IDs: Systems 1-6 gas and electric, plus the two `hp`. Overrides stay unchanged.
- **Re-seal both edition manifests' `result_sha256` and their provenance notes** (Astra #10). Audit and `report.json` `catalogue` carry the ID. The audit line shows the override, as above.

**C4. D-58 golden** (`tests/fixtures/reference_selection_matrix.json`), key-only edit through a committed bijective `tests/fixtures/system_id_migration.json`. The proof (Astra #4):
- **inverse-mapping the migrated golden reproduces the pre-change file byte-for-byte**, outside the identity paths;
- numeric `system`, `action`, `energy_type`, `blocks`, nulls and assignment multiplicity are preserved;
- each mapping pair has **identical non-identity configuration**.

This is authorised by the new decision record.

**C5. Re-seal and samples**
- Re-run `scripts/simulate_all_systems.py` to re-key the status file by ID and refresh its hash.
- `scripts/generate_samples.py` and `verification/scenarios/scenario_defs.py` use IDs.

**C6. Tests, docs and fixtures**
- About 87 test files.
- The `variant_mockups` OSMs.
- The stock README, which a test executes.
- A "Finding a system" section in the modeling README.
- `packaging/windows/run-demo.cmd`.

**C7. Full re-freeze, under a strict gate** (Astra #11)
- **Structural equivalence for all 110 rows plus the override cases.** Build each row before and after the change, apply the name mapping, and normalized model content and connectivity must be identical: controls, equipment order, curves, plant associations.
- Annual evidence is compared **by fuel, by end use and by unmet hours**, not only total energy.
- **Any physical or selection change is accepted separately**, never folded into the rename. A name-sorted iteration reorder counts as such a change.
- The installed-wheel smoke gate is kept.

**Decision record, process** (precedent D-67). It records:
- stable opaque IDs, with base-row identity versus configured-build description;
- legacy names as permanent input aliases;
- the taxonomy;
- the D-58 key-only edit and its inverse-mapping proof;
- that the System 4 discriminator is provenance;
- that the reference heat-pump System 1 rows are CV reheat air handlers.

Commits C2-C4 fail the catalogue-hash test until C5, so the PR is merged by squash.

## Verification

1. A truth table for about 30 rows, covering every family, facet value and override case. A coverage test checks that every vocabulary value occurs and that each row lands in exactly one type.
2. Cross-checks without the SDK:
   - heating against `_row_heating_media`;
   - terminals against `_composite_shape`;
   - `necb_reference` against both `reference_rules.json`;
   - the conditional implicit-source rules against builder source.
3. Build and classify (SDK): `classify.characterize` agrees with the facets on every row.
4. Field-sensitivity mutations: mutating each facet-relevant field must change the facets.
5. Identity:
   - the pinned ID registry, with no reuse;
   - charset, length and case-insensitive uniqueness;
   - display uniqueness;
   - the emitted-name tests on real builds;
   - a **narrow leak test**: newly authored objects carry the ID prefix, not a legacy name. It does not do arbitrary substring matching, because "VRF" and "PTHP" are legitimate words.
6. Identify scores equal for every row before and after. The D-58 inverse-mapping proof. Structural equivalence across all rows.
7. Gates:
   - full suite with the package uninstalled, plus wheel smoke;
   - `lint-imports`, ruff, decisions and coverage checks;
   - `simulate_all_systems.py --check`, 110/110;
   - the strict re-freeze;
   - full CI dispatch at the PR head; merge when green.

## Defaults (phylroy can override)

- Legacy names are accepted as input, with an `audit.info` line recording "legacy name X resolved to Y". They are never emitted.
- Families stay as they are. The taxonomy fixes browsing, not the builds.
- The `catalog_name` and `catalogue` field names stay; their values become IDs.

## Revision 3: Astra's follow-up (2026-11-25)

Astra rated nine findings ADDRESSED and #7 and #9 PARTLY. She raised these new items:

- **BLOCKER: NECB applicability stays out of `btap.modeling`.** `necb_reference` is derived **in `btap.codes.necb`**, which owns `reference_rules.json`. The new function `btap.codes.necb.catalog_reference_use(code=)` returns `{id: [System N variants]}` for that edition.
  - `btap.modeling` keeps only `necb_lineage` (row data, `sys_abbr`) and code-agnostic facets.
  - `catalog_html()` and `systems()` take an optional **annotations provider**, so the NECB chip and filter arrive from the codes layer, following the costing `daylighting_areas` provider precedent.
  - `btap.codes.necb.catalog_html(code=)` is the NECB-annotated page.
- **#7 completed:** `terminal_outdoor_air` (none or ventilating terminal) describes PTAC and VRF units that supply outdoor air at the zone.
- **#9 policy:** an emitted model name over 100 characters is **audited as a warning, never shortened**. EnergyPlus 25.2 measured clean at 132 characters, and silent shortening could collide names.
- **Scope vocabulary:** `one per zone`, `shared from one control zone`, and `central multi-zone with independently controlled terminals` (VAV and similar).
- **UI verification exercises the shipped JavaScript.** The filter and URL-state code becomes a pure function in the page's script, and a test runs that exact function under `node` over the page's data. The test is skipped with a stated reason when `node` is absent, and is required in the CI image.
- **Chip counts are disjunctive:** a count shows what ticking that chip would give, with the other groups applied. Multivalued facets do not sum to 110, and no test claims they do.
- **Display grammar:** display text never reaches a model, so it needs only to be ASCII. `;` is allowed there. The ban on `, ; ! |` applies to IDs and emitted model names only.

## Findings outside this PR's scope (record; fix separately)

These surfaced while building the taxonomy (2026-11-25). The rename does not change any of them. The taxonomy only reports what the builders do.

1. **`stock/identify.py` reads equipment from names and defaults.**
   - `'DX' in row['name']` credits MAU cooling to the four NECB MAU + PTAC rows. It misses the campus water-heated-PTAC MAU, which has the same DX coil.
   - `row_heating_media` calls the four reference heat-pump CV-reheat rows *electric*, but the builder fits a DX heat-pump coil.
   - In this PR, scores stay identical by reading the immutable `legacy_name`. The fix is a separate, measured change.
2. **Possible double ventilation in the DOAS + four-pipe fan-coil composites.** `fan_coils.py` never zeroes the fan coils' outdoor air, so the DOAS *and* the fan coils ventilate. This is the class #217 found with zone ERVs, and it needs a sizing run to confirm.
3. **`canonical.py` describes the reference heat-pump System 1 rows as "100% OA make-up air".** The builder makes a mixed-air air handler (`sys_oa='mixed'`). The canonical names are retired by this PR.
4. **The NECB System 2 "make-up air unit" is built as a mixed-air unit.** It uses `build_oa_system` with `necb_mau` sizing (`all_outdoor_air: False`), so it is not 100% outdoor air.
5. **Chiller kind is a label only.** `chiller_type` names the chiller, and every chiller is a default `ChillerElectricEIR` until the efficiency pass applies kind-specific curves.
