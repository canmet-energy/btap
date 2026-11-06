**Verdict: replace "flat facts -> best catalogue row -> build" as the primary stock-generation architecture. Retain the catalogue, reuse the builders, and retain `classify` for its existing consumers while introducing a scoped observation path for stock.** The appropriate stock unit is a parameterized service template plus an explicit policy for assigning and scaling it on the target geometry. A catalogue row is a useful named preset, not the language in which every observed building must be expressible. My earlier compatibility proposal is a useful migration guard, but putting it around the existing row selector alone would make an under-expressive architecture safer, not make it the right architecture.

## 1. The architectural choice

The desired separation is:

```text
source OSM
  -> scoped observations of services, equipment, controls and relationships
  -> portable recipe: service templates + explicit transfer assumptions
target geometry + target semantic bindings
  -> concrete service assignments and validated build plan
  -> existing modeling builders/components
  -> comparison against the instantiated plan
```

This is not a per-object clone and does not require the destination's zone names or zone count to match the source. It also does not require deleting the existing catalogue or moving NECB policy into `stock`.

The repository already has more of the assembly machinery than the fixed-row framing suggests: `python/btap/modeling/hvac/builder.py:97-129,136-142` accepts configuration overrides, and `:147-163` builds composite parts. The limitation is not simply "only 110 machines can be built." It is that the stock path chooses a row and passes only its name and a list of zones (`python/btap/stock/reader.py:497-507`), while the observations have already lost distinctions and bindings (`python/btap/stock/hvac.py:80-115`).

**Correction to my earlier review:** retaining source zone-to-loop assignments is useful evidence and supports same-geometry validation, but is not a sufficient portability design. For building B, those assignments must be replaced by an explicit transfer policy. Source bindings are provenance, not destination selectors.

This is not a wholesale replacement of working SDK code. It replaces the **inference and orchestration path** above that code. "Observe -> abstract -> instantiate" is basically right; "classify -> choose nearest preset" is the wrong specialization of that idea for this product.

**When would I keep the current approach?** If the product deliberately said "classify this building into one of our finite archetypes, then replace its systems with that archetype," a curated catalogue plus an explainable recommender would be a reasonable, much cheaper design. Fixed presets also have a valuable advantage: a finite set can be exercised exhaustively. But the defects you identify are treated as defects precisely because observed equipment and controls were not supposed to be replaced that way. Geometry portability does not imply permission to change independent physical choices. A bounded parameterized language is justified by that distinction, not by a general preference for more abstraction.

The cost is real: more explicit input, runtime validation, and interaction testing, plus some honest unsupported results where the present code always finds a plausible candidate. I would accept that cost incrementally. I would not promise that parameterization makes every OSM faithfully transferable or that a one-week slice replaces the whole stock reader.

## 2. (a) Catalogue rows: keep the presets, stop making them the recipe language

**Yes, parameterized system descriptions are the better primary representation for stock.** Fixed bundles are useful for a curated catalogue, examples, stable public names, and NECB reference construction. They are the wrong exhaustive vocabulary for describing arbitrary existing buildings.

The concrete coupling is visible, not hypothetical: `python/btap/modeling/hvac/data/systems.json:999-1050` has a base PVAV row, a plate-HRV row that also selects hot-water baseboards, and the newly added baseboard/no-HRV row. But the VAV builder already treats the choices separately: `systems/vav_reheat.py:333-336` adds recovery conditionally, and `:346-348` adds the selected baseboards. The missing combination was largely a limitation of the selection interface, not a missing machine-building capability.

For that specific combination, selecting a known VAV backend with explicit `baseboard_type='Hot Water'` and `needs_erv=False` is conceptually sufficient; the writer should not need a new globally named catalogue item to express it. A normalized recipe should expose the physical choices, not these legacy field spellings, and its backend adapter should produce the validated configuration.

**Do not replace 110 rows with an unrestricted bag of keyword overrides.** Parameterization expands the possible state space, including invalid or unimplemented combinations. It removes the need to enumerate every combination as a product, not the need to validate interactions. Use a small set of typed topology templates with supported options and prerequisites, not arbitrary mixing of all SDK components.

