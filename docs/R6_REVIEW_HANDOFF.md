# R6 implementation review handoff

**Prepared:** 2026-09-02
**Review target:** `532d097a2c640e89e4f6740b8f64e660389a9a32`
**Branch:** `python-d80-r5-pr5-docs`
**Base before the R6 implementation sequence:** `23205f1201b67fc7539e6f6e99ab7531e2aeb505^`
**Retirement authority:** D-84 in `docs/necb_decisions.md`
**Status:** CLOSED at `bb28cf6`. Two review rounds, all findings resolved,
full four-job dispatch green — see "Review closure" below.

## Review closure

Two rounds, both findings-first, both against a running system rather than
the diff alone.

**Round 1** (target `532d097`) found one blocking defect, four medium and
seven low/residual items — resolved in `c01a8ed`, summarised under "Opus
review resolution" below.

**Round 2** (target `c01a8ed`) verified those repairs by re-running the
original probes, and found two more:

- **`_vrf_class` could not see what it was classifying.** The class was
  inferred from `unit.terminals()`, but the reference transform strips
  them, so EVERY VRF in a reference model answered "air conditioner" —
  cooling-only rows applied to a heat pump, and the heating minimum
  skipped with no audit line, because both sat behind one flag. The
  frozen `corpus-none-08-vrf` baseline had recorded exactly that.
  `c5e8010` made the class require evidence and warn without it; `c0f12ba`
  removed the cause, so the reference no longer carries a VRF outdoor unit
  serving no zone. D-85 records both halves.
- **`_apply_chiller` had dropped the applied COP from its audit value.**
  The value and the model-name suffix shared one string and the name's
  compact `57tons 1.2kW/ton` form won. The COP is the determination an AHJ
  reads; the two are now separate (`c0f12ba`).

Round 2 also fixed a test-isolation defect that made the documented local
command unreliable: `tests/support.py` sets `BTAP_ENERGYPLUS` process-wide,
so under `-n auto` the override rung answered for the companion rung under
test. Two engine tests failed in parallel and passed serially.

