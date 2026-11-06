**Verdict: "record absence explicitly" is not the common root cause. You are seeing a real family of failures, but explaining it too narrowly.** The broader failure is that the round trip has no enforced semantic-preservation contract: facts can be omitted from the representation, discarded between layers, applied to the wrong targets, or outweighed by unrelated matching credits. Explicit absence addresses the first mechanism, not the other three. In particular, #219 had the values already, and #220 has the empty air-loop list already. Those are counterexamples to absence-recording as the common cure.

## 1. Verdict and evidence

The concrete mechanisms differ:

- `python/btap/stock/identify.py:637-650`: candidate scoring selects `group['descriptive']` rather than the enclosing group, discarding sibling facts such as `air_loops`. It then scores every row admitted by `family_guess`. The issue is the consumer's evidence boundary, not necessarily the writer's failure to observe.
- `python/btap/stock/identify.py:245-251`: the scorer explicitly declares that disagreements do not disqualify. Therefore even a perfectly observed absence does not prevent invention.
- `python/btap/stock/reader.py:283-319`: the controls reader takes the first economizer row, then applies it model-wide. Forwarding the missing limits fixes one information-loss boundary but does not fix the loss of target scope.
- `python/btap/stock/reader.py:578-581`: only unresolved HVAC groups enter candidate construction. Improving the identifier cannot repair all reconstruction paths.

These are related architectural failures, not four unrelated bugs. But the useful unifying concept is **evidence-preserving reconstruction**, not **negative fact collection**.

| Case | Actual architectural mechanism | Would explicit absence alone prevent it? |
| --- | --- | --- |
| #216, opaque doors | A physical category was misrepresented. The current writer branches on construction opacity (`python/btap/stock/envelope.py:252-260`), whereas the reader chooses its construction operation from the recipe category (`reader.py:161,194-196,227,250-252`). | No. A typed opaque/glazed distinction and preservation check are needed, not a growing list of things a door lacks. |
| #214, phantom HRV | An omitted observable distinction, a catalogue coverage gap, and compensating scores. | It distinguishes the candidates, but a finite penalty still permits the contradiction to win. |
| #219, economizer limits | Values were observed and serialized, then not forwarded to the applying operation. | No; absence was not the missing information. |
| #220, phantom MAU | A recorded topology fact is excluded from scorer input, and a zone-device kind is equated with a larger system family (`identify.py:74-75,265-268,639`). | No; `air_loops: []` is already explicit. |

Two direct disagreements with your framing:

- **The classifier already records many negatives.** `python/btap/modeling/hvac/classify.py:644-678` initializes `heated`, `cooled`, `heat_pump`, `loop_dx_cooling`, `loop_hydronic_cooling`, `packaged_unitary`, `ventilation_sized`, and `dcv` as false, among other explicit empty/absent values. These are scan accumulators, not a satisfactory general representation of observation completeness, but "almost never records what it lacks" is too strong. Daylighting also records an explicit empty inventory (`python/btap/stock/controls.py:158-165`). Economizers are not the sole exception.
- **The quoted destruction of facts is not a proof that structural reconstruction is inherently unreliable.** `python/btap/modeling/hvac/classify.py:462-474,492-511` explains a particular lossy flattening pass and already works around it by reading equipment identity before flattening. There are genuine irrecoverable distinctions in arbitrary models; this passage does not establish that every observable structural contradiction must remain a guess. The stock-layer rationale generalizes a local representation loss into a broad impossibility claim.

There is also an important protection your framing underplays: candidates are opt-in on BOTH writing and reading (`python/btap/stock/writer.py:16-17,49-56`; `python/btap/stock/reader.py:522-534`). The scorer is documented as a suggestion mechanism, not an exact classifier. The defect is not that a search tool can display an imperfect alternative; it is that a blanket `accept_candidates=True` makes the first alternative executable without a separate compatibility decision (`reader.py:489-505`).

One factual correction to "a faithful alternative existed" in every case: the committed HRV regression explicitly says no faithful **catalogue row** existed before the new row (`python/tests/stock/test_heat_recovery_is_not_invented.py:13-16`; `python/btap/modeling/hvac/data/systems.json:1039-1050`). A faithful physical composition or primitive implementation may have existed, but that is different from an alternative the old selector could return. This is partly an expressiveness problem, not only an observation problem.

## 2. Facts and weights

Adding an observable fact is useful. Making a known structural contradiction merely another finite score term is not a sound way to guarantee faithful construction. Keep ranking for suggesting alternatives; separate it from determining whether an alternative is compatible with the observed building.