Several existing details make that qualification essential:

- `builder.py:136-138` merges arbitrary configuration keys, while `systems/base_system.py:34-37` supplies a no-op default preflight. There is no universal "every requested option was consumed" check.
- The catalogue key allowlist is a TEST over shipped rows, not a runtime contract for user overrides (`python/tests/modeling/test_catalog_schema.py:1-9,151-158`). A new recipe API must validate keys and cross-field combinations at runtime. `python/btap/modeling/hvac/performance.py:61-78` already provides a useful local precedent for rejecting unknown authoring inputs.
- Your `needs_erv` observation is supported: the system-builder reads of that key are in `systems/vav_reheat.py:59-60,333,372`. It is not a universal HVAC option just because it has a generic-looking name. A non-VAV recovery request must reach an implemented compatible attachment path or fail as unsupported; passing the flag through is not implementation. Other recovery topologies may exist independently of that flag.
- The current composite backend applies every part to the SAME `zones` argument (`builder.py:151-163`). A central service for four zones plus PTACs for two requires separate service bindings, not simply another composite row.

### What happens to NECB and its golden?

**Nothing needs to be removed or re-adjudicated just to add this stock path.** Preserve the named catalogue API and existing preset behavior. Add a validated parameterized build entry point alongside it, sharing the existing build implementation where safe. Eventually a named row can be an adapter into that representation, but converting every row is not a prerequisite for the first stock implementation.

The current dependency trace matters:

1. NECB consumes `characterize` facts, then applies its OWN rule selector (`python/btap/codes/necb/hvac/reference.py:97-126`). It does not depend on stock's fuzzy scorer.
2. Its finalization already produces both a catalogue name and a configuration (`reference.py:912-915`), and the build call passes that configuration (`:1518-1520`). Parameterization is therefore not foreign to the NECB consumer; it is already part of its public builder use.
3. The matrix's per-row path builds a shipped row as a proposed model, characterizes it under both retained and scrubbed names, and compares reference assignments in both editions (`python/tests/necb/test_hvac_reference_selection_matrix.py:127-176,186-220`). The normal run uses a representative subset; `FULL_MATRIX` selects all rows (`:96-110`). It separately demands that every catalogue name has adjudicated coverage (`:240-247`). Keep those requirements intact.

A recipe-authored parameter combination need not become a new shipped catalogue product. It is an authored model input, just as a foreign OSM is. That does NOT mean it inherits adjudicated behavior from the preset it resembles. If a resulting model later enters compliance, it must traverse normal characterization, input gates, and NECB selection. New advertised stock template capabilities need focused integration coverage; anything promoted to a new catalogue row still needs the existing adjudication.

The golden is not an exhaustive physical correctness oracle for arbitrary parameter combinations: its compared assignment keys are `system`, `action`, `energy_type`, `catalog`, and `blocks` (`python/tests/necb/reference_matrix_support.py:18`). Preserving those outputs is necessary when refactoring shared code, but does not prove that controls, curves, plant sharing, or all equipment outputs stayed identical. Retain the builder/engine/frozen-scenario checks too. Never regenerate the adjudicated matrix to make a refactor pass.

### A deeper backend limitation than row count

Parameterized rows alone still inherit hidden topology policy. `VAVReheat.build` calls `_zone_groups`, which separates underground zones and, above four storeys, groups by facade orientation (`systems/vav_reheat.py:216-270`). Passing an explicit target group does not necessarily mean "build exactly one loop for this group." Likewise, hot-water construction defaults to compatible-plant reuse (`systems/plant_loops.py:613,636-639,652-671`), so separate service calls can share a plant without that sharing being expressed by the recipe.

Consequently the parameterized path needs an explicit **assignment/grouping and plant-sharing contract**, not merely more coil options. Keep current grouping and reuse behavior for the existing catalogue/NECB path; add explicit-group and explicit-resource-binding capabilities for stock incrementally. Do not silently change legacy defaults to make stock easier.