**Closing evidence** — dispatch run
[`33587044533`](https://github.com/canmet-energy/btap/actions/runs/33587044533),
head `bb28cf6`, all four jobs success at STEP level, not merely rollup:
live Leg C `23/23 tests, 0 skips` with `LEGACY_PIN_REQUIRED=1` and
`fresh export ≡ committed goldens across 11 groups`; the pinned SmallOffice
whole-building gate `4 passed`; verify and parity frozen lanes; installed-wheel
smoke. Locally: 863 passed, verify 3/3, parity 2/2, Ruff clean, import
contracts 3 kept / 0 broken.

Do NOT read acceptance from this branch's `pull_request` run
(`33587040725`): its `verify` and `parity` jobs are SKIPPED by design.

**One thing left unexplained.** Two files deleted by `efb37cf` —
`python/tests/test_fixture_drift.py` and
`btap-necb/lib/btap_necb/data/decisions.json` — reappeared in the working
tree at 03:06 on 2026-09-02, byte-identical to their `efb37cf^` versions,
alongside 73 tracked files whose mtimes were rewritten with content
matching HEAD. HEAD never moved (no `checkout:` reflog entry, no stash),
which is the signature of a pathspec-scoped `git checkout <commit> -- …`
or `git restore --source=…`: that form leaves no audit trail and does not
delete files absent from the target. The actor could not be identified.
Nothing shipped from that state — the push was made from a verified clean
tree — but a `git add -A` from whatever did it would silently reverse the
R6 deletion.

## Opus review resolution

Opus reviewed the implementation on 2026-09-02 and found one blocking defect,
four medium defects, and seven low/residual items. The blocking and medium
findings were accepted and repaired before this handoff was finalized:

- Purchased-cooling identity is persisted on each generated chiller, and
  `_apply_chiller` now applies COP 2.802 on every efficiency pass. Direct and
  real EnergyPlus sizing tests reproduce the second-pass sequence.
- Variant mockups no longer check the impossible `level == "error"`; sizing
  mode requires an attached reference SQL file and the post-sizing completion
  audit marker.
- The disposition ledger again names the four deleted drivers, and its test
  requires those paths to remain absent. The one-shot R6 re-freeze validator is
  classified as archive.
- Both Table-I air-conditioner and air-source heat-pump rows are vendored.
  Cooling/heating are applied independently, and cooling-only VRF is tested.
- D-85 rules that VRF code minimums are assigned exactly, consistent with
  other equipment appliers; an initially better COP is deliberately replaced
  in tests.

Low findings also repaired: current registry/doc maintenance instructions no
longer point at the retired Ruby sync; the lighting matrix gate pins real
schema/state invariants; local oracle source resolution uses the Bundler gem
spec rather than a remote basename; and all systematic one-unit heat-pump
cooling/heating bin gaps were closed under the strict-min/inclusive-max lookup
rule. The unreachable Ruby-seal helpers in hash-pinned `freeze.py` remain
deliberately until a future behavior-driven re-freeze; they are not a live path.

## Reviewer brief

Review this as an irreversible architecture migration plus five code-conformance
corrections, not as one mechanical deletion. The key claims to challenge are:

1. The last Ruby/Python coexistence evidence was captured before active seals
   became Python-only.
2. Every durable capability formerly owned by a product gem either moved to
   Python, was explicitly retained as oracle infrastructure, or was deleted by
   an audited disposition.
3. The post-handoff re-freeze changed only evidence paths, seal metadata, and
   their resulting provenance before product Ruby was deleted.
4. Product Ruby is gone, but the pinned external Ruby oracle remains live and
   continuously exercised.
5. The post-retirement conformance fixes are based on printed NECB requirements,
   not legacy parity, and every intentional oracle divergence is explicit.

The most useful review is findings-first. In particular, inspect the review
questions near the end rather than treating green CI as sufficient proof.

## Final architecture

The repository now contains one product implementation: the Python distribution
`canmet-btap`, imported as `btap`. Its package dependency direction remains:

```text
btap.necb -> btap.costing -> btap.modeling -> btap.audit
btap.simulation -> btap.audit
```

Import-linter enforces those arrows and the SDK-free audit floor.

Ruby now has one deliberate role only:

- `legacy_pin/` bundles the pinned `openstudio-standards` oracle revision.
- `verification/oracle/` contains Ruby probes for that external oracle.
- Product code has no `openstudio-standards`, measure, legacy BTAP, or product
  Ruby dependency.

The five deleted product trees were:

- `btap-audit/`
- `btap-simulation/`
- `btap-modeling/`
- `btap-costing/`
- `btap-necb/`

Current verification has two independent parts:

- 35 frozen Python pipeline scenarios in `verification/scenarios/`, divided
  into `python` (30), `verify` (3), and `parity` (2) lanes.
- Live Python-versus-pinned-oracle Leg C under `legacy_pin/` and
  `verification/oracle/`, including the whole-building SmallOffice gate.

## Review route by phase

### 1. Retirement prerequisites and tooling ports

**Commit:** `23205f1201b67fc7539e6f6e99ab7531e2aeb505`
**Subject:** `r6: port retirement prerequisites before final attestation`

This checkpoint combined the narrow PR-A1 hardening and PR-A2 Python ports.
Most of its large insertion count is rescued OSM fixture data, not handwritten
logic.

Key changes:

- Pinned NECB archetype cache recipe now includes:
  - `legacy_pin/REF` bytes;
  - oracle generator digest;
  - EPW digest and filename;
  - complete generator arguments.
- `verification/oracle/gen_legacy_archetype.rb` writes a sidecar containing the
  actually locked oracle revision, fuel, and ECM arguments.
- The Kiva archetype successor inspects `result.reference_model`, not the
  original proposed model, and fails on missing constructions, missing Kiva
  associations, failed layered conversions, or non-regular layers.
- `verification/r6_disposition.json` became the machine-checked ownership list
  for verification survivors, archives, ports, and deletions.
- A vacuous lighting-control dictionary assertion was replaced with a real
  contract.

Durable tools ported to Python:

- shared HTTP/SSE JSON-RPC HBIX client (`python/btap/_mcp.py`);
- Section 8.4 fetcher;
- building-stock adapter;
- rule-key orphan lint;
- decisions TOC generator;
- package and Section 8.4 coverage generators;
- legacy fork drift report;
- Section 8.4.6 curve probe;
- NECB archetype sweep.

The HBIX client was authenticated against all six configured services during
implementation: codes, geocoding, weather, building-stock, modelling, and
simulation. These calls were read-only and did not expose the key.

Nine variant mockup OSMs and their manifest moved into Python fixtures. Ten
manifest-driven reference-route tests cover purchased energy, residential
copy/redirect routes, System 2, System 5, kitchen hood, refrigerated, unheated,
and heat-pump selections.

### 2. Final cross-language attestation

**Attested commit:** `85ab14352677093e24038d933cf1071e5b03431a`
**GitHub Actions run:** `33544573991`
**URL:** https://github.com/canmet-energy/btap/actions/runs/33544573991

This is intentionally immutable. It is the final authority for product
Ruby/Python coexistence and predates the seal transition and evidence rewrite.

Recorded evidence:

- 45 Ruby parity runs;
- 629 Ruby parity assertions;
- zero Ruby parity skips;
- Ruby SmallOffice: 3 runs / 62 assertions / zero skips;
- Python SmallOffice successor: 4 tests passed;
- live Leg C: 23/23;
- frozen parity scenarios passed;
- lint, Python, verify, and all then-existing gem matrix jobs passed.

The first dispatch failed before testing because `python3-venv` was installed
after venv creation. Commit `85ab143` moved that installation earlier and the
replacement run passed. Do not cite the failed run as behavioral evidence.

### 3. Post-handoff seal schema

**Commit:** `cbce093dd35c37982b79fc9fa8f3b54e9f5ff4f9`
**Subject:** `r6: preserve final attestation in post-handoff seals`

The 31 formerly cross-language active seals became
`python-only:post-handoff`. Each retains:

- original `retired_seal` (`ruby` for 29, `ruby-api:*` for 2);
- final cross-language commit;
- final run ID and URL;
- transition reason.

The four scenarios that were already Python-only retain their historical
classification. Tests reject any active `ruby` or `ruby-api` seal and require
all 31 historical records to agree on the immutable attestation.

Review `verification/scenarios/scenario_defs.py`, `manifest.json`, and the seal
accounting in `freeze.py` together. The active seal must not imply that a later
Python-only re-freeze recreated cross-language evidence.

### 4. Python evidence authority and installed reference data

**Commit:** `601961b4914d6a94123c22d4f886d6889589d241`
**Subject:** `r6: move evidence and references to Python authority`

An explicit 87-entry migration ledger in
`python/tests/data/coverage_code_ref_mapping.json` rewrote all coverage code
references:

- 12 manifests;
- 241 coverage entries;
- 313 reference uses;
- 87 unique old-to-new mappings;
- zero remaining live product-Ruby destinations.

`python/tests/test_coverage_code_refs.py` parses Python with `ast` and checks:

- every destination path exists;
- every `path#symbol` resolves;
- all 87 historical mappings were consumed with their exact occurrence count;
- the current inventory remains non-vacuous.

Durable documentation moved to root `docs/`. `docs/necb_decisions.md` remains
hand-authored except for its generated TOC; the two coverage reports are fully
generated.

Section 8.4 reference caches moved to
`python/btap/necb/data/coverage/` and ship in the wheel. The installed
`btap.necb.coverage` API and `btap-necb-coverage` CLI expose them offline.
`ATTRIBUTION.md` distinguishes the Crown NECB text from LGPL package source.
Wheel smoke checks both editions, article counts, provenance, and attribution.

D-84 was added to the canonical Python decisions registry and authored decision
document. It records the retirement, oracle survival, final attestation, seal
transition, evidence migration, and deletion boundary.

### 5. Hardened and accepted post-handoff re-freeze

**Freezer hardening commit:** `243cedbcd5b6a63ff0c981293236391740b68a27`
**Accepted freeze commit:** `906d30ed5ba18592c986d30a9655f05c956c592c`

An initial freeze under system Python lacked `canmet-tbd` and degraded three
thermal-bridging artifacts. The validator rejected the unexpected changes and
the generated files were restored. `freeze.py` was then hardened to require
`canmet-tbd==3.5.2` in its own interpreter whenever the thermal scenario is
present.

The accepted freeze ran with `python/.venv/bin/python` from a clean tree.
`verification/scenarios/r6_refreeze_diff.json` records:

- 134 baseline files checked;
- exactly 46 evidence files changed;
- exactly 23 scenarios with evidence-content changes;
- exactly 31 seal transitions;
- active seals: 31 post-handoff and 4 historical Python-only;
- retired seals: 29 Ruby and 2 Ruby API;
- zero unexpected changes.

All frozen lanes passed after promotion: Python 30/30, verify 3/3, parity 2/2.
The freezer itself is manifest-hashed; avoid formatting or editing it casually.

### 6. Product Ruby deletion and orchestration cleanup

**Commit:** `efb37cf1365299b17819613f5782ae76b9a7ba86`
**Subject:** `Retire product Ruby gems at R6`

Scope: 380 files changed, 350 files deleted, approximately 306,000 lines
removed. The five product gem trees and gem-dependent drivers were deleted.

Retired verification drivers included:

- `verification/run_corpus.rb`;
- `verification/selftest.sh`;
- `verification/matrix.sh`;
- obsolete bootstrap and dormant cross-language product drivers/tests.

The survivor list remains machine-checked in `verification/r6_disposition.json`.
The request manifest keeps hashes for deleted source files as historical
provenance; those are not live path dependencies and should not be rewritten.

Rake and `.github/workflows/test.yml` were rebuilt around four jobs:

- `lint`: orphan keys, AST code references, generated coverage, decisions;
- `python`: import contracts, Ruff, suite, installed-wheel smoke;
- `verify`: full required-dependency Python suite, rule verification, verify
  frozen lane;
- `parity`: pinned SmallOffice, live Leg C, parity frozen lane, optional golden
  export.

Ruby setup remains only where the oracle bundle requires it.

A post-delete full-suite run exposed two local ownership issues that were fixed
before commit:

- weather discovery lost Toronto when the gem fallback disappeared; it now uses
  the Python-owned checkout fixture path;
- engine archive/absence tests were contaminated by the correctly installed
  `canmet-energyplus` dependency; tests now explicitly simulate companion
  absence when exercising lower-priority fallback rungs.

**Post-retirement CI:** run `33561399726` at `efb37cf` passed all four jobs,
including installed-wheel smoke, SmallOffice, live Leg C, and both non-default
frozen lanes.

## Post-retirement conformance fixes

These corrections deliberately follow printed NECB requirements where the
legacy implementation/oracle is wrong. Each implementation is a separate
commit; generated baseline/report changes are separate where applicable.

### Purchased-cooling reference chiller COP

**Commit:** `37d275c9ea15f41d661311c595ba028eed3ce2d0`

Generic air-cooled equipment under Table 5.2.12.1-K retains COP 2.866.
Purchased-cooling representation is a different reference-building rule:
Table 8.4.3.5 requires COP 2.802.

The selection config carries `purchased_cooling_reference_cop`. The reference
builder tags only chillers created by purchased-cooling assignments. Every
efficiency pass reads that persistent object tag and applies 2.802 instead of
the generic Table-K COP, including the post-reference-sizing pass in
`compliance.py`. The chiller name and audit value no longer claim the generic
Table-K kW/ton value when the Table 8.4.3.5 override applies.

Evidence includes a direct hard-sized second-pass regression and a real
EnergyPlus reference-sizing test. Frozen effect remains none because no frozen
scenario reaches this purchased-cooling route.

### NECB 2020 small heat-pump cooling

**Commit:** `580d8b886ce5ba623d38a047b12faacb858002fb`

Four small heat-pump rows (single/split package x two heating types) changed
from Table-B SPVAC EER 11 to the explicit Table-A heat-pump class, SEER 15.
D-59 and D-60 prose/registry summaries were revised so they no longer preserve
the old legacy-parity interpretation as a valid cross-edition difference.

Direct data and model-level tests require both 2020 and 2025 to produce the
SEER 15 cooling COP below 19 kW. The genuine edition difference that remains is
small split-system heating HSPF 7.4 (2020) versus 7.8 (2025).

Frozen effect: none; existing frozen heat-pump equipment does not land in the
small cooling bin.

### VRF Table 5.2.12.1-I

**Implementation commit:** `6781a648b17a0c5d5b342206e5310026c09e4dd6`
**Baseline commit:** `df3069eae07c1b5d8849a82bf7e2347af0e20240`

The 2020 and 2025 tables were fetched from HBIX during implementation. The
product implements both the four air-conditioner cooling rows and four
air-source heat-pump cooling/heating rows. D-85 selects heat-pump rows when an
attached terminal has a VRF DX heating coil; otherwise it selects the
air-conditioner rows.

| Capacity | Cooling minimum | Heating minimum |
|---|---:|---:|
| `< 19 kW` | SEER 15 | HSPF 7.8 |
| `19-<40 kW` | EER 10.8 | COP 3.30 |
| `40-<70 kW` | EER 10.4 | COP 3.20 |
| `>=70 kW` | EER 9.3 | COP 3.20 |

Behavior:

- Cooling and heating capacities are binned independently.
- Seasonal/full-load ratings use the same no-fan conversions as other DX
  equipment.
- Selected code minimums are assigned exactly; better builder/proposed COPs are
  not retained by the minimum-efficiency pass.
- Cooling-only units receive the higher air-conditioner cooling row without
  requiring a heating capacity.
- Unsized units warn loudly with a Table-I citation.
- Non-air-cooled classic OpenStudio VRF units warn rather than guessing among
  water, groundwater, and ground-source Table-I classes; OpenStudio's condenser
  type does not distinguish those source classes.

Evidence includes exact data ladders for both editions, heat-pump and
cooling-only model tests, exact assignment from COP 5.0, separate unsized-mode
warnings, and a real EnergyPlus sizing/application test. The 2025 table's
single-phase SEER2/HSPF2 row remains unselected because the model carries no
evidence that distinguishes that class.

Frozen effect is intentionally narrow: only `corpus-none-08-vrf` changed, and
only because its unsized model now emits the required warning. Changed files:
`audit.json`, `audit.txt`, `report.json`, `stdout.txt`, plus manifest hashes and
clean source-commit provenance. The other 34 scenarios stayed byte-identical.

### Split-system heat-pump capacity breakpoint

**Commit:** `a6963cc6dece842fd624159ced86cbe38e7eba43`

The original four-value `136841.0` typo correction exposed a systematic
one-unit boundary convention that is invalid for floating capacities under the
lookup rule `minimum < capacity <= maximum`. All 48 discontinuities across the
2020/2025 cooling and heating ladders now use the preceding row's maximum as
the next row's minimum. A direct test checks every adjacent boundary in every
edition/package/heating combination.

Frozen effect: none; no scenario lands in the typo gap.

### Storage-room receptacle loads

**Commit:** `e26794e00585a6d7447208b6e7a554b0b8cea016`

Table A-8.4.3.2.(2)-B values were transposed in the legacy-vendored data.
Twenty-two rows changed in the shared 2020 data table used by both editions:

- 11 schedule variants for `Storage room < 5 m2`: 1 W/m2 -> 0 W/m2;
- 11 schedule variants for `Storage room >= 5 m2`: 0 W/m2 -> 1 W/m2.

The JSON stores electric equipment density in W/ft2, so 1 W/m2 is represented
by the established value `0.0929368029739777`.

The committed oracle golden was not hand-edited. Instead,
`test_oracle_goldens_loads.py`:

- asserts the exact old oracle value and corrected product value on both sides;
- permits exactly 22 named storage-field differences;
- normalizes only those fields;
- still demands exact row ordering, key sets, schedules, and all other values.

Review concern: this normalization is intentionally strict but is also the most
sensitive product-over-oracle exception in the patch. Verify that matching by
storage name prefix cannot admit unrelated future rows without the count and
old-value assertions failing.

Frozen effect: none; no frozen scenario selects these storage space types.

### Generated coverage

**Commit:** `532d097a2c640e89e4f6740b8f64e660389a9a32`

`docs/NECB_8_4_COVERAGE.html` was regenerated after source-line movement and the
new Table-I citation. Two consecutive generations were byte-identical and the
committed-byte test passes. `NECB_COVERAGE.md` did not change.

## Validation evidence

### Final PR-C workflow

**Run:** `33573754086`
**Head:** `532d097a2c640e89e4f6740b8f64e660389a9a32`
**URL:** https://github.com/canmet-energy/btap/actions/runs/33573754086
**Conclusion:** success

Every executed substantive step passed:

- `lint`: orphan-key lint, AST code references, deterministic coverage docs,
  decisions registry/TOC/runtime citations;
- `python`: dependency contracts, Ruff, complete Python suite, installed-wheel
  smoke;
- `verify`: generated sample corpus, pinned thermal stack, NECB rule
  verification, full required-dependency suite with `FULL_MATRIX=1`, verify
  frozen lane;
- `parity`: pinned SmallOffice whole-building gate, live Leg C, parity frozen
  lane.

Golden export/upload steps were skipped because `export_goldens=false`; this is
expected. Exporting legacy goldens for product conformance corrections would be
wrong unless `legacy_pin/REF` itself changed.

### Local focused evidence

- Purchased-cooling neighbors: 40 passed.
- Small-HP data/model/registry slice: 26 passed.
- VRF direct efficiency/provenance: 18 passed.
- VRF topology/classification neighbors: 24 passed.
- Capacity-break provenance: 13 passed.
- Storage loads neighbors: 19 passed.
- Loads oracle-golden suite: 3 passed.
- Frozen Python lane after VRF re-freeze: 30/30 subtests.
- Frozen verify lane: 3/3 subtests.
- Frozen parity lane: 2/2 subtests.
- Ruff: clean.
- Import contracts: 3 kept, 0 broken.
- Clean installed-wheel smoke completed real sizing with the independently
  packaged `canmet-energyplus` companion.

Two local xdist reruns reached 98-99% with no failure marker but lost their
summary/exit marker due the known VS Code terminal capture problem. They are not
counted as passes. The final GitHub `python` and `verify` jobs are the
conclusive complete-suite evidence.

## Intentional non-changes

- `legacy_pin/REF` did not move.
- Oracle goldens were not regenerated for product conformance corrections.
- Historical source paths in the 87-entry migration ledger, request-manifest
  bootstrap provenance, and period decision records remain intentionally.
- The four pre-existing Python-only scenario classifications were not rewritten.
- Frozen machinery files were not reformatted merely to satisfy a broader-than-CI
  Ruff invocation; CI scopes Ruff to `python/`.
- Product behavior does not claim NECB 2011-2017 support.

## Residual review questions and known cleanup

These are not hidden by the successful workflow:

1. `.github/workflows/test.yml` still permits `schedule` in the `parity` job
   condition even though the workflow declares no schedule trigger and current
   repository guidance says parity is dispatch-only. This is dead condition
   text, not a runtime failure, but should be cleaned or explicitly justified.
2. Some workflow comments still say "gems" where the current owner is a Python
   domain/package. Treat as terminology cleanup unless it changes a command or
   path.
3. The public GitHub repository description observed during CI still described
   "nine standalone ... gems." That metadata is outside this tree and should be
   updated separately.
4. Review whether D-59's historical wording now makes the correction chronology
   clear enough; it was changed in place to stop presenting EER 11 as valid.
5. Review whether the purchased-cooling COP belongs as a rule-data value in both
   reference-rule files or would be better represented in a dedicated Table
   8.4.3.5 data family.
6. Review whether the VRF implementation should eventually vendor all Table-I
   source classes with an explicit model input for source classification rather
   than warning for non-air-cooled units.
7. Review the storage oracle normalization carefully. It is intentionally an
   exception to ordinary exact Leg-C equality and must remain narrow.
8. `freeze.py` retains unreachable product-Ruby seal helpers and paths because
  it is manifest-hashed. Removing them is safe only with an explicit machinery
  hash update and clean-tree re-freeze; no current runtime path can call them.

## Suggested review commands

From the repository root:

```bash
# Commit boundaries
git log --oneline 23205f1201b67fc7539e6f6e99ab7531e2aeb505^..532d097a2c640e89e4f6740b8f64e660389a9a32

git show --stat 23205f1201b67fc7539e6f6e99ab7531e2aeb505
git show --stat cbce093dd35c37982b79fc9fa8f3b54e9f5ff4f9
git show --stat 601961b4914d6a94123c22d4f886d6889589d241
git show --stat 906d30ed5ba18592c986d30a9655f05c956c592c
git show --stat efb37cf1365299b17819613f5782ae76b9a7ba86

# Conformance-fix range
git diff efb37cf1365299b17819613f5782ae76b9a7ba86..532d097a2c640e89e4f6740b8f64e660389a9a32

# Fast repository gates
python3 python/scripts/necb_orphan_keys.py
python3 python/scripts/generate_decisions_toc.py --check
cd python
.venv/bin/lint-imports
.venv/bin/ruff check .
.venv/bin/pytest -q \
  tests/necb/test_hvac_efficiency_provenance.py \
  tests/necb/test_hvac_necb_efficiency.py \
  tests/necb/test_hvac_necb_energy_recovery.py \
  tests/necb/test_loads_data_integrity.py \
  tests/necb/test_oracle_goldens_loads.py

# Full local suite
BTAP_SDK_REQUIRED=1 BTAP_TBD_REQUIRED=1 BTAP_SCENARIOS_REQUIRED=1 \
  .venv/bin/pytest -n auto -q tests/
```

For authoritative CI evidence, inspect workflow runs `33544573991`,
`33561399726`, and `33573754086` by exact head SHA. Do not infer R6 acceptance
from a PR-level green rollup that skipped dispatch-only jobs.

## Expected reviewer output

Please return findings ordered by severity with file/symbol references. Focus on
behavioral errors, weakened verification, over-broad oracle exceptions,
misstated NECB requirements, packaging omissions, and provenance gaps. If no
blocking issue is found, state that explicitly and list residual risks or test
gaps separately.