**As a recommender, heuristic weights are defensible. As a reconstruction validity test, this score is unsound.** The constants have no stated calibration or loss function. Related evidence is counted repeatedly: a DX loop and a row with `cooling=True` get loop-cooling credit and another cooling credit (`identify.py:327-355`); hydronic heating, matching boiler fuel, and needing a boiler can all add credits for overlapping evidence (`identify.py:437-440,463-496,511-524`). Thus magnitudes depend partly on how a row spells its configuration, not solely on physical similarity. A new unrelated positive can pay for an invented device.

The epistemic policy is also backwards in one place: `family_guess` hard-filters entire catalogue families (`identify.py:639-648`), while observed disagreements only lower scores (`identify.py:242-250`). Guesses can exclude the right answer, but measurements cannot exclude a wrong one.

Replace the single ordering with:

1. **Compatibility:** compare measured, scoped structural facts against proposed build effects. Contradictions are a set of named changes, not a scalar. Unknowns remain unknown; they are neither agreement nor observed absence.
2. **Selection:** rank compatible plans for convenience. If none exist, say "no compatible plan"; optionally display incompatible alternatives separately with their required substitutions. Do not lower the validity standard just because the catalogue is incomplete.
3. **Authorization:** distinguish selecting a candidate from approving its specific differences. An explicit retrofit may legitimately add HRV; a reconstruction must not silently do so. The same compatibility check must also apply to named/resolved systems and caller-supplied selections.

Do not simply change -2.5 to a very large negative number, or reject everything with an `against` string. Some current objections are themselves false (the chilled-water example below), and guessed facts must not acquire hard authority by accident.

Nor does recording a negative automatically preserve its meaning downstream. The current HRV branch interprets missing, null, and false identically (`identify.py:586-587`). Its objection then asserts "the loop carries no air-to-air heat exchanger" even for older/manual fact dictionaries that never examined recovery. OA scoring similarly treats an omitted `system_outdoor_air_method` as measured no-OA (`identify.py:393-405`). The representation and every consumer must agree on what unknown means.

## 3. Structural direction

Introduce an explicit compatibility/build-plan boundary: distinguish observed facts from unknowns and guesses, retain their scope, compare source requirements against the actual builder's normalized effects, and require an explicit substitution decision for contradictions. A complete raw equipment inventory alone is insufficient: the same equipment can be connected differently, and the same controls can be assigned to the wrong loops.

**I disagree with a complete SDK-object inventory as the necessary starting point, and with "no additions" as the whole invariant.** The product deliberately transfers generic recipes between geometries. Counts and individual objects cannot be identical in that use case; removals, fuel substitutions, changed control limits, and reassigned service relationships can be just as consequential as additions. A disabled SDK placeholder heating coil is not equivalent to an active source of heat either (`python/btap/modeling/hvac/systems/zone_terminal.py:55-59`).

The bounded representation should describe **service topology and behavior**: central air services, terminals, supplementary zone equipment, plant sources, and controls attached to those services. Keep loop-side, terminal-side and zone-side heating/cooling distinct. Give each observation a scope and coverage status: observed value/presence, observed absence, or unknown/unreadable with a reason. Establish absence only for a domain the extractor actually covered.

Deduplicate descriptions, not assignments. A reusable system template can serve many instances, while a separate binding retains which zones belong to which original loop and which zones have supplementary devices. That preserves the generic recipe goal without serializing every SDK object.

The catalogue/builder should expose one normalized build description with defaults and composite parts resolved. The scorer should consume it instead of implementing a second, partial interpretation of builder behavior. There is already a symptom of that duplication: `_BUILDER_COIL_DEFAULTS` mirrors builders (`identify.py:124-142`), and `_row_heating_media` separately resolves composites (`identify.py:178-240`). Start by factoring the configuration resolution shared with `python/btap/modeling/hvac/builder.py:136-142`; do not create a third handwritten table of claimed effects.

Use the existing non-mutating builder preflight as a foundation (`builder.py:72-96,141-146`), not as evidence that no gates exist. A recipe-level planner additionally needs to resolve target bindings and compatibility before mutation. Build on a disposable model, compare the resulting bounded semantics, and publish only an accepted result. Every recipe field should end with a structured disposition: applied to named targets, explicitly aggregated, unsupported, or refused. Otherwise adding a writer field can remain a silent reader no-op indefinitely.