Also keep provenance separate from identity. Today the classifier resolves the prefix of a loop NAME to a catalogue system (`classify.py:624-632`). If an overridden custom system keeps its old preset name, a later read can falsely call it that unmodified preset. Custom builds should carry their actual normalized specification/version and separate preset provenance, without pretending that provenance proves current equipment identity. Existing source-name recognition can remain a legacy projection; the new stock extractor must inspect the system.

## 3. (b) Intermediate representation: scoped structure is a prerequisite

**The flat summary is reparable as a summary, not as the authoritative reconstruction representation.** Changing `dict` to a dataclass without changing its semantics would achieve little. Python dictionaries are fine JSON carriers; scope, cardinality, relationships, and observation status are what need to change.

`characterize` is not literally one flat dictionary: it already separates plants and zone groups (`classify.py:173-192`). But each group's summary unions device kinds and fuels across zones (`:1400-1429`), and terminal scanning writes one `terminal_type` repeatedly (`:1351-1357`). Stock then collapses groups by that summary and retains only combined lists (`stock/hvac.py:80-115`). A richer structure appended after this stage cannot recover the information already erased.

Use three distinct representations, even if implemented with a few small types rather than a framework:

| Representation | Contains | Does not claim |
| --- | --- | --- |
| Source observations | Scoped central services; per-zone terminal/supplemental equipment; plant connections; controls; measured values, coverage and unknowns; source identities as evidence | That observed instance assignments are portable rules |
| Portable recipe | Reusable service templates, logical service roles, parameters, transfer/grouping/scaling policies, accepted approximations | That a source zone name identifies a target zone |
| Instantiated build plan | Concrete target zones per service, explicit shared plant/resource references, resolved control targets and sizing policy | That compilation makes unobserved source facts known |

This is a **small semantic service graph**, not a graph serialization of every OpenStudio object. Nodes represent things such as an air service, a zone-terminal service, and a hot-water source; edges express "serves" and "fed by." It can be represented as typed records and IDs. No graph database or generic graph-isomorphism engine is needed.

Retain unknown equipment as a scoped unresolved observation rather than silently dropping it. Record observation completeness before asserting absence. An extractor that handles only one recovery-device type cannot establish the absence of every possible heat-recovery topology. Similarly, a physical equipment-class declaration and an inferred family remain separate evidence.

The representations also need different treatment of omission. An observation can be unknown; a portable recipe can require a decision; an executable plan must have every required choice resolved. "Recovery observed absent" becomes a definite no-recovery plan. "Recovery not examined" must not compile to the same plan unless an author explicitly supplies that assumption. Type validation should enforce this distinction rather than let each builder interpret missing keys independently.

Keep the current `classify.characterize` output stable for NECB initially. Add scoped extraction in `modeling`, reuse its low-level coil/fuel reading helpers where their semantics fit, and avoid changing the meaning of existing flags as a side effect. Longer term the old summary can be a tested projection of the richer observations; that is a separate migration, not a prerequisite for stock progress.

### Portability is an explicit modeling decision, not a matching trick

The present HVAC reader binds by exact SOURCE zone names (`stock/reader.py:490,498-504`). Whatever the product requirement, that code path does not implement general application to unrelated geometry today. Renaming zones in B is already enough to break it. Fixing classification accuracy would not close this gap.

A portable recipe should name **semantic roles** such as `office-perimeter`, `workshop`, or simply a caller-authored `terminal-conditioned-area`; the application supplies a mapping from those roles to B's zones. A target adapter may derive roles from available space-use tags and geometry, but their meaning and any fallback must be declared. These need not be NECB catalog identities, and resolving them must not require `stock` to import `codes`.

Choose an explicit instantiation rule per service: one device per bound zone, one shared loop per bound group, or another supported grouping rule. Choose an explicit capacity rule too: resize on B's loads, use a measured intensity, or preserve specified capacity when that is genuinely the requested experiment. Copying A's absolute capacity into a much larger B is not automatically more faithful than autosizing; each is a different transfer assumption. COPs, efficiency curves, control limits, and schedules also require a declared preservation/aggregation policy, not blind inheritance from a chosen backend's defaults.

