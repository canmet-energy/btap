# Modern HVAC catalog expansion: phases 1-3 implementation record

**Status:** implemented, with UFAD deliberately deferred. The
`btap.modeling.hvac` catalog now has 102 rows and builds generic OpenStudio SDK
topology, not a commissioned or code-compliant system. NECB
equipment-selection and efficiency rules stay in `btap.codes`; no product
dependency on measures or `openstudio-standards` was added.

## Implemented outcome

| Phase | Result |
| --- | --- |
| 1 | Shipped `DOAS with active chilled beams and electric baseboards` and `DOAS with passive chilled beams and electric baseboards`. They use a dehumidifying/reheating 100% OA loop, an explicit 15/18 C chilled-water profile, dew-point reset, and preflight-before-mutation validation. The hydronic-radiant candidate was retired after annual energy accounting showed that DX terminals supplied 83% of zone-terminal cooling and its uninsulated ground slab dominated heating consumption. |
| 2 | Shipped `VAV chiller with gas boiler reheat and rotary ERV` and `PVAV with gas boiler reheat and plate HRV`. The two recovery variants use gas-boiler hydronic perimeter trim; the pre-existing VAV/PVAV rows are unchanged. Existing `VRF`, `DOAS with VRF`, `hs08_ccashp_vrf`, and `hs13_ashp_vrf` retain heat recovery and are regression-pinned rather than duplicated. |
| 3 | Shipped `Dual-duct VAV with gas boiler and water-cooled chiller` as a true two-deck air loop with dual-duct terminals. UFAD did not ship: OpenStudio 3.11 has workspace/IDF support but no typed, persistent OpenStudio Model (`.osm`) representation, and post-translation augmentation is not enforceable in every supported backend. |

The shipped rows have focused object-graph and translation tests plus annual
EnergyPlus operating tests. One criterion applies to every new row: a clean
annual run, nonzero heating and cooling energy, and no more than 100 occupied
unmet hours in either mode on the standard five-zone fixture. The gate also
verifies beam hydronic design values, chilled-water dew-point-reset movement
without `PsyTsatFnPb` failures, central heat exchange, and simultaneous VRF
heat recovery.

That comfort criterion was added after the first implementation exposed an
important distinction between "the simulation completed" and "the system
conditioned the building." Before correction, the two beam rows had 411-420
cooling unmet hours and both recovery rows had 468.5 heating unmet hours. The
accepted topologies and final annual measurements are:

| Catalog row | Heating unmet h | Cooling unmet h | Conditioning correction |
| --- | ---: | ---: | --- |
| DOAS with active chilled beams and electric baseboards | 49.00 | 76.25 | `modern_doas` cooling reserve sized for dew-point-limited terminals |
| DOAS with passive chilled beams and electric baseboards | 49.00 | 89.00 | `modern_doas` cooling reserve sized for dew-point-limited terminals |
| VAV chiller with gas boiler reheat and rotary ERV | 70.00 | 0.75 | gas-boiler hydronic perimeter trim |
| PVAV with gas boiler reheat and plate HRV | 70.00 | 0.75 | gas-boiler hydronic perimeter trim |
| Dual-duct VAV with gas boiler and water-cooled chiller | 54.00 | 0.00 | original two-deck topology met the common criterion |

The 2.2 chilled-beam cooling reserve is explicitly empirical rather than a
design rule: 2.0 produced 116.0 occupied cooling unmet hours for the passive
row, while 2.2 produced 89.0. The recovery rows are likewise not an isolated A/B
experiment: their untouched non-recovery comparator records 468.75 heating
unmet hours, but the recovery variants also add hydronic perimeter baseboards.
The tests therefore claim only that each complete topology conditions the
fixture and that its heat exchanger operates.

The radiant candidate did not earn a catalog name. On the same annual run,
PTAC DX supplied 18,680 kWh against 3,955 kWh from the slab (83% versus 17% of
zone-terminal cooling), and the named chiller used 4,077 kWh against
26,292 kWh of DX cooling. Removing the PTACs left 2,315.5 occupied cooling
unmet hours. The floor injected about 313 MWh of heat while roughly 271 MWh
left through the preserved, uninsulated 3.401 W/(m2 K) ground slab; its
555.6 kWh/m2 heating intensity was far above the accepted rows' 91-156
kWh/m2. Adding insulation would move the problem into an unrequested envelope
mutation. The row, builder family, and one-value `radiant_trim_type` option
were therefore removed. Generic teardown still has a direct regression that
strands beam and low-temperature radiant coils and proves the orphan sweep
removes them and their plant.