The precise contract should be: **for each supported observed property at its bound scope, the rebuilt value equals the declared reconstruction target, or an explicit accepted transformation accounts for the difference.** That target may intentionally be an aggregate. A topology mismatch cannot be offset by a numerical match elsewhere. Unknown required properties prevent a *verified reconstruction* claim; a representative build can still proceed if its unverified assumptions are explicitly accepted and its output is labelled accordingly.

This is a limited analogy to the NECB fatal gates, not a reason to import their policy wholesale. Stock is intentionally a separate layer and supports approximate/retrofit work. Refuse an unsupported claim of fidelity or an unapproved transformation; do not outlaw every disclosed approximation. Keep mechanical build descriptions in `modeling`, and the stock-specific preservation policy in `stock`.

The reader currently mutates loads and envelope before any candidate building (`reader.py:549-560`), catches builder failures and continues (`reader.py:497-504`), and returns a partial account (`reader.py:606-610`). Existing builder preflight checks known requirements before teardown, which is good. It does not make the whole recipe application transactional, nor roll back an unexpected later build failure. A new "refusal" rule must be positioned before publication/mutation of the caller's model, not merely appended to that final list.

Finally, test preservation at the boundaries. Writer-only round trips cannot certify reconstruction; `python/tests/stock/test_round_trip.py:1-12` explicitly describes only model-to-recipe coverage. Exercise source -> recipe -> a separately prepared target -> semantic comparison, with deliberately different target defaults. Include paired models differing only in one feature, heterogeneous multi-loop cases, unknown equipment, and removal as well as addition. Compare the properties that were promised, not just catalogue names, score ordering, or annual energy (errors can cancel).

Two precautions matter:

- A source and result compared through the SAME lossy extractor can agree while sharing the same blind spot. Builder contract tests must inspect actual relevant SDK objects/relationships and, where translation changes physical categories, the translated IDF. Tests of opaque doors already demonstrate why an unchanged OSM subtype is insufficient.
- Validate the fact vocabulary. `python/tests/stock/test_heat_recovery_is_not_invented.py:80-85` supplies `heat_fuels`, `cool_fuels`, `loop_hydronic_heating`, and `baseboard_media`, which are not the corresponding fields the scorer reads. Those tests exercise recovery ordering without the intended full fuel/media context. A typed/validated fact shape would expose that immediately rather than letting misspelled or obsolete evidence disappear.

**An incremental path, not a rewrite:** first introduce the compatibility result and scoped observation shape for central-loop presence, recovery, cooling location, and zone-device assignments; preserve instance bindings through the existing signature deduplication; normalize the builders used by those cases and gate candidate acceptance; then extend the same field-disposition contract to controls and envelope. Reuse the existing composite build path (`builder.py:147-163`) for approved combinations. One `build_system` call can already build several parts, so "one selected row" is not inherently "one device"; the limits are what those parts can express and whether they all get applied to the same zone set.

## 4. Additional findings

### A. A chilled-water loop is described to the scorer as zonal-only cooling

`python/btap/modeling/hvac/classify.py:1083-1088` sets `loop_hydronic_cooling=True` for a hydronic cooling coil. `python/btap/stock/hvac.py:35-48` drops that field from the descriptive schema. Then `python/btap/stock/identify.py:327-339` defines loop cooling as **DX only**, and treats electrical cooling without DX as zonal cooling. An electrically chilled-water-cooled air handler with no zonal cooling therefore receives the explicit but false objection that its loop has no cooling coil. Even passing the missing hydronic fact to `_score` would not fix this: the scorer does not read it. This is a concrete counterexample to "just add another absence flag."

Do not mechanically repair that by OR-ing the two booleans: `_terminal_facts` also calls `_scan_cooling_component` for terminal-side cooling (`classify.py:1368-1372`), which sets that same hydronic flag. A genuinely scoped supply-cooling observation is the better contract.

### B. Economizers and DCV lose their attachment scope

`python/btap/stock/controls.py:121-153` writes separate controller values per loop. `python/btap/stock/reader.py:283-321` takes the first loop's economizer type and limits, applies them to all loops, and enables DCV everywhere if ANY source row enables it. Explicit `dcv_enabled=False` is never applied as a disable. `python/btap/modeling/hvac/ventilation.py:204-224` confirms the economizer primitive is intentionally model-wide; this is a wrong choice of operation by the reader, not a primitive bug.

Thus a mixed `NoEconomizer` / economizer building becomes homogeneous according to the first row; one DCV zone group changes unrelated groups. This is not a disclosed aggregate: there is no per-loop rejection or aggregation warning.