For "two of four source zones have PTACs," the portable claim might be "the workshop role has PTACs; the other role does not." If those two zones have no distinguishing transferable semantics, the source cannot tell you WHICH of B's seven zones should get them. A writer can emit an incomplete binding requirement or an observed prevalence statistic, but cannot truthfully derive the transfer rule.

For example, a recipe could contain a shared ventilation-service template bound to `served-area` and a separate PTAC template bound to `locally-cooled-area`, with a constraint that the latter is a subset of the former. B's caller supplies those two sets of zones, and the PTAC service expands once per selected zone. A zonal-only recipe omits the central service by an explicit observed-absence claim. Neither case needs a new combined catalogue name. This is a proposed semantic shape, not an API the repository already provides.

If the stock study wants a prevalence policy, make its denominator explicit: conditioned floor area, number of zones, or another chosen quantity. Two of four zones is not necessarily half the area, and a thermal zone is not generally splittable by an equipment-assignment operation. An area-share allocator may need disclosed approximation or geometry subdivision; it must not secretly become "first half of alphabetically sorted zones."

This is the fundamental unavoidable uncertainty. A parameterized compiler cannot eliminate it, and neither can a fuzzy score. A study author can supply the policy once and reuse it across many buildings; asking for that input is not a failure of automation.

## 4. (c) Selection: deterministic compilation first, recommendations only for a different question

**For a building whose relevant physical structure is observed, "recommend a system" is usually the wrong question.** The task is to represent and instantiate that structure under a declared transfer policy, not guess which marketed/catalogue label the original designer intended.

A PTAC observation with no central air service should compile to a supported zone-terminal template. It should not compete against a PTAC-plus-MAU bundle because both have the substring/feature PTAC. The current `_ZONAL_FAMILY` association is exactly that larger-bundle inference (`stock/identify.py:74-75,262-268`). The library already has a zone-terminal builder that returns no central loops and accepts PTAC heating choices (`modeling/hvac/systems/zone_terminal.py:25-52,67-95`); use those capabilities deliberately rather than recovering them through score tuning.

Likewise, an observed VAV service with hydronic heat, DX cooling, hot-water supplemental baseboards, and no recovery is a specification. It does not need to be *identified as* the closest named PVAV product to be buildable.

For the supported template grammar I would use ordinary deterministic dispatch and validation:

1. Normalize the observed physical roles and parameters; preserve ambiguous/unknown fields.
2. Select a backend whose documented capability contract covers the requested template, without modifying that template.
3. Apply the authored target-binding and sizing policy, then validate the concrete plan.
4. Report unsupported features, unresolved inputs, or incompatible combinations explicitly. Do not select the least-incompatible backend.

The dispatch may involve a small rules table or checking several backend capability predicates. That is constraint checking, but it does not yet justify a general constraint solver. If several backends realize the same supported semantics, choose a documented implementation preference or expose that choice; do not pretend a preference is evidence about the source.

**A deterministic lookup into the SAME fixed rows is not enough.** It would remove score instability but still fail on unenumerated valid combinations. **A solver over the current flat facts is not enough either.** It would solve an information-depleted problem more rigorously. Change the representational unit and the evidence boundary before choosing a fancier search algorithm.

Where a recommender remains useful:

- The user asks for an intentional retrofit or an approximate archetype rather than preservation.
- An unsupported source topology requires a choice among substitute implementations.
- A source field really is unknown, and the author wants plausible assumptions to review.

In those modes, I would recommend **explicit changes to the specification**, not silently substitute an entire winning bundle. Show known-preserved properties, changed properties, unknowns, and unsupported requirements. Prefer non-dominated alternatives where possible: an option that changes no fewer requested properties and offers no user-selected advantage should not outrank a strictly better one. Ranking among remaining alternatives requires a user/study objective (cost, supported implementation, or an explicitly chosen approximation policy); it cannot be derived from arbitrary credits for matching hydronic coils and baseboards.

The current scorer's duplicated interpretation of row dialects and defaults (`identify.py:124-142,178-240`) and its own account of failed composite-field merging (`:528-547`) are evidence that this is already becoming an incomplete second implementation of the builders. Continuing to expand that interpreter is work I would stop. The existing ranked list may remain as a clearly labelled legacy catalogue browser, but it should not be the planner's mandatory input.