The NECB boundary is also release-gated rather than inferred from selection
alone. The D-58 selector matrix now covers all 102 inputs in both supported
editions. Every catalog input then passes through full `reference_hvac()`
construction, OpenStudio Model (`.osm`) save/reload, and EnergyPlus forward
translation; the nine distinct four-scenario assignment signatures cover the
remaining office, residential, and data-processing branches. A serial
24-pipeline EnergyPlus gate covers all five modern inputs plus every stable
reference-construction path in NECB 2020 and 2025, requiring clean proposed
and reference sizing runs. A System 2/5 water-coil UA-inversion failure
found while extending that gate predates this catalog work and is tracked in
[#113](https://github.com/canmet-energy/btap/issues/113). The attempted
ideal-loads sizing probe changed code-driven reference sizing without a
decision record, so it was removed from this modeling change rather than
silently establishing new NECB behavior.

## Findings that change the initial outline

| Subject | Verified finding | Consequence |
| --- | --- | --- |
| Chilled beams | OpenStudio 3.11 has `AirTerminalSingleDuctConstantVolumeCooledBeam` with **Active** and **Passive** modes, and a separate `AirTerminalSingleDuctConstantVolumeFourPipeBeam`. | Beams are **air terminals on the ventilation air loop**, not `ZoneHVACFourPipeBeam` zone equipment. Do not build a second DOAS diffuser for the same zone. |
| Radiant | The pinned gem and a published OpenStudio measure build `ZoneHVACLowTempRadiantVarFlow` with hydronic coils and **internal-source surface constructions**. | Constructions and water temperatures are part of the feature, not optional finishing work. |
| VRF heat recovery | `ecm_air.add_outdoor_vrf_unit()` already sets `setHeatPumpWasteHeatRecovery(True)`. Standalone `VRF`, `DOAS with VRF`, and the ECM DOAS+VRF builders use it. The canonical VRF name already says "heat recovery system". | **Do not add a duplicate "VRF heat recovery" row** or turn on a flag that is already on. Phase 2 verifies and documents existing support. |
| Central ERV | The pinned gem adds an air-to-air heat exchanger at the OA system's outboard OA node, with pretreat setpoint control, economizer bypass, and frost protection. | Reuse this *approach* for an opt-in VAV variant; zone ERVs are not a substitute. |
| Dual duct | OpenStudio 3.11 accepts `AirLoopHVAC(model, True)` (two supply outlet nodes) and `AirTerminalDualDuctVAV`; an SDK simulation fixture constructs both decks. | Use the actual two-deck topology. The published measure named "Dual Duct DOAS" instead uses a single-duct VAV loop and zone fan coils; **it is not a dual-duct implementation to port**. |
| UFAD | EnergyPlus needs `RoomAirModelType` and UFAD interior/exterior room-air settings to model stratification. OpenStudio 3.11 exposes those EnergyPlus object types through its IDD and `Workspace` APIs, but not as typed `openstudio.model` classes. Adding them to an OpenStudio Model creates transient generic objects that the forward translator drops; an OpenStudio Model (`.osm`) save/reload turns them into invalid `Catchall` objects. | Warmer supply-air sizing or a plenum alone is **not UFAD**. The available SDK-only path is explicit post-translation workspace injection. A real catalog row remains gated on a first-class, persistent translation contract plus successful stratification simulation. |

**Research pointers (approaches, not code to copy):** [pinned radiant builder][gem-radiant],
[pinned air-loop ERV][gem-erv], [pinned VRF heat recovery][gem-vrf],
[OpenStudio chilled-beam measure][measure-beam],
[OpenStudio radiant+DOAS measure][measure-radiant],
[SDK four-pipe beam example][sdk-beam],
[SDK true dual-duct example][sdk-dual],
[misleadingly named dual-duct measure][measure-dual],
[EnergyPlus room-air models][energyplus-ufad], and an
[IDF/workspace displacement-ventilation measure][measure-displacement].
The measures repository now lives under `NatLabRockies`; these are public
source links pinned to commits. The pinned gem is the *oracle's implementation*,
not a normative source of code requirements. Do not copy Ruby or a measure
into Python; design and test the SDK object graph independently.

## Common contract and release gates

- New public names are explicit `systems.json` rows with `origin: "generic"`,
  required `needs_boiler` flags, and a dedicated `sizing.json` block where
  necessary. Start with representative configurations, not a Cartesian
  product of fuels and chiller labels. `build_system(model, name, zones,
  remove_existing=...)` still serves **only the requested zones**, returns
  the created air loops, and preserves existing names and their topology.
  Validate invalid modes, missing inputs, and incompatible existing equipment
  **before** altering the model; no success-shaped partial builds.
- For each new family/key update `builder.FAMILIES`,
  `canonical.py` (unique canonical names), the closed vocabulary in
  `python/tests/modeling/test_catalog_schema.py`, `catalog_report.py`
  (family/terminal labels and diagrams), `classify.py` (correct
  heating/cooling/plant facts for foreign as well as catalog models), and
  `teardown.py` where new terminals/coils or constructions change replacement
  behavior. Add to `python/btap/modeling/README.md`; leave NECB reference
  selection and existing catalog rows alone. No `article=` citations belong
  in `btap.modeling`.
- Follow the actual test layout, `python/tests/modeling/test_*.py` (there is
  no `tests/modeling/hvac/` directory). Test SDK construction and
  `characterize()` facts, catalog resolution/canonical collisions, report
  rendering, replacing an existing system, and a **subset of zones** with
  adjacent untouched zones. Forward-translate and run sizing plus at least
  one heating and cooling simulation per *shipped* row; require zero
  EnergyPlus Severe/Fatal errors, connected water/air paths, nonzero
  delivered capacity under design loads, and no newly orphaned equipment.
- `python/tests/modeling/test_system_simulation_status.py` expects a verdict
  for **every** catalog name. The original gate was met on 2026-10-12:
  `python/scripts/simulate_all_systems.py` exists, and the committed verdict
  was the output of a real sweep — 97/97 `ok`, 458 s total, sizing only,
  OpenStudio 3.11.0+241b8abb4d, Toronto CWEC2020, on the
  `5ZoneNoHVAC.osm` OpenStudio Model.
  Each row carries its severe and fatal counts, its completion flag and its
  elapsed time, and the file carries a `produced_by` block; the test fails on
  a row claiming `ok` without them. So the hand-written claim turned out to
  be TRUE, and it is now evidence rather than an assertion.

  After the invalid radiant candidate was retired, the complete verdict was
  regenerated on 2026-10-16 from clean source revision `8b0e913`
  (`source_dirty: false`): **102/102 `ok`**, zero failures, 496.0 s total,
  using OpenStudio 3.11.0+241b8abb4d and EnergyPlus 25.2.0-cf7368216c. The
  five shipped modern rows are therefore covered by both this sizing sweep
  and the separate annual operating regression described above.

  A new catalogue row means re-running the sweep and committing the moved
  verdict with the row. `--name` and `--limit` give a smoke run and
  deliberately refuse to write the file, because a verdict is a claim about
  every row and a subset cannot make it. `--check` re-runs and diffs without
  writing. The catalog report also builds *every* row: a diagram error
  is a release blocker, not just a cosmetic concern.
- Run the new focused tests plus existing affected modeling tests, import
  contracts, Ruff, and the SDK/EnergyPlus verification lane. Compare existing
  frozen scenarios; if outputs move, follow the repository's **clean-tree**
  `verification/scenarios/freeze.py` process in the same change. That
  script has **no `--check` flag**. Do not add a baseline for a new system
  unless a scenario actually exercises it.

## Phase 1: chilled beams; radiant candidate retired

**Delivered:** one complete DOAS-based chilled-beam family with active and
passive rows. The hydronic-radiant candidate did not meet the identity and
energy-accounting contract above and was removed rather than shipped as zone
equipment mislabeled as a chiller-led system.

### 1.1 Plant and ventilation foundation

1. The existing `plant_loops.hot_water()` defaults to **82 C** and
   `plant_loops.chilled_water()` to **7 C**. Neither is an appropriate
   *unexamined* default for a radiant cooling slab or chilled beam. Add
   explicit, code-neutral low-temperature heating / tempered-chilled-water
   profiles in `systems/plant_loops.py`, and thread the selected profile
   through `builder.py` for **new rows only**. A loop may be reused only
   when its source, temperature/setpoint profile, and other relevant reuse
   keys match. Preserve the pre-expansion rows' defaults and selection.
   Test two differently tempered systems in one model: they must not
   accidentally share or reprogram one plant loop.
2. Factor the useful DOAS air-loop assembly out of `systems/doas.py` only
   as needed, keeping its existing uncontrolled-diffuser behavior for the
   existing catalog name. New systems require appropriate ventilation
   flow, OA scheduling, a cooling/dehumidification and reheat strategy,
   and zone sizing accounting for the DOAS. A fixed **20 C** neutral
   supply setpoint alone does **not** prove dehumidification. Establish
   control inputs and test latent removal and humidity limits before
   enabling cooled surfaces. Keep water/surface temperatures above the
   measured zone dew point by a **positive, configured margin** while
   cooling is enabled; include a humid-weather simulation/lockout test.

### 1.2 Chilled beams

1. Implement `systems/chilled_beams.py` with a single DOAS air loop and
   one `AirTerminalSingleDuctConstantVolumeCooledBeam` per zone, its
   `CoilCoolingCooledBeam` on the tempered-water loop, and a defined
   heating source (initially electric or hydronic baseboard). Use the
   SDK's `setCooledBeamType("Active"|"Passive")`; the published measure
   uses precisely these modes and puts the terminal on the DOAS loop.
   Both modes need a real primary-air path and separately verified
   ventilation; do not invent a "passive four-pipe zone unit".
2. Add two initial names encoding beam mode and heating source, for
   example `DOAS with active chilled beams and electric baseboards` and
   `DOAS with passive chilled beams and electric baseboards`; retain
   `config` overrides for validated design inputs. After both simulate,
   optionally add a **distinct** four-pipe active-beam variant using
   `AirTerminalSingleDuctConstantVolumeFourPipeBeam`,
   `CoilCoolingFourPipeBeam`, and `CoilHeatingFourPipeBeam`.
   The [SDK fixture][sdk-beam] sets a beam cooling-capacity curve: verify
   its required curve and rated-flow fields and the water-plant connections
   in OpenStudio **3.11**, not just object creation.
3. Tests: two modes produce different terminal settings; exactly one air
   terminal per selected zone and no extra uncontrolled DOAS diffusers;
   the chilled-water coil is on the matching tempered loop, baseboard
   provides heat, and the system passes humid and dry sizing/simulation.
   Replacement must clear beam-specific plant demand components; the
   current teardown's orphan-coil pass handles only ordinary water coils.

### 1.3 Hydronic radiant floor candidate — retired

The criteria below governed the attempted implementation. Its object graph,
surface restoration, condensation control, and comfort result worked, but the
annual energy split did not: DX carried most cooling and ground conduction
carried most slab heat. Because the standard fixture has no insulated
slab-on-grade and HVAC authoring must not alter its envelope, no radiant row
ships from this phase.

1. Implement `systems/radiant.py`: a DOAS for ventilation/latent control
   plus one `ZoneHVACLowTempRadiantVarFlow` per zone, with
   `CoilHeatingLowTempRadiantVarFlow` and
   `CoilCoolingLowTempRadiantVarFlow` on correctly controlled hydronic
   loops. Use temperature/setpoint schedules and a verified heating vs
   cooling lockout. The [pinned gem][gem-radiant] and
   [published measure][measure-radiant] provide object-graph examples;
   their climate-zone assumptions, EMS controls, and water temperatures
   are **not** generic values to port verbatim.
2. Preflight the target floor surface(s), existing opaque constructions,
   adjacent/reverse surfaces, plant profile, and control schedules.
   Install a `ConstructionWithInternalSource` on each intended floor
   surface **without mutating shared constructions or unrelated zones**.
   Insulation/layer and design-water choices are explicit code-agnostic
   inputs; never quietly pick an ASHRAE climate-zone R-value for a NECB
   model. For an interzone slab, either account for both sides with
   appropriate paired constructions or reject a selection that would
   silently alter an unselected zone. Record enough provenance to restore
   builder-owned surface changes when replacing the system, without
   overwriting later caller edits.
3. Start with a named DOAS + hydronic **floor** configuration. Add ceiling
   only after demonstrating a compatible interior/exterior
   internal-source construction, reverse surface behavior, and simulator
   operation; a water cooling panel is a **different** SDK object and
   must not be advertised as a hydronic slab without testing. Ensure a
   later envelope pass does not overwrite the embedded source: test the
   documented geometry -> loads -> HVAC -> envelope composition, or
   explicitly document/enforce a different ordering.
4. Tests: every selected surface has a valid internal source; a missing
   slab/construction or invalid water temperature fails clearly **before
   mutation**; humid cooling never operates below the dew-point margin;
   sizing and heating/cooling simulations actually deliver loads. Test
   `remove_existing` on a subset with a shared adjacent surface, plus
   cleanup of radiant coils and prior constructions.

**Phase 1 exit:** one active- and one passive-beam row pass the common gates
above. Four-pipe beams remain a conditional addition. A future radiant row
needs an independently justified insulated-envelope preflight and must show
that the named hydronic equipment, rather than hidden DX capacity, carries the
load.

## Phase 2: central VAV energy recovery; verify existing VRF heat recovery

### 2.1 VAV with an air-loop ERV

1. Add opt-in `needs_erv` variants of a **small number** of existing
   `vav_reheat` rows in `systems.json`; do not change existing rows.
   In `systems/vav_reheat.py`, install one
   `HeatExchangerAirToAirSensibleAndLatent` per grouped air handler
   onto its `AirLoopHVACOutdoorAirSystem` at the outboard OA node.
   Central ERV is not `ZoneHVACEnergyRecoveryVentilator`.
2. Adapt the [pinned gem's approach][gem-erv] to SDK-only code:
   sensible/latent effectiveness, appropriate exhaust/relief path,
   `SetpointManagerOutdoorAirPretreat`, frost control, and economizer
   lockout / OA-controller bypass. Use explicit, validated parameters
   rather than inventing a standards-mandated default. Do not insert
   another exchanger if an OA-system exchanger is already present;
   distinguish catalog-selected ERV from any ERV added later by a
   code-driven efficiency pass. Update `naming.py`/report labeling
   (`sys_hr`) so the extra component is observable.
3. Tests: compare flagged and original rows; identical served zones and
   air-loop count, **one** properly connected exchanger per loop only
   on flagged rows, effective heat exchange under opposite OA/return
   conditions, sensible/latent settings, bypass/frost controls, and
   intact VAV reheat, OA sizing, and teardown. Forward translation
   must show both HX air streams, not just an unattached object.

### 2.2 VRF heat recovery: regression and documentation, not a new builder

1. Add assertions to `python/tests/modeling/test_vrf_erv_gshp_composites.py`
   and the ECM VRF tests that the outdoor unit's
   `heatPumpWasteHeatRecovery()` is true for `VRF`, `DOAS with VRF`,
   and the ECM variants; terminal OA must remain autosized for
   standalone VRF and near zero when DOAS supplies ventilation.
2. Add an opposing-zone heating/cooling simulation to check the
   simultaneous-operation path where test weather/loads permit it.
   Explain the existing behavior in `python/btap/modeling/README.md`.
   A **heat-pump-only** (non-heat-recovery) VRF would be a *new*, clearly
   named option if requested later: the [pinned gem's generic VRF
   helper][gem-vrf] exposes the boolean, while our existing ECM
   helper deliberately defaults to recovery.

**Phase 2 exit:** central-ERV VAV names simulate without changing existing
VAVs; VRF heat recovery is accurately documented and regression-pinned,
with **no duplicate catalog name**.

## Phase 3: real dual-duct VAV; feasibility-gated UFAD

### 3.1 Dual-duct VAV

1. Implement `systems/dual_duct.py` using the [OpenStudio two-deck SDK
   fixture][sdk-dual]: `AirLoopHVAC(model, True)` gives hot and cold
   `supplyOutletNodes()`; put a controlled heating coil and setpoint on
   one deck, a controlled cooling coil and setpoint on the other, an OA
   system and fan upstream, and an `AirTerminalDualDuctVAV` on each
   selected zone. An in-memory SDK 3.11 probe confirms two outlets and
   initialized hot/cold inlets after `addBranchForZone`. **Do not**
   substitute `AirTerminalSingleDuctVAVHeatAndCoolNoReheat`.
2. Start with one explicitly named combination and plant sources supported
   by existing helpers; add boiler/chiller, electric/DX, or district
   variants only after those particular coils simulate. Put separate
   deck-temperature/setpoint and air-flow design inputs in a dedicated
   sizing block; extend `BaseSystem.apply_system_sizing` only if the
   two-deck fixture demonstrates a missing SDK sizing field, preserving
   existing single-deck behavior. Keep served-zone grouping
   code-neutral rather than importing NECB's system-6 facade grouping.
3. Test both decks in the translated EnergyPlus model, independent hot
   and cold setpoints, both terminal inlets, mixing and OA delivery in
   opposing-load zones, plant connections, exact returned loop count,
   classification, catalog diagram, and subset teardown. Reject the
   [published "Dual Duct DOAS" measure][measure-dual] as a topology
   oracle: it explicitly installs VAV no-reheat terminals and separate
   [four-pipe fan-coil zone equipment][measure-dual-fancoil], not
   dual-duct terminals.

### 3.2 UFAD: workspace translation gate before any public row

1. Prototype a **genuine** UFAD model on a small plenum + occupied-zone
   fixture: supply/return connections and EnergyPlus
   `RoomAirModelType` plus `RoomAirSettings:UnderFloorAirDistributionInterior`
   or `...Exterior`. The [EnergyPlus reference][energyplus-ufad] says
   omitting `RoomAirModelType` yields well-mixed room air. Measure
   occupied-level and return-level temperatures to show stratification;
   a higher `Sizing:Zone` supply temperature or ventilation effectiveness
   alone does **not** pass.
2. Treat the OpenStudio 3.11 capability split as established evidence:
   `IddObjectType` resolves `RoomAirModelType` and both UFAD settings
   objects, and a translated EnergyPlus `Workspace` accepts them while
   remaining Draft-valid. The typed `openstudio.model` API has no
   `RoomAir*` classes. Generic additions to a `Model` are silently omitted
   by `ForwardTranslator`; saving and reloading that OSM converts them to
   invalid `Catchall` objects. Therefore do not wait for a workspace
   capability that already exists, and do not mistake it for persistent
   OpenStudio Model (`.osm`) support.
3. Before adding a catalog row, make the workspace path a deliberate
   product contract. Either require a self-contained OpenStudio Model
   (`.osm`) and defer UFAD until typed model support exists, or add a
   first-class SDK-only
   post-translation stage that persists inspectable UFAD intent and
   parameters on the model and injects the EnergyPlus objects in every
   supported export and simulation path. It must fail visibly when that
   stage is bypassed, inject each object exactly once, and expose the
   limitation that an ordinary external OpenStudio Model (`.osm`)
   translation cannot reproduce UFAD. The remote
   `workflow_type="openstudio"` backend also uploads the model unchanged
   and bypasses local workspace augmentation. The
   [displacement-ventilation measure][measure-displacement]
   demonstrates the post-translation approach, but an EnergyPlus workspace
   measure is not permitted as a hidden product dependency here.
4. Once that contract is approved and implemented, add
   `systems/ufad.py` using explicit plenum/zoning preconditions (no
   silent geometry creation), diffuser and return locations, room-air
   parameters for interior/exterior zones, and purpose-specific sizing.
   Validate missing plenums, persisted intent, injected IDF objects,
   warm-supply cooling loads, occupied/return temperature gradients, both
   zone types, `classify`, subset replacement, and the full
   catalog/simulation-status gates. An independently named *underfloor
   supply/plenum, well-mixed zones* approximation would need its own scope
   decision and explicit limitations; it cannot satisfy this gate.

**Phase 3 exit:** a real, simulated two-deck VAV row ships. UFAD ships
**only** if the workspace translation contract and room-air simulation gates
pass; otherwise Phase 3 closes with the specific unresolved contract or SDK
blocker documented and *no misleading catalog entry*.

## Delivery sequence and boundaries

1. Land Phase 1 plant/DOAS moisture controls, then chilled beams, then
   radiant surfaces; the last step depends on the safe-temperature
   plumbing. Phase 2's VAV ERV can proceed independently. Phase 3's
   dual-duct builder can proceed after SDK-fixture verification; UFAD
   feasibility should be investigated before any promised release date.
2. For each slice, record the catalog rows, modeled plant
   temperatures, ventilation/latent strategy, construction assumptions
   (where applicable), simulation evidence, and known exclusions in
   `python/btap/modeling/README.md`. This document records the acceptance
   contract and implemented outcome.
3. Displacement ventilation, absorption/heat-recovery chillers, and
   CHP/cogeneration remain outside phases 1-3. In particular, a
   heat-recovery **chiller** is not VRF heat recovery, and CHP is a
   generation/plant feature rather than a zone-system catalog row.

[gem-radiant]: https://github.com/NatLabRockies/openstudio-standards/blob/f01da13a6b89e45761d1ede481fedb1c1aeb6ea0/lib/openstudio-standards/prototypes/common/objects/Prototype.hvac_systems.rb#L4832-L5250
[gem-erv]: https://github.com/NatLabRockies/openstudio-standards/blob/f01da13a6b89e45761d1ede481fedb1c1aeb6ea0/lib/openstudio-standards/standards/Standards.AirLoopHVAC.rb#L1805-L1894
[gem-vrf]: https://github.com/NatLabRockies/openstudio-standards/blob/f01da13a6b89e45761d1ede481fedb1c1aeb6ea0/lib/openstudio-standards/hvac/components/air_conditioner_vrf.rb#L70-L78
[measure-beam]: https://github.com/NatLabRockies/OpenStudio-measures/blob/8787577a470624cf6b2a6fcf7081e5aa81f2c96b/xcel_published/ChilledBeamwithDOAS/resources/OsLib_HVAC.rb#L1050-L1065
[measure-radiant]: https://github.com/NatLabRockies/OpenStudio-measures/blob/8787577a470624cf6b2a6fcf7081e5aa81f2c96b/nrel_published/AedgOfficeHvacRadiantDoas/resources/os_lib_hvac.rb#L1407-L1440
[sdk-beam]: https://github.com/NatLabRockies/OpenStudio-resources/blob/0348c6b5eda20bb379b3e88aca4444770282cd40/model/simulationtests/airterminal_fourpipebeam.rb#L98-L132
[sdk-dual]: https://github.com/NatLabRockies/OpenStudio-resources/blob/0348c6b5eda20bb379b3e88aca4444770282cd40/model/simulationtests/dual_duct.rb#L22-L65
[measure-dual]: https://github.com/NatLabRockies/OpenStudio-measures/blob/8787577a470624cf6b2a6fcf7081e5aa81f2c96b/nrel_published/AedgK12HvacDualDuctDoas/resources/os_lib_hvac.rb#L1038-L1060
[measure-dual-fancoil]: https://github.com/NatLabRockies/OpenStudio-measures/blob/8787577a470624cf6b2a6fcf7081e5aa81f2c96b/nrel_published/AedgK12HvacDualDuctDoas/resources/os_lib_hvac.rb#L1442-L1478
[energyplus-ufad]: https://github.com/NatLabRockies/EnergyPlus/blob/2c8aa53c3b6e0bfa6848743054507535ec95fcf5/doc/input-output-reference/src/overview/group-room-air-models.tex
[measure-displacement]: https://github.com/NatLabRockies/OpenStudio-measures/blob/8787577a470624cf6b2a6fcf7081e5aa81f2c96b/xcel_published/ChangeOverheadVentilationtoDisplacementVentilation/measure.rb#L143-L173