### C. "Null stays absent" is not guaranteed by skipping the setter

`python/btap/stock/reader.py:295-312` excludes null limits, and `python/btap/modeling/hvac/ventilation.py:165-176` only sets non-null limits. If the target already carries a limit, an observed unset source limit leaves that target value in place. The new tests start with an unset target (`python/tests/stock/test_economizer_limits_round_trip.py:87-133`), so they do not establish the claim on a populated target. This requires distinguishing **unset this field** from **do not touch this field**, not only distinguishing absence from unknown when reading.

### D. A resolved HVAC group is not reconstructed or reported

`python/btap/stock/hvac.py:109-111` emits a resolved group's `system`; `python/btap/stock/reader.py:578-581` builds only unresolved groups. There is no corresponding resolved-system build path. Applied/skipped/refused accounting therefore omits those systems entirely. On a target retaining the source HVAC this can look correct; on replacement geometry it leaves the requested system unbuilt. Fixing candidate scoring cannot address this path.

### E. Generic grouping discards topology, not just redundant descriptions

`python/btap/stock/hvac.py:80-106` merges identical descriptions and accumulates flat zone and loop-name lists, without retaining the mapping between them. `python/btap/stock/reader.py:480-499` builds one selected system over that union. For a shared-loop builder, multiple identical source loops become one shared loop. Even perfect inventory counts would not restore the original zone-to-loop assignment once it has been discarded.

An earlier loss occurs within a loop: `python/btap/modeling/hvac/classify.py:1400-1413` unions zone equipment kinds into one group-level list. If only two of four zones have PTACs, this says only "group has PTAC." A builder such as `python/btap/modeling/hvac/systems/mau_ptac.py:81-96` installs one in every selected zone. Rejecting central MAUs for a zonal-only group fixes #220 but not this separate equipment-spreading mechanism.

### F. Setback schedules are changed, even for simple supported schedules

`python/btap/stock/controls.py:60-66` calls the maximum value "occupied" for BOTH heating and cooling and records only the end time. `python/btap/stock/reader.py:268-273` reconstructs occupied time starting at midnight. Heating steps `(07:00,16 C), (18:00,21 C), (24:00,16 C)` become occupied at 21 C from midnight through 18:00, adding seven occupied-temperature hours. Cooling steps `(07:00,28 C), (18:00,24 C), (24:00,28 C)` are mislabelled with 28 C as occupied and end time 07:00, then rebuilt at 24 C for the rest of the day. These are supported two-value profiles, not obscure EMS schedules.

The reader also writes setpoints model-wide (`reader.py:278-280`); the underlying primitive creates thermostats where absent (`python/btap/modeling/hvac/thermostats.py:118-123,155-168`). Thus a building with a thermostat on one zone does not imply permission to equip every previously floating zone.

### G. Fenestration optical values are written but not consumed

`python/btap/stock/envelope.py:260-266` emits `shgc` and `visible_transmittance`. `python/btap/stock/reader.py:224-255` applies only U. The called primitive takes SHGC and visible transmittance from the **target's existing construction**, not from the recipe (`python/btap/modeling/envelope/constructions.py:515-521`). Different target glazing therefore survives with the wrong optical properties without an unsupported-field report. This is another #219-shaped reader omission that an equipment inventory cannot catch.

### H. Some tests encode the abstraction error rather than challenge it

`python/tests/stock/test_identify.py:142-148` explicitly expects a PTAC group to select the campus MAU row. That fixture never establishes central-loop presence. `python/tests/stock/test_equipment_and_hvac.py:152-174` establishes that four loops collapse to one description but does not check that their four service assignments can be reconstructed. These are not arguments against either useful test in isolation; they explain why a suite can stay green while the architecture invents services. Add invariants around the information being preserved, not just examples of the current selection or compression.

**Scope and confidence:** This is a read-only source review of the files present during this session; only this requested review file was written. The reported data-flow defects are supported by the cited executable paths. I have not independently reproduced the stated GJ/year effects or run EnergyPlus. An attempted lightweight check could not import OpenStudio under the default Python, and execution of the existing virtual-environment interpreter was denied by the tool permissions; I did not install packages or work around that restriction. The schedule examples are direct evaluations of the source formulas, not claimed simulation measurements.

**Bottom line:** keep fact extraction, stop using score compensation as permission to change observed physics, and preserve the bindings that make a fact meaningful. Your four fixes are useful repairs, but the structural work is a scoped semantic contract across extraction, aggregation, selection, construction, and verification.