## 5. (d) What I would keep, replace, and minimally repair

| Component | Decision |
| --- | --- |
| `classify.characterize` for NECB | Keep its API and behavior initially. Its summaries answer a different consumer's questions and have extensive adjudicated coverage. Reuse extraction helpers, not necessarily its final summary as stock's input. |
| `stock.identify` as the normal build selector | Replace. Keep an opt-in suggestion/browser endpoint if it is useful; do not make successful row identification a prerequisite for stock generation. |
| Catalogue names and shipped rows | Keep as stable presets and tested product examples. No automatic creation of a new row for every imported combination. |
| Family builders and component helpers | Reuse. Add narrowly scoped validated entry points and explicit assignment/resource capabilities where the existing behavior is insufficient. |
| Flat `descriptive` recipe section | Retain only as a human-readable/legacy summary. Introduce a versioned scoped template representation for executable stock recipes. |
| Compatibility/authorization checks from the first review | Keep as the boundary around compilation and deliberate substitutions, not as the only improvement to the old fuzzy pipeline. |

**Minimum viable repair if a redesign cannot begin yet:** stop automatically executing contradictory top candidates in a preservation mode; require a selected system plus explicit accepted differences, preserve the available scope when validating it, and make target-role binding an explicit caller input rather than source-name coincidence. Treat those as containment. They cannot recover zonal distinctions already merged away, and they will legitimately refuse cases that the current heuristic "handles."

**Minimum viable architectural replacement:** one scoped observation schema, one supported parameterized service template, explicit role-to-target-zone bindings, one validated backend adapter, and public-path A-to-B acceptance tests. It can coexist with the legacy API without migrating every family or every compliance caller.

What I would NOT spend the next week doing:

- Adding another large negative weight for each observed absence.
- Enumerating all baseboard/recovery/coil/fuel combinations as catalogue rows.
- Replacing the whole `classify` API and forcing NECB to migrate simultaneously.
- Building an unrestricted SDK graph serializer, universal HVAC solver, or generic plugin framework.
- Calling an arbitrary `config` dictionary a new architecture without handling unused options, grouping, plant sharing, controls, and default provenance.
- Treating retained source zone names or a guessed space-type mapping as portability.

### Package ownership and compatibility

Keep neutral observations, equipment/template types, physical validation, and concrete SDK construction in `btap.modeling`. Put stock's source-to-template abstraction, aggregation, transfer assumptions, role binding, and approximation authorization in `btap.stock`. Keep NECB rule election and its reference assignment policy in `btap.codes`. Both upper layers use `modeling`; neither imports the other. Do not introduce shipped vintage tables in stock to fill unknown parameters.

Use an explicit new recipe schema/version or explicitly versioned executable HVAC section. The current writer declares schema 1 and the reader rejects unknown schema values (`stock/writer.py:12`; `stock/reader.py:544-548`). Do not reinterpret old missing keys as measured absence when migrating. Preserve a documented legacy path; a migration should carry unknowns and ask for missing transfer assumptions rather than "upgrade" a guess into an observation.

Normalized build specs need stable semantics across library updates. Either serialize effective parameter values, including the accepted sizing/performance policy, or retain an immutable/versioned preset reference with overrides. A mutable preset name alone is not a reproducible specification. Distinguish observed values, authored transfer choices, and accepted backend defaults in the audit. This is especially important because builders already accept a partial performance profile merged over defaults (`modeling/hvac/performance.py:61-81`).

## 6. (e) One week: prove the replacement on one portable vertical slice

**My first action would be to write the failing A-to-B acceptance case, not to tune `identify` or draft a universal schema.** Make A and B have different names, zone counts, and areas. Bind named semantic roles on B explicitly. If a design cannot handle that test, it has not addressed the product requirement.

I would choose **zonal PTAC service with explicit absence of central air service** as the first executable slice. It directly challenges #220, has an existing no-central-loop backend, and avoids making hidden VAV facade grouping the first dependency. This is not a promise to reproduce every existing water-heated PTAC, schedule, plant topology, or ventilation mode in five days.

| Time | Concrete work and exit condition |
| --- | --- |
| Day 1 | Define the transfer contract in executable examples: A has PTACs on one role and none on another; B has different names/counts/areas and an explicit binding. Assert zero invented central loops, correct equipment on each bound zone, and no equipment on excluded roles. Include unknown/unrecognized source equipment and missing target bindings as explicit failures. |
| Day 2 | Extract the supported PTAC observations BEFORE group union: heating mechanism and source, cooling mechanism, ventilation behavior, presence/activity, relevant performance and control inputs, and source membership as evidence. Emit portable templates with role/binding requirements, not candidate names. Use explicit supported/unreadable states rather than a default-filled universal structure. |
| Day 3 | Add the minimal validated parameterized backend path, sharing builder implementation. Start with the PTAC heating/ventilation/control forms actually supported end-to-end. Validate unknown options and dependencies before mutation. Keep the catalogue API unchanged; give custom builds truthful identity/provenance. Do not quietly accept local-OA or availability behavior that the backend cannot reproduce. |
| Day 4 | Wire source extraction -> recipe -> target bindings -> plan -> construction through the public stock path. Set properties on the created service objects, not model-wide. Check the result against the instantiated plan, including absence and unserved roles. Use a disposable target or otherwise prevent publishing a partial build after a refusal. |
| Day 5 | Run focused A-to-B and invalid-combination tests, relevant builder/catalogue contracts, import checks, and unchanged NECB selection coverage where shared code moved. Exercise the supported builds in serial sizing runs before claiming a validated HVAC implementation; inventory alone does not establish that. If the time or environment cannot support this, label the result an experimental slice rather than completed support. Follow the repository's clean-tree freeze procedure if frozen outputs intentionally change. Document the supported slice and leave other systems explicitly on the legacy/unsupported route. |

The final acceptance assertion is not equal A/B equipment count or annual energy. It is that **B satisfies the declared transfer plan**: e.g. one PTAC per selected target zone, no central air loop, preserved supported equipment/control choices, and the declared sizing policy. B may need more capacity and more units because its geometry differs.

For a hydronic PTAC, a declared plant binding is additional work. The existing terminal builder supports water heating (`zone_terminal.py:74-80`), but that alone does not specify whether one or multiple source plants should be shared on B, nor preserve pumping and temperature behavior. Support a narrowly declared plant case if it fits the week; otherwise report it as unsupported. Shipping the electric/no-central service slice correctly is more valuable than claiming all PTACs while quietly falling back to a gas-boiler preset's assumptions.

As the next slice, add central VAV plus optional supplemental zone service and recovery, **after** exposing exact target grouping and resource-sharing behavior. Its paired regression should demonstrate that baseboards and recovery vary independently without adding catalogue names. The existing HRV validator also requires effectiveness, frost, bypass, and parasitic-power inputs (`systems/vav_reheat.py:59-85`); one observed `True` cannot supply those values.

If limited to maintenance rather than adding any API that week, I would implement containment and the failing portability tests instead. I would not claim that a better-ranked MAU/no-MAU choice completes portability.

## Final recommendation

**Keep the reusable mechanics; replace the stock modeling abstraction.** The problem is not that 110 is a large number, nor that every heuristic is bad. A preset catalogue is being asked to serve as an exhaustive language for observed buildings, and a recommender is being asked to author the missing semantics. Parameterized, scoped service templates plus explicit geometry-transfer policy put those responsibilities where they belong.

The previous compatibility proposal remains necessary: parameterization can introduce unsupported combinations just as easily as presets can introduce unwanted equipment. But it becomes the validator of an explicit construction plan, not a compensating layer around an inherently lossy nearest-row choice.

**Review scope:** read-only architectural assessment of the current code, not an implementation or a claim of simulated improvement. Only this requested document was changed in this follow-up. The worktree is active (reader line numbers shifted during the read); citations use the later observed locations where checked. No catalogue rows, adjudicated goldens, or source files were edited.
